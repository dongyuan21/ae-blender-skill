from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ae_stack_runtime.common import read_json, write_json
from ae_stack_runtime.route import lock_source_route
from ae_stack_runtime.run_setup import capability_preflight, init_run
from ae_stack_runtime.state import StateStore
from fixture_factory import approved_review


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ae-stack-v2-state-"))
        self.library = self.root / "library"
        self.source = self.root / "source.aep"
        self.reference = self.root / "reference.png"
        self.source.write_bytes(b"synthetic-aep-for-state-test")
        Image.new("RGB", (64, 64), (10, 20, 30)).save(self.reference)
        initialized = init_run(self.source, self.reference, self.library, "state-test")
        self.run_dir = Path(initialized["runDirectory"])
        self.store = StateStore(self.run_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cas_and_upstream_recommit_invalidate_descendants(self) -> None:
        capability_path = self.run_dir / "artifacts" / "capability-preflight.json"
        capability_preflight(
            capability_path,
            afterfx=None,
            ffmpeg=None,
            ffprobe=None,
            require_afterfx=False,
            require_ffmpeg=False,
        )
        before = self.store.status()["stateSha256"]
        self.store.commit(
            node="CAPABILITY_PREFLIGHT_PASSED",
            artifact_path=capability_path,
            gate_status="PASS",
            maturity="DRAFT",
            expected_state_sha256=before,
        )
        stale_hash = before
        with self.assertRaisesRegex(RuntimeError, "CAS mismatch"):
            self.store.commit(
                node="CAPABILITY_PREFLIGHT_PASSED",
                artifact_path=capability_path,
                gate_status="PASS",
                maturity="DRAFT",
                expected_state_sha256=stale_hash,
            )

        route_draft_path = self.run_dir / "drafts" / "source-route-draft.json"
        route_path = self.run_dir / "artifacts" / "source-route.json"
        write_json(route_draft_path, {
            "finalComp": {"id": 201, "name": "FINAL", "width": 1080, "height": 1920},
            "boardComp": {"id": 101, "name": "BOARD", "width": 1080, "height": 1920},
            "nestingPath": [{"compId": 201}, {"compId": 101}],
            "routeScope": {"compIds": [201, 101], "routeCriticalFootageItemIds": []},
            "qaBaseline": {
                "acceptedMissingKeys": [],
                "acceptedExpressionErrorKeys": [],
                "acceptedEnabledWatermarkKeys": [],
            },
            "renderSettings": {},
            "review": approved_review(),
        })
        lock_source_route(route_draft_path, route_path)
        self.store.commit(
            node="SOURCE_ROUTE_LOCKED",
            artifact_path=route_path,
            gate_status="PASS",
            maturity="DRAFT",
            expected_state_sha256=self.store.status()["stateSha256"],
        )
        self.assertIn("SOURCE_ROUTE_LOCKED", self.store.status()["activeNodes"])

        # A new preflight attempt supersedes every active descendant.
        self.store.commit(
            node="CAPABILITY_PREFLIGHT_PASSED",
            artifact_path=capability_path,
            gate_status="PASS",
            maturity="DRAFT",
            expected_state_sha256=self.store.status()["stateSha256"],
        )
        status = self.store.status()
        self.assertIn("CAPABILITY_PREFLIGHT_PASSED", status["activeNodes"])
        self.assertNotIn("SOURCE_ROUTE_LOCKED", status["activeNodes"])
        self.assertIn("SOURCE_ROUTE_LOCKED", status["stalePasses"])
        self.assertIn("SOURCE_ROUTE_LOCKED", status["eligibleNodes"])

    def test_retry_receipt_preserves_prerequisite_lineage_before_invalidation(self) -> None:
        capability_path = self.run_dir / "artifacts" / "capability-preflight.json"
        capability_preflight(
            capability_path,
            afterfx=None,
            ffmpeg=None,
            ffprobe=None,
            require_afterfx=False,
            require_ffmpeg=False,
        )
        self.store.commit(
            node="CAPABILITY_PREFLIGHT_PASSED",
            artifact_path=capability_path,
            gate_status="PASS",
            maturity="DRAFT",
            expected_state_sha256=self.store.status()["stateSha256"],
        )
        capability_receipt_sha = self.store.status()["activePasses"]["CAPABILITY_PREFLIGHT_PASSED"]["receiptSha256"]
        revise_path = self.run_dir / "drafts" / "source-route-revise.json"
        write_json(revise_path, {"artifactType": "source-route-review", "status": "revise"})
        self.store.commit(
            node="SOURCE_ROUTE_LOCKED",
            artifact_path=revise_path,
            gate_status="REVISE",
            maturity="DRAFT",
            expected_state_sha256=self.store.status()["stateSha256"],
            retry_from="CAPABILITY_PREFLIGHT_PASSED",
            issues=[{"code": "CAPABILITY_MISSING"}],
        )
        receipt_path = Path(self.store.status()["latestAttempts"]["SOURCE_ROUTE_LOCKED"]["receiptPath"])
        receipt = read_json(receipt_path)
        self.assertEqual(
            receipt["prerequisiteReceipts"]["CAPABILITY_PREFLIGHT_PASSED"],
            capability_receipt_sha,
        )
        self.assertNotIn("CAPABILITY_PREFLIGHT_PASSED", self.store.status()["activeNodes"])

    def test_commit_rejects_main_artifact_outside_run_directory(self) -> None:
        outside = self.root / "outside.json"
        write_json(outside, {"schemaVersion": 2, "artifactType": "capability-preflight", "checks": []})
        with self.assertRaisesRegex(ValueError, "inside the run directory"):
            self.store.commit(
                node="CAPABILITY_PREFLIGHT_PASSED",
                artifact_path=outside,
                gate_status="REVISE",
                maturity="DRAFT",
                expected_state_sha256=self.store.status()["stateSha256"],
            )


if __name__ == "__main__":
    unittest.main()
