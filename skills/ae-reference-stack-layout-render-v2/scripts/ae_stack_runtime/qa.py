from __future__ import annotations

from typing import Any

from .common import SCHEMA_VERSION, now_iso


ISSUE_RETRY_NODE: dict[str, str] = {
    "CAPABILITY_MISSING": "CAPABILITY_PREFLIGHT_PASSED",
    "WRONG_FINAL_OR_BOARD_COMP": "SOURCE_ROUTE_LOCKED",
    "ROUTE_DEPENDENCY_MISSING": "SOURCE_ROUTE_LOCKED",
    "BOARD_TILE_MISSING_OR_MISCLASSIFIED": "BOARD_INVENTORY_LOCKED",
    "EVENT_PAIRING_AMBIGUOUS": "EVENT_MODEL_LOCKED",
    "MOVER_CONTINUITY_ERROR": "EVENT_MODEL_LOCKED",
    "HAND_ALIGNMENT_ERROR": "EVENT_MODEL_LOCKED",
    "REFERENCE_ROI_INCLUDES_UI_OR_HAND": "REFERENCE_ROI_LOCKED",
    "REFERENCE_SILHOUETTE_MISMATCH": "VISIBLE_LAYOUT_LOCKED",
    "REFERENCE_HOLE_MISMATCH": "VISIBLE_LAYOUT_LOCKED",
    "ROW_OR_BRANCH_GRAMMAR_MISMATCH": "VISIBLE_LAYOUT_LOCKED",
    "DEPTH_OCCLUSION_MISMATCH": "DEPTH_EVIDENCE_LOCKED",
    "UNSUPPORTED_VISIBLE_DEPTH_CLAIM": "DEPTH_EVIDENCE_LOCKED",
    "HIDDEN_CAPACITY_CONCENTRATION": "CAPACITY_RECONCILED",
    "PHYSICAL_SLOT_COUNT_MISMATCH": "CAPACITY_RECONCILED",
    "CLICK_BLOCKED": "ASSIGNMENT_SOLVED",
    "ASSIGNMENT_IDENTITY_MISMATCH": "ASSIGNMENT_SOLVED",
    "PROPERTY_PLAN_STALE": "PROPERTY_PLAN_FROZEN",
    "PROPERTY_OLD_VALUE_MISMATCH": "PROPERTY_PLAN_FROZEN",
    "PROPERTY_READBACK_MISMATCH": "PROPERTY_PLAN_FROZEN",
    "NEW_ROUTE_MISSING_FOOTAGE": "SOURCE_ROUTE_LOCKED",
    "NEW_ROUTE_EXPRESSION_ERROR": "PROPERTY_PLAN_FROZEN",
    "WATERMARK_ENABLED": "PROPERTY_PLAN_FROZEN",
    "PREVIEW_Z_POP_OR_JUMP": "EVENT_MODEL_LOCKED",
    "PREVIEW_VISUAL_MISMATCH": "VISIBLE_LAYOUT_LOCKED",
    "VIDEO_TECHNICAL_FAILURE": "APPLY_READBACK_PASSED",
    "FULL_VIDEO_BEHAVIOR_FAILURE": "EVENT_MODEL_LOCKED",
}

NODE_ORDER = [
    "CAPABILITY_PREFLIGHT_PASSED",
    "SOURCE_ROUTE_LOCKED",
    "BOARD_INVENTORY_LOCKED",
    "EVENT_MODEL_LOCKED",
    "REFERENCE_ROI_LOCKED",
    "VISIBLE_LAYOUT_LOCKED",
    "DEPTH_EVIDENCE_LOCKED",
    "CAPACITY_RECONCILED",
    "ASSIGNMENT_SOLVED",
    "SIMULATION_PASSED",
    "PROPERTY_PLAN_FROZEN",
    "APPLY_READBACK_PASSED",
    "PREVIEW_ACCEPTED",
    "FULL_RENDER_PASSED",
]


def route_qa(qa: dict[str, Any]) -> dict[str, Any]:
    issues = qa.get("issues")
    if not isinstance(issues, list):
        raise ValueError("qa.issues must be an array")
    routes: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for index, row in enumerate(issues):
        if not isinstance(row, dict):
            unmapped.append({"index": index, "issue": row, "reason": "issue must be an object"})
            continue
        code = str(row.get("code", ""))
        retry = ISSUE_RETRY_NODE.get(code)
        if retry is None:
            unmapped.append({"index": index, "issue": row, "reason": "unmapped issue code"})
        else:
            routes.append({"code": code, "retryFrom": retry, "issue": row})
    if routes:
        earliest = min(routes, key=lambda row: NODE_ORDER.index(row["retryFrom"]))["retryFrom"]
    else:
        earliest = None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "qa-route",
        "createdAt": now_iso(),
        "status": "ROUTED" if earliest else ("UNMAPPED" if unmapped else "NO_ISSUES"),
        "retryFrom": earliest,
        "routes": routes,
        "unmappedIssues": unmapped,
        "instruction": (
            "Invalidate retryFrom and every descendant; do not edit the AEP inside QA."
            if earliest
            else "No retry node was selected."
        ),
    }
