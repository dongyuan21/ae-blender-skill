from __future__ import annotations

from collections import Counter, defaultdict, deque
import re
from typing import Any, Callable

from .common import (
    require_dict,
    require_int,
    require_list,
    require_number,
    require_str,
    unique,
    vector,
)
from .facts import event_facts_sha256


NODES: tuple[str, ...] = (
    "INITIALIZED",
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
)

PREREQUISITES: dict[str, tuple[str, ...]] = {
    "INITIALIZED": (),
    "CAPABILITY_PREFLIGHT_PASSED": ("INITIALIZED",),
    "SOURCE_ROUTE_LOCKED": ("CAPABILITY_PREFLIGHT_PASSED",),
    "BOARD_INVENTORY_LOCKED": ("SOURCE_ROUTE_LOCKED",),
    "EVENT_MODEL_LOCKED": ("BOARD_INVENTORY_LOCKED",),
    "REFERENCE_ROI_LOCKED": ("CAPABILITY_PREFLIGHT_PASSED",),
    "VISIBLE_LAYOUT_LOCKED": ("REFERENCE_ROI_LOCKED",),
    "DEPTH_EVIDENCE_LOCKED": ("VISIBLE_LAYOUT_LOCKED",),
    "CAPACITY_RECONCILED": ("EVENT_MODEL_LOCKED", "DEPTH_EVIDENCE_LOCKED"),
    "ASSIGNMENT_SOLVED": ("CAPACITY_RECONCILED",),
    "SIMULATION_PASSED": ("ASSIGNMENT_SOLVED",),
    "PROPERTY_PLAN_FROZEN": ("SIMULATION_PASSED",),
    "APPLY_READBACK_PASSED": ("PROPERTY_PLAN_FROZEN",),
    "PREVIEW_ACCEPTED": ("APPLY_READBACK_PASSED",),
    "FULL_RENDER_PASSED": ("PREVIEW_ACCEPTED",),
}

NODE_ARTIFACT_TYPE: dict[str, str] = {
    "INITIALIZED": "run-initialization",
    "CAPABILITY_PREFLIGHT_PASSED": "capability-preflight",
    "SOURCE_ROUTE_LOCKED": "source-route",
    "BOARD_INVENTORY_LOCKED": "board-inventory",
    "EVENT_MODEL_LOCKED": "source-event-model",
    "REFERENCE_ROI_LOCKED": "reference-roi",
    "VISIBLE_LAYOUT_LOCKED": "visible-layout",
    "DEPTH_EVIDENCE_LOCKED": "observed-depth",
    "CAPACITY_RECONCILED": "capacity-plan",
    "ASSIGNMENT_SOLVED": "assignment",
    "SIMULATION_PASSED": "simulation-report",
    "PROPERTY_PLAN_FROZEN": "property-plan",
    "APPLY_READBACK_PASSED": "apply-readback",
    "PREVIEW_ACCEPTED": "preview-qa",
    "FULL_RENDER_PASSED": "full-render-qa",
}

GATE_STATUSES = {"PASS", "REVISE", "BLOCKED"}
MATURITIES = {"DRAFT", "CANDIDATE", "FINAL"}
_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def _sha256(value: Any, label: str) -> str:
    result = require_str(value, label)
    if not _HASH_RE.match(result):
        raise ValueError(f"{label} must be a 64-character hexadecimal SHA-256")
    return result.upper()


def descendants(node: str) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for candidate, requirements in PREREQUISITES.items():
        for requirement in requirements:
            children[requirement].append(candidate)
    result: set[str] = set()
    queue: deque[str] = deque(children.get(node, []))
    while queue:
        candidate = queue.popleft()
        if candidate in result:
            continue
        result.add(candidate)
        queue.extend(children.get(candidate, []))
    return result


def eligible_nodes(active_passes: dict[str, Any]) -> list[str]:
    completed = set(active_passes)
    return [
        node
        for node in NODES
        if node != "INITIALIZED"
        and node not in completed
        and all(requirement in completed for requirement in PREREQUISITES[node])
    ]


def _base(value: dict[str, Any], expected_type: str) -> None:
    if require_int(value.get("schemaVersion"), "schemaVersion") != 2:
        raise ValueError("schemaVersion must equal 2")
    if require_str(value.get("artifactType"), "artifactType") != expected_type:
        raise ValueError(f"artifactType must equal {expected_type}")


def _review(value: dict[str, Any], label: str = "review") -> None:
    review = require_dict(value.get(label), label)
    if review.get("status") != "approved":
        raise ValueError(f"{label}.status must be approved")
    issues = require_list(review.get("issues", []), f"{label}.issues")
    if issues:
        raise ValueError(f"{label}.issues must be empty for a locked PASS artifact")


def _safe_region(value: dict[str, Any], coordinate: dict[str, Any]) -> None:
    width = require_number(coordinate.get("width"), "coordinateSystem.width")
    height = require_number(coordinate.get("height"), "coordinateSystem.height")
    if width <= 0 or height <= 0:
        raise ValueError("coordinateSystem dimensions must be positive")
    safe = require_dict(value.get("safeRegion"), "safeRegion")
    left = require_number(safe.get("left"), "safeRegion.left")
    top = require_number(safe.get("top"), "safeRegion.top")
    right = require_number(safe.get("right"), "safeRegion.right")
    bottom = require_number(safe.get("bottom"), "safeRegion.bottom")
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("safeRegion must be inside coordinateSystem")


