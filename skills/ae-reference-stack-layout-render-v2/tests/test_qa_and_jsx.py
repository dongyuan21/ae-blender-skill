from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ae_stack_runtime.qa import route_qa


class QaAndJsxTests(unittest.TestCase):
    def test_qa_routes_to_earliest_authoritative_node(self) -> None:
        routed = route_qa({
            "issues": [
                {"code": "CLICK_BLOCKED", "detail": "tile 17"},
                {"code": "REFERENCE_SILHOUETTE_MISMATCH", "detail": "row 4"},
            ]
        })
        self.assertEqual(routed["status"], "ROUTED")
        self.assertEqual(routed["retryFrom"], "VISIBLE_LAYOUT_LOCKED")

    def test_explicit_empty_route_scope_does_not_expand_to_whole_project(self) -> None:
        for path in sorted((ROOT / "scripts" / "ae").glob("*.jsx")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("values.length===0)return true", text, path.name)
            self.assertIn("if(!(values instanceof Array))return false", text, path.name)
        inspect = (ROOT / "scripts" / "ae" / "inspect_stack_v2.jsx").read_text(encoding="utf-8")
        self.assertIn("var scope=null", inspect)
        self.assertIn("job.routeCompIds instanceof Array", inspect)

    def test_jsx_workers_share_one_job_env_and_canonical_baseline(self) -> None:
        for path in sorted((ROOT / "scripts" / "ae").glob("*.jsx")):
            text = path.read_text(encoding="utf-8")
            self.assertIn('$.getenv("AE_STACK_V2_JOB")', text, path.name)
            self.assertNotIn("AE_STACK_JOB", text.replace("AE_STACK_V2_JOB", ""), path.name)
        for name in ("apply_property_plan_v2.jsx", "verify_property_plan_v2.jsx"):
            text = (ROOT / "scripts" / "ae" / name).read_text(encoding="utf-8")
            self.assertIn("baseline.acceptedMissingKeys", text)
            self.assertIn('artifactType:"apply-readback"', text)
            self.assertIn("referenceSourceAepUsed:false", text)
            self.assertIn("referenceSourceGeometryUsed:false", text)


if __name__ == "__main__":
    unittest.main()
