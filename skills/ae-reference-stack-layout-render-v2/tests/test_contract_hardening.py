from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ae_stack_runtime.common import read_json
from ae_stack_runtime.contracts import (
    validate_apply_readback,
    validate_capacity,
    validate_property_plan,
)


FIXTURE = ROOT / "examples" / "hourglass-40-visible-57-physical"


class ContractHardeningTests(unittest.TestCase):
    def test_capacity_rejects_provenance_count_tamper(self) -> None:
        capacity = read_json(FIXTURE / "capacity-plan.json")
        capacity["provenanceCounts"]["synthesized-for-surplus"] -= 1
        with self.assertRaisesRegex(ValueError, "provenanceCounts"):
            validate_capacity(capacity)

    def test_capacity_rejects_front_back_cycle(self) -> None:
        capacity = read_json(FIXTURE / "capacity-plan.json")
        capacity["frontBackEdges"].append({
            "frontSlotId": "r05-c01::d2",
            "backSlotId": "r05-c01::d0",
            "kind": "reference-occlusion",
            "evidenceClass": "inferred",
        })
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_capacity(capacity)

    def test_property_plan_rejects_duplicate_property_target(self) -> None:
        plan = read_json(FIXTURE / "property-plan.json")
        plan["propertyUpdates"].append(copy.deepcopy(plan["propertyUpdates"][0]))
        plan["propertyUpdateCount"] += 1
        with self.assertRaisesRegex(ValueError, "property target identities"):
            validate_property_plan(plan)

    def test_apply_readback_requires_external_hash_proof(self) -> None:
        result = {
            "schemaVersion": 2,
            "artifactType": "apply-readback",
            "ok": True,
            "readbackErrors": [],
            "dependencyErrors": [],
            "disabledLayerErrors": [],
            "newRouteCriticalMissing": [],
            "newRouteExpressionErrors": [],
            "newEnabledWatermarks": [],
            "referenceSourceAepUsed": False,
            "referenceSourceGeometryUsed": False,
            "inputProjectUnchanged": True,
            "protectedSourceUnchanged": True,
            "originalSourceUnchanged": True,
        }
        with self.assertRaisesRegex(ValueError, "inputProjectSha256"):
            validate_apply_readback(result)


if __name__ == "__main__":
    unittest.main()