def validate_capability(value: dict[str, Any]) -> None:
    _base(value, "capability-preflight")
    checks = require_list(value.get("checks"), "checks")
    if not checks:
        raise ValueError("checks must not be empty")
    failed = [
        row
        for row in checks
        if not isinstance(row, dict)
        or (row.get("required") is True and row.get("passed") is not True)
    ]
    if failed:
        raise ValueError(f"Required capability checks failed: {failed}")


def validate_source_route(value: dict[str, Any]) -> None:
    _base(value, "source-route")
    final_comp = require_dict(value.get("finalComp"), "finalComp")
    board_comp = require_dict(value.get("boardComp"), "boardComp")
    final_id = require_int(final_comp.get("id"), "finalComp.id")
    board_id = require_int(board_comp.get("id"), "boardComp.id")
    for label, comp in (("finalComp", final_comp), ("boardComp", board_comp)):
        require_str(comp.get("name"), f"{label}.name")
        require_number(comp.get("width"), f"{label}.width")
        require_number(comp.get("height"), f"{label}.height")
    if final_id == board_id and not str(value.get("sameCompJustification", "")).strip():
        raise ValueError("finalComp and boardComp may match only with sameCompJustification")
    route = require_list(value.get("nestingPath"), "nestingPath")
    route_ids = [
        require_int(require_dict(row, "nestingPath[]").get("compId"), "nestingPath[].compId")
        for row in route
    ]
    if not route_ids or route_ids[0] != final_id or route_ids[-1] != board_id:
        raise ValueError("nestingPath must start at finalComp and end at boardComp")
    unique([str(item) for item in route_ids], "nestingPath comp IDs")
    scope = require_dict(value.get("routeScope"), "routeScope")
    scope_ids = [require_int(row, "routeScope.compIds[]") for row in require_list(scope.get("compIds"), "routeScope.compIds")]
    if not set(route_ids).issubset(set(scope_ids)):
        raise ValueError("routeScope.compIds must include every nestingPath comp")
    for row in require_list(scope.get("routeCriticalFootageItemIds", []), "routeScope.routeCriticalFootageItemIds"):
        require_int(row, "routeScope.routeCriticalFootageItemIds[]")
    baseline = require_dict(value.get("qaBaseline", {}), "qaBaseline")
    for key in ("acceptedMissingKeys", "acceptedExpressionErrorKeys", "acceptedEnabledWatermarkKeys"):
        require_list(baseline.get(key, []), f"qaBaseline.{key}")
    _review(value)


def validate_board_inventory(value: dict[str, Any]) -> None:
    _base(value, "board-inventory")
    require_int(value.get("boardCompId"), "boardCompId")
    tiles = require_list(value.get("tiles"), "tiles")
    if not tiles:
        raise ValueError("tiles must not be empty")
    tile_ids: list[str] = []
    layer_keys: list[str] = []
    for index, row in enumerate(tiles):
        tile = require_dict(row, f"tiles[{index}]")
        tile_id = require_str(tile.get("tileId"), f"tiles[{index}].tileId")
        tile_ids.append(tile_id)
        comp_id = require_int(tile.get("compId"), f"tiles[{index}].compId")
        layer_index = require_int(tile.get("layerIndex"), f"tiles[{index}].layerIndex")
        layer_keys.append(f"{comp_id}/{layer_index}")
        require_str(tile.get("layerName"), f"tiles[{index}].layerName")
        render_order = require_int(tile.get("renderOrder"), f"tiles[{index}].renderOrder")
        if render_order != layer_index:
            raise ValueError(f"{tile_id}: renderOrder must be copied from AE layerIndex")
        active_start = require_number(tile.get("inPoint"), f"tiles[{index}].inPoint")
        active_end = require_number(tile.get("outPoint"), f"tiles[{index}].outPoint")
        if active_end <= active_start:
            raise ValueError(f"{tile_id}: outPoint must be greater than inPoint")
        vector(tile.get("originalPosition"), f"tiles[{index}].originalPosition")
        size = vector(tile.get("cardSize"), f"tiles[{index}].cardSize")
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError(f"{tile_id}: cardSize must be positive")
    unique(tile_ids, "tile IDs")
    unique(layer_keys, "board layer identities")
    if require_list(value.get("unclassifiedCandidates", []), "unclassifiedCandidates"):
        raise ValueError("unclassifiedCandidates must be empty")
    _review(value)


