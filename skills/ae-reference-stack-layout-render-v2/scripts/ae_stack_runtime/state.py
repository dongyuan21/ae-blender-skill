from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .common import (
    SCHEMA_VERSION,
    artifact_ref,
    atomic_write_json,
    exclusive_lock,
    now_iso,
    read_json,
    sha256_file,
    write_json,
)
from .contracts import (
    GATE_STATUSES,
    MATURITIES,
    NODES,
    PREREQUISITES,
    descendants,
    eligible_nodes,
    validate_node_artifact,
)


_SAFE_NODE = re.compile(r"^[A-Z0-9_]+$")


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} must be inside the run directory: {path}") from error


class StateStore:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self.state_dir = self.run_dir / "state"
        self.receipts_dir = self.state_dir / "receipts"
        self.current_path = self.state_dir / "current.json"
        self.lock_path = self.state_dir / ".state.lock"

    def require_initialized(self) -> None:
        if not self.current_path.is_file():
            raise FileNotFoundError(f"State store is not initialized: {self.current_path}")

    def read_current(self) -> dict[str, Any]:
        self.require_initialized()
        return read_json(self.current_path)

    def state_sha256(self) -> str:
        self.require_initialized()
        return sha256_file(self.current_path)

    def initialize(self, run_id: str, initialization_artifact: Path) -> dict[str, Any]:
        if self.current_path.exists():
            raise FileExistsError(self.current_path)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        artifact_value = read_json(initialization_artifact)
        if artifact_value.get("artifactType") != "run-initialization":
            raise ValueError("Initialization artifactType must be run-initialization")
        receipt = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "sequence": 1,
            "node": "INITIALIZED",
            "attempt": 1,
            "gateStatus": "PASS",
            "maturity": "DRAFT",
            "createdAt": now_iso(),
            "parentReceiptSha256": None,
            "prerequisiteReceipts": {},
            "mainArtifact": artifact_ref(initialization_artifact, "run-initialization"),
            "evidenceArtifacts": [],
            "metrics": {},
            "issues": [],
            "retryFrom": None,
            "invalidatedNodes": [],
            "nextAllowed": ["CAPABILITY_PREFLIGHT_PASSED"],
            "producer": {"kind": "deterministic-tool", "name": "ae_stack init-run"},
        }
        receipt_path = self.receipts_dir / "0001-initialized-attempt-01.json"
        write_json(receipt_path, receipt)
        receipt_hash = sha256_file(receipt_path)
        current = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "revision": 1,
            "updatedAt": now_iso(),
            "activePasses": {
                "INITIALIZED": {
                    "receiptPath": str(receipt_path),
                    "receiptSha256": receipt_hash,
                    "artifactPath": str(initialization_artifact),
                    "artifactSha256": sha256_file(initialization_artifact),
                }
            },
            "latestAttempts": {
                "INITIALIZED": {
                    "receiptPath": str(receipt_path),
                    "receiptSha256": receipt_hash,
                    "gateStatus": "PASS",
                    "attempt": 1,
                }
            },
            "stalePasses": {},
            "lastReceipt": {"path": str(receipt_path), "sha256": receipt_hash},
            "eligibleNodes": ["CAPABILITY_PREFLIGHT_PASSED"],
        }
        atomic_write_json(self.current_path, current)
        return self.status()

    def status(self) -> dict[str, Any]:
        current = self.read_current()
        return {
            "runId": current["runId"],
            "revision": current["revision"],
            "statePath": str(self.current_path),
            "stateSha256": self.state_sha256(),
            "activeNodes": list(current.get("activePasses", {}).keys()),
            "activePasses": current.get("activePasses", {}),
            "latestAttempts": current.get("latestAttempts", {}),
            "stalePasses": current.get("stalePasses", {}),
            "eligibleNodes": current.get("eligibleNodes", []),
            "lastReceipt": current.get("lastReceipt"),
        }

    def _attempt_number(self, current: dict[str, Any], node: str) -> int:
        latest = current.get("latestAttempts", {}).get(node)
        return int(latest.get("attempt", 0)) + 1 if isinstance(latest, dict) else 1

    def _invalidate(
        self,
        current: dict[str, Any],
        nodes: set[str],
        reason: str,
        invalidated_by: str,
    ) -> list[str]:
        active = current.setdefault("activePasses", {})
        stale = current.setdefault("stalePasses", {})
        invalidated: list[str] = []
        for node in NODES:
            if node not in nodes or node not in active:
                continue
            stale.setdefault(node, []).append({
                **active[node],
                "invalidatedAt": now_iso(),
                "invalidatedBy": invalidated_by,
                "reason": reason,
            })
            del active[node]
            invalidated.append(node)
        return invalidated

    def commit(
        self,
        *,
        node: str,
        artifact_path: Path,
        gate_status: str,
        maturity: str,
        expected_state_sha256: str,
        evidence_paths: list[tuple[str, Path]] | None = None,
        metrics: dict[str, Any] | None = None,
        issues: list[dict[str, Any]] | None = None,
        retry_from: str | None = None,
        producer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if node not in NODES or not _SAFE_NODE.match(node):
            raise ValueError(f"Unknown node: {node}")
        if node == "INITIALIZED":
            raise ValueError("INITIALIZED can only be created by init-run")
        if gate_status not in GATE_STATUSES:
            raise ValueError(f"gateStatus must be one of {sorted(GATE_STATUSES)}")
        if maturity not in MATURITIES:
            raise ValueError(f"maturity must be one of {sorted(MATURITIES)}")
        if retry_from is not None and retry_from not in NODES:
            raise ValueError(f"Unknown retryFrom node: {retry_from}")
        if retry_from is not None and gate_status == "PASS":
            raise ValueError("retryFrom is only valid for REVISE or BLOCKED attempts")
        artifact_path = artifact_path.resolve()
        _require_within(artifact_path, self.run_dir, "artifact")
        if not artifact_path.is_file():
            raise FileNotFoundError(artifact_path)
        artifact_sha_before = sha256_file(artifact_path)
        artifact_value = read_json(artifact_path)
        if gate_status == "PASS":
            validate_node_artifact(node, artifact_value)
        normalized_evidence: list[tuple[str, Path]] = []
        for name, path in evidence_paths or []:
            resolved = path.resolve()
            _require_within(resolved, self.run_dir, f"evidence {name}")
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            normalized_evidence.append((name, resolved))

        with exclusive_lock(self.lock_path):
            current_hash = self.state_sha256()
            if current_hash.upper() != expected_state_sha256.upper():
                raise RuntimeError(
                    "State CAS mismatch: current state changed after the worker read it; "
                    f"expected {expected_state_sha256}, actual {current_hash}"
                )
            current = self.read_current()
            active = current.get("activePasses", {})
            missing = [requirement for requirement in PREREQUISITES[node] if requirement not in active]
            if missing:
                raise RuntimeError(f"Cannot commit {node}; missing active prerequisites: {missing}")
            artifact_sha_after = sha256_file(artifact_path)
            if artifact_sha_after != artifact_sha_before:
                raise RuntimeError("Artifact changed after validation and before state commit")
            prerequisite_receipts_snapshot = {
                requirement: active[requirement]["receiptSha256"]
                for requirement in PREREQUISITES[node]
            }

            attempt = self._attempt_number(current, node)
            sequence = int(current.get("revision", 0)) + 1
            invalidated_nodes: list[str] = []
            reason = f"new attempt for {node}"

            # A new upstream PASS supersedes all active descendants. A REVISE/BLOCKED
            # attempt invalidates the node itself and every descendant.
            if gate_status == "PASS":
                invalidated_nodes.extend(self._invalidate(current, descendants(node), reason, node))
            else:
                invalidated_nodes.extend(self._invalidate(current, {node, *descendants(node)}, reason, node))

            if retry_from is not None:
                retry_nodes = {retry_from, *descendants(retry_from)}
                invalidated_nodes.extend(
                    self._invalidate(
                        current,
                        retry_nodes,
                        f"QA routed retry to {retry_from}",
                        node,
                    )
                )
            invalidated_nodes = sorted(set(invalidated_nodes), key=NODES.index)

            prerequisite_receipts = prerequisite_receipts_snapshot
            evidence = [artifact_ref(path, name) for name, path in normalized_evidence]
            latest_receipt = current.get("lastReceipt") or {}
            receipt = {
                "schemaVersion": SCHEMA_VERSION,
                "runId": current["runId"],
                "sequence": sequence,
                "node": node,
                "attempt": attempt,
                "gateStatus": gate_status,
                "maturity": maturity,
                "createdAt": now_iso(),
                "parentReceiptSha256": latest_receipt.get("sha256"),
                "prerequisiteReceipts": prerequisite_receipts,
                "mainArtifact": artifact_ref(artifact_path, artifact_value.get("artifactType") or artifact_path.name),
                "evidenceArtifacts": evidence,
                "metrics": copy.deepcopy(metrics or {}),
                "issues": copy.deepcopy(issues or []),
                "retryFrom": retry_from,
                "invalidatedNodes": invalidated_nodes,
                "nextAllowed": [],
                "producer": copy.deepcopy(producer or {"kind": "agent", "model": "gpt-5.6-sol"}),
            }
            node_slug = node.lower().replace("_", "-")
            receipt_path = self.receipts_dir / f"{sequence:04d}-{node_slug}-attempt-{attempt:02d}.json"

            # Compute next state before writing the receipt so the receipt can record
            # the exact eligible continuation set.
            latest_attempts = current.setdefault("latestAttempts", {})
            latest_attempts[node] = {
                "receiptPath": str(receipt_path),
                "receiptSha256": "PENDING",
                "gateStatus": gate_status,
                "attempt": attempt,
            }
            if gate_status == "PASS":
                current.setdefault("activePasses", {})[node] = {
                    "receiptPath": str(receipt_path),
                    "receiptSha256": "PENDING",
                    "artifactPath": str(artifact_path),
                    "artifactSha256": artifact_sha_after,
                }
            receipt["nextAllowed"] = eligible_nodes(current.get("activePasses", {}))
            write_json(receipt_path, receipt)
            receipt_hash = sha256_file(receipt_path)
            latest_attempts[node]["receiptSha256"] = receipt_hash
            if gate_status == "PASS":
                current["activePasses"][node]["receiptSha256"] = receipt_hash
            current["revision"] = sequence
            current["updatedAt"] = now_iso()
            current["lastReceipt"] = {"path": str(receipt_path), "sha256": receipt_hash}
            current["eligibleNodes"] = eligible_nodes(current.get("activePasses", {}))
            atomic_write_json(self.current_path, current)
            return self.status()

    def invalidate(
        self,
        *,
        from_node: str,
        reason: str,
        expected_state_sha256: str,
    ) -> dict[str, Any]:
        if from_node not in NODES or from_node == "INITIALIZED":
            raise ValueError(f"Invalid from-node: {from_node}")
        with exclusive_lock(self.lock_path):
            current_hash = self.state_sha256()
            if current_hash.upper() != expected_state_sha256.upper():
                raise RuntimeError(
                    f"State CAS mismatch: expected {expected_state_sha256}, actual {current_hash}"
                )
            current = self.read_current()
            invalidated = self._invalidate(
                current,
                {from_node, *descendants(from_node)},
                reason,
                "manual-invalidate",
            )
            current["revision"] = int(current.get("revision", 0)) + 1
            current["updatedAt"] = now_iso()
            current["eligibleNodes"] = eligible_nodes(current.get("activePasses", {}))
            current["lastInvalidation"] = {
                "fromNode": from_node,
                "reason": reason,
                "invalidatedNodes": invalidated,
                "createdAt": now_iso(),
            }
            atomic_write_json(self.current_path, current)
            return self.status()
