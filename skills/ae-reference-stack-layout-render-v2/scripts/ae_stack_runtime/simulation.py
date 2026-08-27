from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    SCHEMA_VERSION,
    now_iso,
    overlap_metrics,
    read_json,
    rect_from_center,
    sha256_file,
    vector,
)
from .contracts import validate_capacity, validate_event_model


_ALLOWED_ASSIGNMENT_FIELDS = {"tileId", "slotId"}


def _assignment_map(assignment: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    result: dict[str, str] = {}
    errors: list[dict[str, Any]] = []
    occupied: dict[str, str] = {}
    rows = assignment.get("assignments", [])
    if not isinstance(rows, list):
        return {}, [{"error": "assignment.assignments must be an array"}]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append({"assignmentIndex": index, "error": "assignment row must be an object"})
            continue
        unexpected = sorted(set(row) - _ALLOWED_ASSIGNMENT_FIELDS)
        if unexpected:
            errors.append({
                "assignmentIndex": index,
                "error": "assignment row contains forbidden source facts or derived geometry",
                "fields": unexpected,
            })
        tile_id = str(row.get("tileId", ""))
        slot_id = str(row.get("slotId", ""))
        if not tile_id or not slot_id:
            errors.append({"assignmentIndex": index, "error": "tileId and slotId are required"})
            continue
        if tile_id in result:
            errors.append({"tileId": tile_id, "error": "tile assigned more than once"})
        if slot_id in occupied:
            errors.append({
                "slotId": slot_id,
                "error": "slot assigned more than once",
                "tiles": [occupied[slot_id], tile_id],
            })
        result[tile_id] = slot_id
        occupied[slot_id] = tile_id
    return result, errors


def simulate_mapping(
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    assignment: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one tile-to-slot mapping.

    All gameplay facts are read only from ``source-event-model``. Assignment
    rows are intentionally too weak to override layer order, active intervals,
    click times, or geometry.
    """
    validate_event_model(event_model)
    validate_capacity(capacity)
    tiles = {str(row["tileId"]): row for row in event_model["tiles"]}
    slots = {str(row["slotId"]): row for row in capacity["slots"]}
    mapping, identity_errors = _assignment_map(assignment)

    if capacity.get("sourceFactsSha256") != event_model.get("sourceFactsSha256"):
        identity_errors.append({
            "error": "capacity plan was built from a different source-event-model",
            "eventSourceFactsSha256": event_model.get("sourceFactsSha256"),
            "capacitySourceFactsSha256": capacity.get("sourceFactsSha256"),
        })

    missing_tiles = sorted(set(tiles) - set(mapping))
    extra_tiles = sorted(set(mapping) - set(tiles))
    missing_slots = sorted(set(slots) - set(mapping.values()))
    extra_slots = sorted(set(mapping.values()) - set(slots))
    for tile_id in missing_tiles:
        identity_errors.append({"tileId": tile_id, "error": "source tile is not assigned"})
    for tile_id in extra_tiles:
        identity_errors.append({"tileId": tile_id, "error": "assignment references unknown source tile"})
    for slot_id in missing_slots:
        identity_errors.append({"slotId": slot_id, "error": "physical slot is not occupied"})
    for slot_id in extra_slots:
        identity_errors.append({"slotId": slot_id, "error": "assignment references unknown physical slot"})

    rectangles: dict[str, tuple[float, float, float, float]] = {
        slot_id: rect_from_center(
            vector(slot["center"], f"{slot_id}.center")[:2],
            vector(slot["size"], f"{slot_id}.size")[:2],
        )
        for slot_id, slot in slots.items()
    }

    overlap_threshold = float(capacity.get("overlapThreshold", 0.001))
    overlap_pairs: set[frozenset[str]] = set()
    overlap_edges: list[dict[str, Any]] = []
    slot_ids = list(slots)
    for first_index, first_id in enumerate(slot_ids):
        for second_id in slot_ids[first_index + 1 :]:
            area, ratio = overlap_metrics(rectangles[first_id], rectangles[second_id])
            if area > 0 and ratio >= overlap_threshold:
                overlap_pairs.add(frozenset((first_id, second_id)))
                overlap_edges.append({
                    "firstSlotId": first_id,
                    "secondSlotId": second_id,
                    "overlapArea": round(area, 4),
                    "overlapRatio": round(ratio, 6),
                })

    bounds_errors: list[dict[str, Any]] = []
    safe = capacity.get("safeRegion")
    if isinstance(safe, dict):
        left = float(safe["left"])
        top = float(safe["top"])
        right = float(safe["right"])
        bottom = float(safe["bottom"])
        for slot_id, rect in rectangles.items():
            if rect[0] < left or rect[1] < top or rect[2] > right or rect[3] > bottom:
                bounds_errors.append({
                    "slotId": slot_id,
                    "rectangle": [round(value, 4) for value in rect],
                    "safeRegion": [left, top, right, bottom],
                })

    blocked_clicks: list[dict[str, Any]] = []
    slot_to_tile = {slot_id: tile_id for tile_id, slot_id in mapping.items()}
    if not identity_errors:
        selected_tiles = sorted(
            (tile for tile in tiles.values() if tile.get("clickTime") is not None),
            key=lambda row: int(row["clickOrdinal"]),
        )
        for selected in selected_tiles:
            selected_id = str(selected["tileId"])
            click_time = float(selected["clickTime"])
            if not float(selected["activeStart"]) <= click_time < float(selected["activeEnd"]):
                blocked_clicks.append({
                    "tileId": selected_id,
                    "ordinal": selected["clickOrdinal"],
                    "time": click_time,
                    "error": "selected tile is not active at click time",
                    "blockers": [],
                })
                continue
            selected_slot = mapping[selected_id]
            blockers: list[dict[str, Any]] = []
            for other_id, other in tiles.items():
                if other_id == selected_id:
                    continue
                if not float(other["activeStart"]) <= click_time < float(other["activeEnd"]):
                    continue
                other_slot = mapping[other_id]
                if frozenset((selected_slot, other_slot)) not in overlap_pairs:
                    continue
                # AE convention: smaller layer index renders in front.
                if int(other["renderOrder"]) < int(selected["renderOrder"]):
                    blockers.append({
                        "tileId": other_id,
                        "slotId": other_slot,
                        "renderOrder": int(other["renderOrder"]),
                        "activeEnd": float(other["activeEnd"]),
                        "faceId": other.get("faceId"),
                    })
            if blockers:
                blockers.sort(key=lambda row: row["renderOrder"])
                blocked_clicks.append({
                    "tileId": selected_id,
                    "slotId": selected_slot,
                    "ordinal": int(selected["clickOrdinal"]),
                    "time": click_time,
                    "selectedRenderOrder": int(selected["renderOrder"]),
                    "blockers": blockers,
                })

    occlusion_violations: list[dict[str, Any]] = []
    if not identity_errors:
        for edge in capacity.get("frontBackEdges", []) or []:
            front_slot = str(edge["frontSlotId"])
            back_slot = str(edge["backSlotId"])
            front_tile_id = slot_to_tile[front_slot]
            back_tile_id = slot_to_tile[back_slot]
            front_order = int(tiles[front_tile_id]["renderOrder"])
            back_order = int(tiles[back_tile_id]["renderOrder"])
            if front_order >= back_order:
                occlusion_violations.append({
                    "kind": edge.get("kind"),
                    "evidenceClass": edge.get("evidenceClass"),
                    "frontSlotId": front_slot,
                    "backSlotId": back_slot,
                    "frontTileId": front_tile_id,
                    "backTileId": back_tile_id,
                    "frontRenderOrder": front_order,
                    "backRenderOrder": back_order,
                    "error": "front slot is not rendered in front by the locked AE layer order",
                })

    match_errors: list[dict[str, Any]] = []
    group_size = event_model.get("matchGroupSize")
    if group_size is not None:
        expected_size = int(group_size)
        groups: dict[str, list[dict[str, Any]]] = {}
        for tile in tiles.values():
            group = tile.get("matchGroupId")
            if group is not None:
                groups.setdefault(str(group), []).append(tile)
        for group, members in groups.items():
            if len(members) != expected_size:
                match_errors.append({
                    "matchGroupId": group,
                    "expectedSize": expected_size,
                    "actualSize": len(members),
                })

    return {
        "identityErrors": identity_errors,
        "boundsErrors": bounds_errors,
        "matchErrors": match_errors,
        "blockedClicks": blocked_clicks,
        "occlusionOrderViolations": occlusion_violations,
        "overlapEdges": overlap_edges,
        "identityErrorCount": len(identity_errors),
        "boundsErrorCount": len(bounds_errors),
        "matchErrorCount": len(match_errors),
        "blockedClickCount": len(blocked_clicks),
        "blockingOrderViolationCount": sum(len(row.get("blockers", [])) for row in blocked_clicks),
        "occlusionOrderViolationCount": len(occlusion_violations),
        "overlapEdgeCount": len(overlap_edges),
        "accessibleClickCount": sum(tile.get("clickTime") is not None for tile in tiles.values()) - len(blocked_clicks),
    }


def simulate(
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    assignment: dict[str, Any],
    *,
    event_model_path: Path | None = None,
    capacity_path: Path | None = None,
    assignment_path: Path | None = None,
) -> dict[str, Any]:
    diagnostics = simulate_mapping(event_model, capacity, assignment)
    if assignment.get("sourceFactsSha256") != event_model.get("sourceFactsSha256"):
        diagnostics["identityErrors"].append({"error": "assignment.sourceFactsSha256 is missing or does not match event model"})
        diagnostics["identityErrorCount"] += 1
    expected_capacity_hash = sha256_file(capacity_path) if capacity_path is not None else None
    if expected_capacity_hash is not None and assignment.get("capacityPlanSha256") != expected_capacity_hash:
        diagnostics["identityErrors"].append({"error": "assignment.capacityPlanSha256 is missing or does not match capacity artifact bytes"})
        diagnostics["identityErrorCount"] += 1
    errors_exist = any(
        diagnostics[key] > 0
        for key in (
            "identityErrorCount",
            "boundsErrorCount",
            "matchErrorCount",
            "blockedClickCount",
            "occlusionOrderViolationCount",
        )
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "simulation-report",
        "createdAt": now_iso(),
        "status": "failed" if errors_exist else "passed",
        "writeAuthorized": not errors_exist,
        "sourceFactsSha256": event_model["sourceFactsSha256"],
        "capacityPlanSha256": sha256_file(capacity_path) if capacity_path else "IN_MEMORY",
        "assignmentSha256": sha256_file(assignment_path) if assignment_path else "IN_MEMORY",
        "inputs": {
            "eventModel": str(event_model_path.resolve()) if event_model_path else None,
            "capacityPlan": str(capacity_path.resolve()) if capacity_path else None,
            "assignment": str(assignment_path.resolve()) if assignment_path else None,
        },
        **diagnostics,
        "sourceFactAuthority": {
            "renderOrder": "source-event-model.tiles[].renderOrder copied from AE layerIndex",
            "activeIntervals": "source-event-model.tiles[].activeStart/activeEnd copied from AE inPoint/outPoint",
            "clickSchedule": "source-event-model locked event facts",
            "geometry": "capacity-plan slots",
            "assignmentMayOverrideSourceFacts": False,
        },
    }


def simulate_from_files(
    event_model_path: Path,
    capacity_path: Path,
    assignment_path: Path,
) -> dict[str, Any]:
    return simulate(
        read_json(event_model_path),
        read_json(capacity_path),
        read_json(assignment_path),
        event_model_path=event_model_path,
        capacity_path=capacity_path,
        assignment_path=assignment_path,
    )