def validate_event_model(value: dict[str, Any]) -> None:
    _base(value, "source-event-model")
    tiles = require_list(value.get("tiles"), "tiles")
    if not tiles:
        raise ValueError("tiles must not be empty")
    tile_ids: list[str] = []
    ordinals: list[int] = []
    for index, row in enumerate(tiles):
        tile = require_dict(row, f"tiles[{index}]")
        tile_id = require_str(tile.get("tileId"), f"tiles[{index}].tileId")
        tile_ids.append(tile_id)
        render_order = require_int(tile.get("renderOrder"), f"tiles[{index}].renderOrder")
        layer_index = require_int(tile.get("layerIndex"), f"tiles[{index}].layerIndex")
        if render_order != layer_index:
            raise ValueError(f"{tile_id}: renderOrder must be derived from AE layerIndex")
        active_start = require_number(tile.get("activeStart"), f"tiles[{index}].activeStart")
        active_end = require_number(tile.get("activeEnd"), f"tiles[{index}].activeEnd")
        if active_end <= active_start:
            raise ValueError(f"{tile_id}: activeEnd must be greater than activeStart")
        click_time = tile.get("clickTime")
        ordinal = tile.get("clickOrdinal")
        if (click_time is None) != (ordinal is None):
            raise ValueError(f"{tile_id}: clickTime and clickOrdinal must both be present or absent")
        if click_time is not None:
            click = require_number(click_time, f"tiles[{index}].clickTime")
            ordinal_value = require_int(ordinal, f"tiles[{index}].clickOrdinal")
            ordinals.append(ordinal_value)
            if not active_start <= click < active_end:
                raise ValueError(f"{tile_id}: clickTime is outside the active interval")
        vector(tile.get("originalPosition"), f"tiles[{index}].originalPosition")
        size = vector(tile.get("cardSize"), f"tiles[{index}].cardSize")
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError(f"{tile_id}: cardSize must be positive")
    unique(tile_ids, "event-model tile IDs")
    unique([str(value) for value in ordinals], "click ordinals")
    if ordinals and sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        raise ValueError("click ordinals must be contiguous 1..N")
    if require_int(value.get("tileCount"), "tileCount") != len(tiles):
        raise ValueError("tileCount must equal len(tiles)")
    if require_int(value.get("eventTileCount"), "eventTileCount") != len(ordinals):
        raise ValueError("eventTileCount must equal the number of clicked tiles")
    if require_int(value.get("persistentTileCount"), "persistentTileCount") != len(tiles) - len(ordinals):
        raise ValueError("persistentTileCount mismatch")
    group_size = value.get("matchGroupSize")
    if group_size is not None and require_int(group_size, "matchGroupSize") < 1:
        raise ValueError("matchGroupSize must be positive")
    click_events = require_list(value.get("clickEvents", []), "clickEvents")
    if len(click_events) != len(ordinals):
        raise ValueError("clickEvents length must equal eventTileCount")
    clicked_by_id = {str(tile["tileId"]): tile for tile in tiles if tile.get("clickTime") is not None}
    seen_event_ids: list[str] = []
    for index, raw in enumerate(click_events):
        event = require_dict(raw, f"clickEvents[{index}]")
        tile_id = require_str(event.get("tileId"), f"clickEvents[{index}].tileId")
        seen_event_ids.append(tile_id)
        tile = clicked_by_id.get(tile_id)
        if tile is None:
            raise ValueError(f"clickEvents[{index}] refers to a non-clicked/unknown tile")
        if require_int(event.get("ordinal"), f"clickEvents[{index}].ordinal") != int(tile["clickOrdinal"]):
            raise ValueError(f"{tile_id}: clickEvents ordinal disagrees with tile facts")
        if abs(require_number(event.get("time"), f"clickEvents[{index}].time") - float(tile["clickTime"])) > 1e-9:
            raise ValueError(f"{tile_id}: clickEvents time disagrees with tile facts")
    unique(seen_event_ids, "clickEvents tile IDs")
    if set(seen_event_ids) != set(clicked_by_id):
        raise ValueError("clickEvents must cover every clicked tile exactly once")
    if value.get("factsLocked") is not True:
        raise ValueError("factsLocked must be true")
    declared_hash = _sha256(value.get("sourceFactsSha256"), "sourceFactsSha256")
    actual_hash = event_facts_sha256(tiles)
    if declared_hash != actual_hash:
        raise ValueError("sourceFactsSha256 does not match the canonical locked event facts")
    _review(value)


def validate_reference_roi(value: dict[str, Any]) -> None:
    _base(value, "reference-roi")
    image = require_dict(value.get("referenceImage"), "referenceImage")
    width = require_number(image.get("width"), "referenceImage.width")
    height = require_number(image.get("height"), "referenceImage.height")
    roi = require_dict(value.get("boardRoi"), "boardRoi")
    left = require_number(roi.get("left"), "boardRoi.left")
    top = require_number(roi.get("top"), "boardRoi.top")
    right = require_number(roi.get("right"), "boardRoi.right")
    bottom = require_number(roi.get("bottom"), "boardRoi.bottom")
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("boardRoi must be inside the reference image")
    for index, row in enumerate(require_list(value.get("excludedRegions", []), "excludedRegions")):
        region = require_dict(row, f"excludedRegions[{index}]")
        require_str(region.get("kind"), f"excludedRegions[{index}].kind")
        require_str(region.get("reason"), f"excludedRegions[{index}].reason")
    _review(value)


