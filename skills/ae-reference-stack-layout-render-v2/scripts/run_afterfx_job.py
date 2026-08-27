#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def stop(process: subprocess.Popen[bytes], grace: float = 8.0) -> None:
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def dependency_states(plan_path: Path | None) -> list[dict[str, Any]]:
    if plan_path is None or not plan_path.is_file():
        return []
    plan = read_json(plan_path)
    states: list[dict[str, Any]] = []
    for lock in plan.get("dependencyLocks", []):
        if lock.get("path") is None:
            continue
        path = Path(str(lock["path"]))
        if not path.is_file():
            raise FileNotFoundError(f"Dependency lock file is missing: {path}")
        state: dict[str, Any] = {"itemId": lock.get("itemId"), "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        expected_hash = lock.get("sha256")
        if expected_hash and state["sha256"] != str(expected_hash).upper():
            raise RuntimeError(f"Dependency hash mismatch for {path}")
        if any(key in lock for key in ["mode", "alphaExtrema", "width", "height"]):
            with Image.open(path) as image:
                state.update({"format": image.format, "mode": image.mode, "width": image.width, "height": image.height})
                if "A" in image.getbands():
                    state["alphaExtrema"] = list(image.getchannel("A").getextrema())
            for key in ["mode", "width", "height", "alphaExtrema"]:
                if key in lock and state.get(key) != lock[key]:
                    raise RuntimeError(f"Dependency {key} mismatch for {path}: {state.get(key)} != {lock[key]}")
        states.append(state)
    return states


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one isolated stateful AE-stack JSX job and protect source/dependency hashes")
    parser.add_argument("--afterfx", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--env-var", default="AE_STACK_V2_JOB")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--include-result", action="store_true", help="embed the full worker result in stdout; the result file is always preserved")
    args = parser.parse_args()

    afterfx = Path(args.afterfx).resolve()
    worker = Path(args.worker).resolve()
    job_path = Path(args.job).resolve()
    if not afterfx.is_file():
        raise FileNotFoundError(afterfx)
    if not worker.is_file():
        raise FileNotFoundError(worker)
    job = read_json(job_path)
    result_path = Path(job["resultPath"])
    input_value = job.get("projectPath") or job.get("sourceProjectPath")
    if not input_value:
        raise ValueError("Job must contain projectPath or sourceProjectPath")
    input_project = Path(str(input_value))
    if not input_project.is_file():
        raise FileNotFoundError(input_project)
    protected = Path(str(job["protectedSourcePath"])) if job.get("protectedSourcePath") else None
    if protected is not None and not protected.is_file():
        raise FileNotFoundError(protected)
    output = Path(str(job["outputProjectPath"])) if job.get("outputProjectPath") else None
    plan_path = Path(str(job["planPath"])) if job.get("planPath") else None

    input_before = sha256(input_project)
    protected_before = sha256(protected) if protected else None
    locks_before = dependency_states(plan_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment[args.env_var] = str(job_path)
    process = subprocess.Popen([str(afterfx), "-m", "-r", str(worker)], env=environment)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if result_path.is_file() and result_path.stat().st_size:
            break
        if process.poll() not in (None, 0) and not result_path.exists():
            raise RuntimeError(f"AfterFX worker exited with code {process.returncode}")
        time.sleep(0.5)
    else:
        stop(process, grace=0)
        raise TimeoutError(f"AfterFX job timed out after {args.timeout}s")

    result = None
    for _ in range(60):
        try:
            result = read_json(result_path)
            break
        except (OSError, json.JSONDecodeError):
            time.sleep(0.2)
    stop(process)
    if not result or not result.get("ok"):
        raise RuntimeError(f"AfterFX job failed: {result}")

    input_after = sha256(input_project)
    if input_after != input_before:
        raise RuntimeError("Worker modified its input AEP")
    protected_after = sha256(protected) if protected else None
    if protected_after != protected_before:
        raise RuntimeError("Worker modified the protected source AEP")
    locks_after = dependency_states(plan_path)
    if locks_after != locks_before:
        raise RuntimeError("A locked external dependency changed during the worker job")
    output_state = None
    if output is not None:
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("Expected output AEP was not created")
        output_state = {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size}

    # The JSX worker cannot prove hashes outside AE. Normalize its persisted
    # apply/readback artifact only after this runner verifies the staged input,
    # protected original, dependency locks, and optional output AEP.
    if result.get("artifactType") == "apply-readback":
        if protected is None:
            raise RuntimeError("Apply/readback jobs require protectedSourcePath so original immutability can be proven")
        result["inputProjectUnchanged"] = True
        result["protectedSourceUnchanged"] = True
        result["originalSourceUnchanged"] = True
        result["inputProjectSha256"] = input_after
        result["protectedSourceSha256"] = protected_after
        result["outputProject"] = output_state
        write_json(result_path, result)

    worker_summary = {
        "ok": result.get("ok"),
        "mode": result.get("mode"),
        "comp": result.get("comp"),
        "tileLayerCount": len(result.get("tileLayers", [])),
        "moverLayerCount": len(result.get("moverLayers", [])),
        "handLayerCount": len(result.get("handLayers", [])),
        "pairCandidateCount": len(result.get("pairCandidates", [])),
        "propertyUpdateCount": result.get("propertyUpdateCount"),
        "newRouteCriticalMissingCount": len(result.get("newRouteCriticalMissing", result.get("missingFootage", []))),
        "newRouteExpressionErrorCount": len(result.get("newRouteExpressionErrors", result.get("expressionErrors", []))),
        "watermarkEnabled": result.get("watermarkEnabled"),
    }
    summary = {
        "status": "complete",
        "worker": str(worker),
        "job": str(job_path),
        "result": str(result_path),
        "inputProject": str(input_project),
        "inputProjectUnchanged": True,
        "inputProjectSha256": input_after,
        "protectedSource": str(protected) if protected else None,
        "protectedSourceUnchanged": True if protected else None,
        "protectedSourceSha256": protected_after,
        "dependencyLocks": locks_after,
        "outputProject": output_state,
        "workerResultSummary": worker_summary,
    }
    if args.include_result:
        summary["workerResult"] = result
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
