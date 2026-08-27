#!/usr/bin/env python3
from __future__ import annotations

import argparse
import compileall
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ae_stack_runtime.common import read_json
from ae_stack_runtime.contracts import (
    validate_assignment,
    validate_board_inventory,
    validate_capacity,
    validate_depth_evidence,
    validate_event_model,
    validate_property_plan,
    validate_reference_roi,
    validate_simulation,
    validate_source_route,
    validate_visible_layout,
)
from ae_stack_runtime.run_setup import init_run


FIXTURE = ROOT / "examples" / "hourglass-40-visible-57-physical"


def result(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, **details}


def check_json_parse() -> dict[str, Any]:
    files = sorted(ROOT.rglob("*.json"))
    for path in files:
        json.loads(path.read_text(encoding="utf-8-sig"))
    return result("all-json-parses", True, fileCount=len(files))


def check_runtime_contracts() -> dict[str, Any]:
    validators = {
        "source-route.json": validate_source_route,
        "board-inventory.json": validate_board_inventory,
        "source-event-model.json": validate_event_model,
        "reference-roi.json": validate_reference_roi,
        "visible-layout.json": validate_visible_layout,
        "observed-depth.json": validate_depth_evidence,
        "capacity-plan.json": validate_capacity,
        "assignment.json": validate_assignment,
        "simulation-report.json": validate_simulation,
        "property-plan.json": validate_property_plan,
    }
    for name, validator in validators.items():
        validator(read_json(FIXTURE / name))
    return result("golden-fixture-runtime-contracts", True, artifactCount=len(validators))


def check_schemas() -> dict[str, Any]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return result("json-schema-validation", True, skipped=True, reason="jsonschema is not installed")
    pairs = {
        "source-event-model.schema.json": "source-event-model.json",
        "visible-layout.schema.json": "visible-layout.json",
        "capacity-plan.schema.json": "capacity-plan.json",
        "assignment.schema.json": "assignment.json",
        "simulation-report.schema.json": "simulation-report.json",
        "property-plan.schema.json": "property-plan.json",
    }
    for schema_name, artifact_name in pairs.items():
        schema = read_json(ROOT / "schemas" / schema_name)
        artifact = read_json(FIXTURE / artifact_name)
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(artifact), key=lambda error: list(error.path))
        if errors:
            first = errors[0]
            raise ValueError(f"{schema_name} rejected {artifact_name} at {list(first.path)}: {first.message}")

    with tempfile.TemporaryDirectory(prefix="ae-stack-v2-receipt-schema-") as temp:
        temp_root = Path(temp)
        source = temp_root / "source.aep"
        reference = temp_root / "reference.png"
        source.write_bytes(b"schema-receipt-fixture")
        Image.new("RGB", (32, 32), (1, 2, 3)).save(reference)
        initialized = init_run(source, reference, temp_root / "library", "schema-receipt")
        receipt_path = Path(initialized["state"]["activePasses"]["INITIALIZED"]["receiptPath"])
        schema = read_json(ROOT / "schemas" / "state-receipt.schema.json")
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(read_json(receipt_path)))
        if errors:
            raise ValueError(f"state-receipt.schema.json rejected initial receipt: {errors[0].message}")
    return result("json-schema-validation", True, artifactCount=len(pairs) + 1)


def check_python_compile() -> dict[str, Any]:
    passed = compileall.compile_dir(str(ROOT / "scripts"), quiet=1) and compileall.compile_dir(str(ROOT / "tests"), quiet=1)
    if not passed:
        raise RuntimeError("Python compileall failed")
    return result("python-compileall", True)


def check_jsx() -> dict[str, Any]:
    paths = sorted((ROOT / "scripts" / "ae").glob("*.jsx"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if '$.getenv("AE_STACK_V2_JOB")' not in text:
            raise ValueError(f"{path.name} does not read AE_STACK_V2_JOB")
        if "AE_STACK_JOB" in text.replace("AE_STACK_V2_JOB", ""):
            raise ValueError(f"{path.name} still contains the legacy AE_STACK_JOB environment variable")
    node = shutil.which("node")
    if node is None:
        return result("jsx-static-and-syntax-check", True, fileCount=len(paths), syntaxSkipped=True)
    with tempfile.TemporaryDirectory(prefix="ae-stack-v2-jsx-") as temp:
        temp_root = Path(temp)
        for path in paths:
            copy = temp_root / f"{path.stem}.js"
            copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            subprocess.run([node, "--check", str(copy)], check=True, capture_output=True, text=True)
    return result("jsx-static-and-syntax-check", True, fileCount=len(paths), syntaxSkipped=False)


def check_tests(verbosity: int) -> dict[str, Any]:
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py")
    count = suite.countTestCases()
    run = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    if not run.wasSuccessful():
        raise RuntimeError(f"Regression suite failed: failures={len(run.failures)}, errors={len(run.errors)}")
    return result("regression-suite", True, testCount=count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the packaged AE Reference Stack Layout Render v2 Skill")
    parser.add_argument("--test-verbosity", type=int, default=1)
    args = parser.parse_args()
    checks = []
    for check in (
        check_json_parse,
        check_runtime_contracts,
        check_schemas,
        check_python_compile,
        check_jsx,
    ):
        checks.append(check())
    checks.append(check_tests(args.test_verbosity))
    fixture = read_json(FIXTURE / "fixture-summary.json")
    report = {
        "status": "passed",
        "package": "ae-reference-stack-layout-render-v2",
        "checks": checks,
        "goldenFixture": {
            "visibleAnchorCount": fixture["visibleAnchorCount"],
            "physicalSlotCount": fixture["physicalSlotCount"],
            "hiddenSlotCount": fixture["hiddenSlotCount"],
            "rowCounts": fixture["rowCounts"],
            "expected": fixture["expected"],
        },
        "hostIntegrationBoundary": "Actual After Effects open/apply/save/fresh-reopen/render was not executed by this offline validator.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