def validate_visible_layout(value: dict[str, Any]) -> None:
    _base(value, "visible-layout")
    coordinate = require_dict(value.get("coordinateSystem"), "coordinateSystem")
    if coordinate.get("space") != "board-comp":
        raise ValueError("coordinateSystem.space must be board-comp")
    _safe_region(value, coordinate)
    reference_coordinate = require_dict(value.get("referenceCoordinateSystem"), "referenceCoordinateSystem")
    if require_number(reference_coordinate.get("width"), "referenceCoordinateSystem.width") <= 0:
        raise ValueError("referenceCoordinateSystem.width must be positive")
    if require_number(reference_coordinate.get("height"), "referenceCoordinateSystem.height") <= 0:
        raise ValueError("referenceCoordinateSystem.height must be positive")
    mapping = require_dict(value.get("referenceToBoardTransform"), "referenceToBoardTransform")
    for key in ("scaleX", "scaleY", "offsetX", "offsetY"):
        require_number(mapping.get(key), f"referenceToBoardTransform.{key}")
    card = require_dict(value.get("cardBody"), "cardBody")
    width = require_number(card.get("width"), "cardBody.width")
    height = require_number(card.get("height"), "cardBody.height")
    if width <= 0 or height <= 0:
        raise ValueError("cardBody dimensions must be positive")
    anchors = require_list(value.get("anchors"), "anchors")
    if not anchors:
        raise ValueError("anchors must not be empty")
    anchor_ids: list[str] = []
    row_counts: dict[int, int] = defaultdict(int)
    safe = value["safeRegion"]
    for index, row_value in enumerate(anchors):
        anchor = require_dict(row_value, f"anchors[{index}]")
        anchor_id = require_str(anchor.get("anchorId"), f"anchors[{index}].anchorId")
        anchor_ids.append(anchor_id)
        row_index = require_int(anchor.get("row"), f"anchors[{index}].row")
        require_int(anchor.get("column"), f"anchors[{index}].column")
        row_counts[row_index] += 1
        center = vector(anchor.get("center"), f"anchors[{index}].center")
        size = vector(anchor.get("size", [width, height]), f"anchors[{index}].size")
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError(f"{anchor_id}: size must be positive")
        rect = [center[0] - size[0] / 2, center[1] - size[1] / 2, center[0] + size[0] / 2, center[1] + size[1] / 2]
        if rect[0] < float(safe["left"]) or rect[1] < float(safe["top"]) or rect[2] > float(safe["right"]) or rect[3] > float(safe["bottom"]):
            raise ValueError(f"{anchor_id}: card rectangle is outside safeRegion")
        if anchor.get("referenceCenter") is not None:
            vector(anchor.get("referenceCenter"), f"anchors[{index}].referenceCenter")
        if anchor.get("evidence") not in {"observed", "inferred"}:
            raise ValueError(f"{anchor_id}: visible anchor evidence must be observed or inferred")
    unique(anchor_ids, "visible anchor IDs")
    grammar = require_dict(value.get("grammar"), "grammar")
    declared = grammar.get("rowCounts")
    if declared is not None:
        declared_counts = [require_int(item, "grammar.rowCounts[]") for item in require_list(declared, "grammar.rowCounts")]
        actual_counts = [row_counts[row] for row in sorted(row_counts)]
        if declared_counts != actual_counts:
            raise ValueError(f"grammar.rowCounts {declared_counts} does not match anchors {actual_counts}")
    if require_int(value.get("topSurfaceAnchorCount"), "topSurfaceAnchorCount") != len(anchors):
        raise ValueError("topSurfaceAnchorCount must equal len(anchors)")
    _review(value, "proposerReview")
    _review(value, "reviewerReview")
    reviewer = require_dict(value.get("reviewerReview"), "reviewerReview")
    if reviewer.get("independentContext") is not True:
        raise ValueError("reviewerReview.independentContext must be true")


def validate_depth_evidence(value: dict[str, Any]) -> None:
    _base(value, "observed-depth")
    hints = require_list(value.get("anchorDepthHints"), "anchorDepthHints")
    anchor_ids: list[str] = []
    for index, row in enumerate(hints):
        hint = require_dict(row, f"anchorDepthHints[{index}]")
        anchor_id = require_str(hint.get("anchorId"), f"anchorDepthHints[{index}].anchorId")
        anchor_ids.append(anchor_id)
        minimum = require_int(hint.get("minDepth", 1), f"anchorDepthHints[{index}].minDepth")
        maximum = require_int(hint.get("maxDepth", minimum), f"anchorDepthHints[{index}].maxDepth")
        if not 1 <= minimum <= maximum:
            raise ValueError(f"{anchor_id}: invalid minDepth/maxDepth")
        if hint.get("evidenceClass") not in {"observed", "inferred", "unknown"}:
            raise ValueError(f"{anchor_id}: invalid evidenceClass")
        require_str(hint.get("rationale", "not-visible-in-single-frame"), f"{anchor_id}.rationale")
    unique(anchor_ids, "depth-hint anchor IDs")
    for index, row in enumerate(require_list(value.get("occlusionEdges", []), "occlusionEdges")):
        edge = require_dict(row, f"occlusionEdges[{index}]")
        front = require_str(edge.get("frontAnchorId"), f"occlusionEdges[{index}].frontAnchorId")
        back = require_str(edge.get("backAnchorId"), f"occlusionEdges[{index}].backAnchorId")
        if front == back:
            raise ValueError("occlusion edge endpoints must differ")
        if edge.get("evidenceClass") not in {"observed", "inferred"}:
            raise ValueError("occlusion edge evidenceClass must be observed or inferred")
    _review(value)


