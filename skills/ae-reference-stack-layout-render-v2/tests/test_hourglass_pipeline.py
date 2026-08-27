from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ae_stack_runtime.common import read_json, write_json
from ae_stack_runtime.contracts import (
    validate_assignment,
    validate_event_model,
    validate_property_plan,
    validate_simulation,
)
from ae_stack_runtime.property_plan import _coalesce_updates
from ae_stack_runtime.simulation import simulate_from_files
from fixture_factory import create_hourglass_fixture


class HourglassPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="ae-stack-v2-hourglass-"))
        create_hourglass_fixture(cls.temp_dir, build_property_plan=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_40_visible_57_physical_pipeline(self) -> None:
        capacity = read_json(self.temp_dir / "capacity-plan.json")
        assignment = read_json(self.temp_dir / "assignment.json")
        simulation = read_json(self.temp_dir / "simulation-report.json")
        plan = read_json(self.temp_dir / "property-plan.json")

        self.assertEqual(capacity["visibleAnchorCount"], 40)
        self.assertEqual(capacity["physicalSlotCount"], 57)
        self.assertEqual(capacity["hiddenSlotCount"], 17)
        self.assertEqual(capacity["provenanceCounts"]["observed-top-surface"], 40)
        self.assertEqual(capacity["provenanceCounts"]["synthesized-for-surplus"], 17)
        self.assertEqual(assignment["status"], "solved")
        self.assertEqual(assignment["assignmentCount"], 57)
        self.assertTrue(all(set(row) == {"tileId", "slotId"} for row in assignment["assignments"]))
        self.assertEqual(simulation["status"], "passed")
        self.assertTrue(simulation["writeAuthorized"])
        self.assertEqual(simulation["blockedClickCount"], 0)
        self.assertEqual(simulation["occlusionOrderViolationCount"], 0)
        self.assertEqual(plan["propertyUpdateCount"], 57)
        self.assertTrue((self.temp_dir / "visible-layout-overlay.png").is_file())
        self.assertTrue((self.temp_dir / "capacity-overlay.png").is_file())
        self.assertTrue((self.temp_dir / "assignment-overlay.png").is_file())
        validate_assignment(assignment)
        validate_simulation(simulation)
        validate_property_plan(plan)

    def test_assignment_cannot_smuggle_source_facts(self) -> None:
        assignment = read_json(self.temp_dir / "assignment.json")
        assignment["assignments"][0]["zOrder"] = 0
        with self.assertRaisesRegex(ValueError, "only tileId and slotId"):
            validate_assignment(assignment)

    def test_event_fact_hash_detects_mutation(self) -> None:
        event = read_json(self.temp_dir / "source-event-model.json")
        event["tiles"][0]["activeEnd"] += 1.0
        with self.assertRaisesRegex(ValueError, "sourceFactsSha256"):
            validate_event_model(event)

    def test_simulation_rejects_missing_assignment_lineage(self) -> None:
        assignment_path = self.temp_dir / "assignment-without-lineage.json"
        assignment = read_json(self.temp_dir / "assignment.json")
        assignment.pop("sourceFactsSha256")
        assignment.pop("capacityPlanSha256")
        write_json(assignment_path, assignment)
        result = simulate_from_files(
            self.temp_dir / "source-event-model.json",
            self.temp_dir / "capacity-plan.json",
            assignment_path,
        )
        self.assertEqual(result["status"], "failed")
        self.assertGreaterEqual(result["identityErrorCount"], 2)
        self.assertFalse(result["writeAuthorized"])

    def test_property_updates_merge_distinct_keys_and_reject_conflicts(self) -> None:
        base = {
            "compId": 101,
            "layerIndex": 90,
            "layerName": "hand",
            "sourceId": 9090,
            "propertyMatchName": "ADBE Position",
            "expectedNumKeys": 2,
        }
        merged = _coalesce_updates([
            {**base, "keys": [{"keyNumber": 1, "expectedOld": [0, 0], "newValue": [10, 10], "tolerance": 0.5}]},
            {**base, "keys": [{"keyNumber": 2, "expectedOld": [1, 1], "newValue": [20, 20], "tolerance": 0.5}]},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual([row["keyNumber"] for row in merged[0]["keys"]], [1, 2])
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate key write"):
            _coalesce_updates([
                {**base, "keys": [{"keyNumber": 1, "expectedOld": [0, 0], "newValue": [10, 10], "tolerance": 0.5}]},
                {**base, "keys": [{"keyNumber": 1, "expectedOld": [0, 0], "newValue": [99, 99], "tolerance": 0.5}]},
            ])


if __name__ == "__main__":
    unittest.main()
