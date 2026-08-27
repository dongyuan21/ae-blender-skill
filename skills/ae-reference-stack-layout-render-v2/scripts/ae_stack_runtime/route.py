from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import SCHEMA_VERSION, now_iso, path_state, read_json, require_dict, require_list, require_str, write_json
from .contracts import validate_source_route


def _issue_key(row: Any) -> str:
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        raise ValueError("QA baseline rows must be strings or objects")
    if row.get("key"):
        return str(row["key"])
    if row.get("itemId") is not None:
        return f"{row.get('itemId')}|{str(row.get('path', '')).replace('\\\\', '/').lower()}"
    if row.get("compId") is not None and row.get("layerIndex") is not None:
        return f"{row.get('compId')}/{row.get('layerIndex')}|{row.get('layerName', '')}|{row.get('sourceName', '')}"
    if row.get("path") is not None:
        return f"{row.get('path')}|{row.get('error', '')}"
    raise ValueError(f"Cannot derive a QA baseline key from: {row}")


def lock_source_route_data(draft: dict[str, Any], draft_path: Path | None = None) -> dict[str, Any]:
    final_comp = require_dict(draft.get("finalComp"), "finalComp")
    board_comp = require_dict(draft.get("boardComp"), "boardComp")
    nesting = require_list(draft.get("nestingPath"), "nestingPath")
    scope = require_dict(draft.get("routeScope", {}), "routeScope")
    route_comp_ids = scope.get("compIds")
    if route_comp_ids is None:
        route_comp_ids = [int(require_dict(row, "nestingPath[]")["compId"]) for row in nesting]
    baseline_raw = require_dict(draft.get("qaBaseline", {}), "qaBaseline")
    baseline = {
        "acceptedMissingKeys": [_issue_key(row) for row in baseline_raw.get("acceptedMissingKeys", baseline_raw.get("acceptedMissing", []))],
        "acceptedExpressionErrorKeys": [_issue_key(row) for row in baseline_raw.get("acceptedExpressionErrorKeys", baseline_raw.get("acceptedExpressionErrors", []))],
        "acceptedEnabledWatermarkKeys": [_issue_key(row) for row in baseline_raw.get("acceptedEnabledWatermarkKeys", baseline_raw.get("acceptedEnabledWatermarks", []))],
    }
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "source-route",
        "createdAt": now_iso(),
        "finalComp": final_comp,
        "boardComp": board_comp,
        "sameCompJustification": draft.get("sameCompJustification"),
        "nestingPath": nesting,
        "routeScope": {
            "compIds": [int(value) for value in route_comp_ids],
            "routeCriticalFootageItemIds": [int(value) for value in scope.get("routeCriticalFootageItemIds", [])],
        },
        "qaBaseline": baseline,
        "renderSettings": require_dict(draft.get("renderSettings", {}), "renderSettings"),
        "review": require_dict(draft.get("review"), "review"),
        "safety": {
            "editBoardCompOnly": True,
            "renderFinalComp": True,
            "referenceSourceAepUsed": False,
            "referenceSourceGeometryUsed": False,
        },
    }
    if draft_path is not None:
        result["draft"] = path_state(draft_path)
    validate_source_route(result)
    return result


def lock_source_route(draft_path: Path, output_path: Path) -> dict[str, Any]:
    result = lock_source_route_data(read_json(draft_path), draft_path)
    write_json(output_path, result)
    return result