def validate_capacity(value: dict[str, Any]) -> None:
    _base(value, "capacity-plan")
    coordinate = require_dict(value.get("coordinateSystem"), "coordinateSystem")
    if coordinate.get("space") != "board-comp":
        raise ValueError("coordinateSystem.space must be board-comp")
    _safe_region(value, coordinate)
    overlap_threshold = require_number(value.get("overlapThreshold"), "overlapThreshold")
    if not 0 <= overlap_threshold <= 1:
        raise ValueError("overlapThreshold must be within 0..1")

    source_count = require_int(value.get("sourceTileCount"), "sourceTileCount")
    visible_count = require_int(value.get("visibleAnchorCount"), "visibleAnchorCount")
    physical_count = require_int(value.get("physicalSlotCount"), "physicalSlotCount")
    hidden_count = require_int(value.get("hiddenSlotCount"), "hiddenSlotCount")
    if visible_count < 1:
        raise ValueError("visibleAnchorCount must be positive")
    if source_count < visible_count:
        raise ValueError("sourceTileCount cannot be smaller than visibleAnchorCount")
    if physical_count != source_count:
        raise ValueError("physicalSlotCount must equal sourceTileCount")
    if hidden_count != source_count - visible_count:
        raise ValueError("hiddenSlotCount must equal sourceTileCount - visibleAnchorCount")

    slots = require_list(value.get("slots"), "slots")
    if len(slots) != source_count:
        raise ValueError("len(slots) must equal sourceTileCount")
    safe = require_dict(value.get("safeRegion"), "safeRegion")
    slot_ids: list[str] = []
    slot_by_id: dict[str, dict[str, Any]] = {}
    depths_by_anchor: dict[str, list[int]] = defaultdict(list)
    provenance_counts: Counter[str] = Counter()
    for index, row in enumerate(slots):
        slot = require_dict(row, f"slots[{index}]")
        slot_id = require_str(slot.get("slotId"), f"slots[{index}].slotId")
        slot_ids.append(slot_id)
        slot_by_id[slot_id] = slot
        anchor_id = require_str(slot.get("surfaceAnchorId"), f"slots[{index}].surfaceAnchorId")
        depth = require_int(slot.get("depthIndex"), f"slots[{index}].depthIndex")
        if depth < 0:
            raise ValueError("depthIndex must be non-negative")
        depths_by_anchor[anchor_id].append(depth)
        center = vector(slot.get("center"), f"slots[{index}].center")
        size = vector(slot.get("size"), f"slots[{index}].size")
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError("slot size must be positive")
        rectangle = [
            center[0] - size[0] / 2,
            center[1] - size[1] / 2,
            center[0] + size[0] / 2,
            center[1] + size[1] / 2,
        ]
        if (
            rectangle[0] < float(safe["left"])
            or rectangle[1] < float(safe["top"])
            or rectangle[2] > float(safe["right"])
            or rectangle[3] > float(safe["bottom"])
        ):
            raise ValueError(f"{slot_id}: slot rectangle is outside safeRegion")
        require_int(slot.get("row"), f"slots[{index}].row")
        require_int(slot.get("column"), f"slots[{index}].column")
        provenance = slot.get("provenance")
        if provenance not in {
            "observed-top-surface",
            "observed-depth",
            "inferred-depth",
            "synthesized-for-surplus",
        }:
            raise ValueError(f"slots[{index}].provenance is invalid")
        provenance_counts[str(provenance)] += 1
        visibility = slot.get("visibility")
        if depth == 0:
            if provenance != "observed-top-surface" or visibility != "visible":
                raise ValueError(f"{slot_id}: depth 0 must be an observed visible top surface")
        else:
            if provenance == "observed-top-surface":
                raise ValueError(f"{slot_id}: hidden depth cannot be observed-top-surface")
            if visibility not in {"fully-hidden", "near-shared"}:
                raise ValueError(f"{slot_id}: hidden slot visibility is invalid")
    unique(slot_ids, "physical slot IDs")
    if len(depths_by_anchor) != visible_count:
        raise ValueError("Each visible anchor must own at least one physical slot")
    for anchor_id, depths in depths_by_anchor.items():
        if sorted(depths) != list(range(len(depths))):
            raise ValueError(f"{anchor_id}: depth indices must be contiguous from 0")

    declared_provenance = require_dict(value.get("provenanceCounts"), "provenanceCounts")
    normalized_declared = {
        str(key): require_int(count, f"provenanceCounts.{key}")
        for key, count in declared_provenance.items()
    }
    if normalized_declared != dict(sorted(provenance_counts.items())):
        raise ValueError("provenanceCounts does not match slots")
    if provenance_counts.get("observed-top-surface", 0) != visible_count:
        raise ValueError("Exactly one observed top-surface slot is required per visible anchor")
    if sum(count for key, count in provenance_counts.items() if key != "observed-top-surface") != hidden_count:
        raise ValueError("hiddenSlotCount does not match non-surface slot provenance")

    per_anchor = require_list(value.get("perAnchorCapacity"), "perAnchorCapacity")
    if len(per_anchor) != visible_count:
        raise ValueError("perAnchorCapacity must contain exactly one row per visible anchor")
    capacity_ids: list[str] = []
    for index, raw in enumerate(per_anchor):
        row = require_dict(raw, f"perAnchorCapacity[{index}]")
        anchor_id = require_str(row.get("anchorId"), f"perAnchorCapacity[{index}].anchorId")
        capacity_ids.append(anchor_id)
        total = require_int(row.get("totalDepth"), f"{anchor_id}.totalDepth")
        minimum = require_int(row.get("evidenceMinDepth"), f"{anchor_id}.evidenceMinDepth")
        maximum = require_int(row.get("evidenceMaxDepth"), f"{anchor_id}.evidenceMaxDepth")
        surplus = require_int(row.get("surplusDepth"), f"{anchor_id}.surplusDepth")
        if anchor_id not in depths_by_anchor:
            raise ValueError(f"perAnchorCapacity refers to unknown anchor {anchor_id}")
        if total != len(depths_by_anchor[anchor_id]):
            raise ValueError(f"{anchor_id}: totalDepth does not match physical slots")
        if not 1 <= minimum <= maximum:
            raise ValueError(f"{anchor_id}: invalid evidence depth interval")
        if not minimum <= total <= maximum:
            raise ValueError(f"{anchor_id}: totalDepth is outside the locked evidence/policy range")
        if surplus != total - minimum:
            raise ValueError(f"{anchor_id}: surplusDepth must equal totalDepth - evidenceMinDepth")
    unique(capacity_ids, "perAnchorCapacity anchor IDs")
    if set(capacity_ids) != set(depths_by_anchor):
        raise ValueError("perAnchorCapacity anchor coverage does not match slots")

    edges = require_list(value.get("frontBackEdges", []), "frontBackEdges")
    known = set(slot_ids)
    edge_keys: list[str] = []
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {slot_id: 0 for slot_id in slot_ids}
    same_anchor_edges: set[tuple[str, str]] = set()
    for index, row in enumerate(edges):
        edge = require_dict(row, f"frontBackEdges[{index}]")
        front = require_str(edge.get("frontSlotId"), f"frontBackEdges[{index}].frontSlotId")
        back = require_str(edge.get("backSlotId"), f"frontBackEdges[{index}].backSlotId")
        if front == back or front not in known or back not in known:
            raise ValueError(f"frontBackEdges[{index}] has invalid endpoints")
        edge_keys.append(f"{front}->{back}")
        adjacency[front].append(back)
        indegree[back] += 1
        kind = require_str(edge.get("kind"), f"frontBackEdges[{index}].kind")
        if edge.get("evidenceClass") not in {"observed", "inferred", "unknown"}:
            raise ValueError(f"frontBackEdges[{index}].evidenceClass is invalid")
        if kind == "same-anchor-depth-chain":
            front_slot = slot_by_id[front]
            back_slot = slot_by_id[back]
            if front_slot["surfaceAnchorId"] != back_slot["surfaceAnchorId"]:
                raise ValueError("same-anchor-depth-chain must stay within one surface anchor")
            if int(back_slot["depthIndex"]) != int(front_slot["depthIndex"]) + 1:
                raise ValueError("same-anchor-depth-chain must connect adjacent depth indices")
            same_anchor_edges.add((front, back))
    unique(edge_keys, "front/back edge identities")
    expected_same_anchor_edges = {
        (f"{anchor_id}::d{depth}", f"{anchor_id}::d{depth + 1}")
        for anchor_id, depths in depths_by_anchor.items()
        for depth in range(len(depths) - 1)
    }
    if same_anchor_edges != expected_same_anchor_edges:
        raise ValueError("frontBackEdges must contain the complete adjacent same-anchor depth chain")
    queue: deque[str] = deque(slot_id for slot_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for child in adjacency.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(slot_ids):
        raise ValueError("frontBackEdges contains a cycle")

    offset = vector(value.get("hiddenOffsetPerDepth", [0.0, 0.0]), "hiddenOffsetPerDepth")
    safety = require_dict(value.get("safety"), "safety")
    if safety.get("visibleAnchorGeometryChanged") is not False:
        raise ValueError("safety.visibleAnchorGeometryChanged must be false")
    if safety.get("sourceFactsWritable") is not False:
        raise ValueError("safety.sourceFactsWritable must be false")
    if safety.get("hiddenCapacityMayExpandSilhouette") is not (offset[:2] != [0.0, 0.0]):
        raise ValueError("hiddenCapacityMayExpandSilhouette does not match hiddenOffsetPerDepth")

    _sha256(value.get("sourceFactsSha256"), "sourceFactsSha256")
    _sha256(value.get("visibleLayoutSha256"), "visibleLayoutSha256")
    _sha256(value.get("depthEvidenceSha256"), "depthEvidenceSha256")
    _review(value)


def validate_assignment(value: dict[str, Any]) -> None:
    _base(value, "assignment")
    if value.get("status") != "solved":
        raise ValueError("assignment.status must be solved")
    rows = require_list(value.get("assignments"), "assignments")
    if require_int(value.get("assignmentCount", len(rows)), "assignmentCount") != len(rows):
        raise ValueError("assignmentCount mismatch")
    tile_ids: list[str] = []
    slot_ids: list[str] = []
    for index, row in enumerate(rows):
        assignment = require_dict(row, f"assignments[{index}]")
        if set(assignment) != {"tileId", "slotId"}:
            raise ValueError(
                f"assignments[{index}] may contain only tileId and slotId; got {sorted(assignment)}"
            )
        tile_ids.append(require_str(assignment.get("tileId"), f"assignments[{index}].tileId"))
        slot_ids.append(require_str(assignment.get("slotId"), f"assignments[{index}].slotId"))
    unique(tile_ids, "assigned tile IDs")
    unique(slot_ids, "assigned slot IDs")
    _sha256(value.get("sourceFactsSha256"), "sourceFactsSha256")
    _sha256(value.get("capacityPlanSha256"), "capacityPlanSha256")
    diagnostics = require_dict(value.get("diagnostics"), "diagnostics")
    for key in ("blockedClickCount", "identityErrorCount", "boundsErrorCount", "occlusionOrderViolationCount"):
        if require_int(diagnostics.get(key, 0), f"diagnostics.{key}") != 0:
            raise ValueError(f"assignment cannot be locked with {key} > 0")


def validate_simulation(value: dict[str, Any]) -> None:
    _base(value, "simulation-report")
    if value.get("status") != "passed":
        raise ValueError("simulation-report.status must be passed")
    if value.get("writeAuthorized") is not True:
        raise ValueError("simulation-report.writeAuthorized must be true")
    _sha256(value.get("sourceFactsSha256"), "sourceFactsSha256")
    _sha256(value.get("capacityPlanSha256"), "capacityPlanSha256")
    _sha256(value.get("assignmentSha256"), "assignmentSha256")
    authority = require_dict(value.get("sourceFactAuthority"), "sourceFactAuthority")
    if authority.get("assignmentMayOverrideSourceFacts") is not False:
        raise ValueError("assignmentMayOverrideSourceFacts must be false")
    for key in (
        "blockedClickCount",
        "identityErrorCount",
        "boundsErrorCount",
        "matchErrorCount",
        "occlusionOrderViolationCount",
    ):
        if require_int(value.get(key, 0), key) != 0:
            raise ValueError(f"{key} must be zero")


def validate_property_plan(value: dict[str, Any]) -> None:
    _base(value, "property-plan")
    updates = require_list(value.get("propertyUpdates"), "propertyUpdates")
    if require_int(value.get("propertyUpdateCount"), "propertyUpdateCount") != len(updates):
        raise ValueError("propertyUpdateCount mismatch")
    identities: list[str] = []
    for index, raw in enumerate(updates):
        update = require_dict(raw, f"propertyUpdates[{index}]")
        comp_id = require_int(update.get("compId"), f"propertyUpdates[{index}].compId")
        layer_index = require_int(update.get("layerIndex"), f"propertyUpdates[{index}].layerIndex")
        require_str(update.get("layerName"), f"propertyUpdates[{index}].layerName")
        if update.get("sourceId") is not None:
            require_int(update.get("sourceId"), f"propertyUpdates[{index}].sourceId")
        match_name = require_str(update.get("propertyMatchName"), f"propertyUpdates[{index}].propertyMatchName")
        if match_name not in {"ADBE Position", "ADBE Scale"}:
            raise ValueError(f"propertyUpdates[{index}]: unsupported propertyMatchName {match_name}")
        identities.append(f"{comp_id}/{layer_index}/{match_name}")
        expected_num_keys = require_int(update.get("expectedNumKeys"), f"propertyUpdates[{index}].expectedNumKeys")
        if expected_num_keys < 0:
            raise ValueError("expectedNumKeys must be non-negative")
        tolerance = require_number(update.get("tolerance", 0.5), f"propertyUpdates[{index}].tolerance")
        if tolerance < 0:
            raise ValueError("property tolerance must be non-negative")
        keys = update.get("keys")
        if expected_num_keys == 0:
            if keys not in (None, []):
                raise ValueError("unkeyed property update cannot contain key writes")
            vector(update.get("expectedValue"), f"propertyUpdates[{index}].expectedValue")
            vector(update.get("newValue"), f"propertyUpdates[{index}].newValue")
        else:
            key_rows = require_list(keys, f"propertyUpdates[{index}].keys")
            if not key_rows:
                raise ValueError("keyed property update must contain at least one key write")
            key_numbers: list[str] = []
            for key_index, key_raw in enumerate(key_rows):
                key = require_dict(key_raw, f"propertyUpdates[{index}].keys[{key_index}]")
                number = require_int(key.get("keyNumber"), f"propertyUpdates[{index}].keys[{key_index}].keyNumber")
                if not 1 <= number <= expected_num_keys:
                    raise ValueError("keyNumber must be within 1..expectedNumKeys")
                key_numbers.append(str(number))
                vector(key.get("expectedOld"), f"propertyUpdates[{index}].keys[{key_index}].expectedOld")
                vector(key.get("newValue"), f"propertyUpdates[{index}].keys[{key_index}].newValue")
                if require_number(key.get("tolerance", tolerance), f"propertyUpdates[{index}].keys[{key_index}].tolerance") < 0:
                    raise ValueError("key tolerance must be non-negative")
            unique(key_numbers, f"propertyUpdates[{index}] key numbers")
    unique(identities, "property target identities")

    provenance = require_dict(value.get("provenance"), "provenance")
    for key in ("sourceFactsSha256", "capacityPlanSha256", "assignmentSha256", "simulationSha256", "inspectionSha256"):
        _sha256(provenance.get(key), f"provenance.{key}")
    if value.get("sourceRoute") is not None:
        _sha256(provenance.get("sourceRouteSha256"), "provenance.sourceRouteSha256")

    safety = require_dict(value.get("safety"), "safety")
    if (
        safety.get("originalAepEdited") is not False
        or safety.get("referenceSourceAepUsed") is not False
        or safety.get("referenceSourceGeometryUsed") is not False
    ):
        raise ValueError("Property-plan safety flags failed")
    route_scope = require_dict(value.get("routeScope"), "routeScope")
    require_list(route_scope.get("compIds", []), "routeScope.compIds")
    require_list(route_scope.get("routeCriticalFootageItemIds", []), "routeScope.routeCriticalFootageItemIds")
    baseline = require_dict(value.get("qaBaseline"), "qaBaseline")
    for key in ("acceptedMissingKeys", "acceptedExpressionErrorKeys", "acceptedEnabledWatermarkKeys"):
        require_list(baseline.get(key, []), f"qaBaseline.{key}")
    require_list(value.get("dependencyLocks", []), "dependencyLocks")
    require_list(value.get("requiredDisabledLayers", []), "requiredDisabledLayers")


def validate_apply_readback(value: dict[str, Any]) -> None:
    _base(value, "apply-readback")
    if value.get("ok") is not True:
        raise ValueError("apply-readback.ok must be true")
    for key in (
        "readbackErrors",
        "dependencyErrors",
        "disabledLayerErrors",
        "newRouteCriticalMissing",
        "newRouteExpressionErrors",
        "newEnabledWatermarks",
    ):
        if require_list(value.get(key, []), key):
            raise ValueError(f"{key} must be empty")
    for key in (
        "inputProjectUnchanged",
        "protectedSourceUnchanged",
        "originalSourceUnchanged",
    ):
        if value.get(key) is not True:
            raise ValueError(f"{key} must be true")
    if value.get("referenceSourceAepUsed") is not False:
        raise ValueError("referenceSourceAepUsed must be false")
    if value.get("referenceSourceGeometryUsed") is not False:
        raise ValueError("referenceSourceGeometryUsed must be false")
    _sha256(value.get("inputProjectSha256"), "inputProjectSha256")
    _sha256(value.get("protectedSourceSha256"), "protectedSourceSha256")


def validate_preview_qa(value: dict[str, Any]) -> None:
    _base(value, "preview-qa")
    if value.get("status") != "accepted":
        raise ValueError("preview-qa.status must be accepted")
    checks = require_list(value.get("checks"), "checks")
    failed = [row for row in checks if not isinstance(row, dict) or row.get("passed") is not True]
    if failed:
        raise ValueError(f"Preview checks failed: {failed}")
    if value.get("independentReview") is not True:
        raise ValueError("preview-qa.independentReview must be true")


def validate_full_render_qa(value: dict[str, Any]) -> None:
    _base(value, "full-render-qa")
    if value.get("status") != "passed":
        raise ValueError("full-render-qa.status must be passed")
    if require_list(value.get("errors", []), "errors"):
        raise ValueError("full-render-qa.errors must be empty")
    if value.get("fullDecodePassed") is not True:
        raise ValueError("fullDecodePassed must be true")
    if value.get("originalSourceUnchanged") is not True:
        raise ValueError("originalSourceUnchanged must be true")


VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "capability-preflight": validate_capability,
    "source-route": validate_source_route,
    "board-inventory": validate_board_inventory,
    "source-event-model": validate_event_model,
    "reference-roi": validate_reference_roi,
    "visible-layout": validate_visible_layout,
    "observed-depth": validate_depth_evidence,
    "capacity-plan": validate_capacity,
    "assignment": validate_assignment,
    "simulation-report": validate_simulation,
    "property-plan": validate_property_plan,
    "apply-readback": validate_apply_readback,
    "preview-qa": validate_preview_qa,
    "full-render-qa": validate_full_render_qa,
}


def validate_node_artifact(node: str, value: dict[str, Any]) -> None:
    if node not in NODE_ARTIFACT_TYPE:
        raise ValueError(f"Unknown node: {node}")
    expected = NODE_ARTIFACT_TYPE[node]
    validator = VALIDATORS.get(expected)
    if validator is None:
        raise ValueError(f"No artifact validator for node {node}")
    validator(value)
