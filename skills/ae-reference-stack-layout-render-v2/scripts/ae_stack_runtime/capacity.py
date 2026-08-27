from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .common import (
    SCHEMA_VERSION,
    now_iso,
    path_state,
    read_json,
    require_dict,
    require_int,
    require_list,
    require_str,
    sha256_file,
    vector,
    write_json,
)
from .contracts import validate_capacity, validate_depth_evidence, validate_event_model, validate_visible_layout


def _explicit_depths(
    anchors: list[dict[str, Any]],
    hints: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    source_count: int,
) -> dict[str, int]:
    raw = require_dict(policy.get("totalDepthByAnchor"), "totalDepthByAnchor")
    anchor_ids = {str(anchor["anchorId"]) for anchor in anchors}
    missing = sorted(anchor_ids - set(raw))
    unknown = sorted(set(raw) - anchor_ids)
    if missing:
        raise ValueError(f"totalDepthByAnchor is missing anchors: {missing[:20]}")
    if unknown:
        raise ValueError(f"totalDepthByAnchor contains unknown anchors: {unknown[:20]}")
    result: dict[str, int] = {}
    for anchor_id in sorted(anchor_ids):
        depth = require_int(raw[anchor_id], f"totalDepthByAnchor.{anchor_id}")
        hint = hints[anchor_id]
        minimum = int(hint.get("minDepth", 1))
        maximum = int(hint.get("maxDepth", max(minimum, depth)))
        if not minimum <= depth <= maximum:
            raise ValueError(f"{anchor_id}: explicit depth {depth} is outside locked range {minimum}..{maximum}")
        result[anchor_id] = depth
    if sum(result.values()) != source_count:
        raise ValueError(
            f"Explicit capacity totals {sum(result.values())}, but source event model contains {source_count} tiles"
        )
    return result


def _balanced_depths(
    anchors: list[dict[str, Any]],
    hints: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    source_count: int,
) -> dict[str, int]:
    result = {anchor_id: max(1, int(hint.get("minDepth", 1))) for anchor_id, hint in hints.items()}
    minimum_total = sum(result.values())
    if minimum_total > source_count:
        raise ValueError(
            f"Locked depth evidence requires at least {minimum_total} physical tiles, but source has {source_count}"
        )
    max_total_default = require_int(policy.get("maxTotalDepth", 3), "maxTotalDepth")
    if max_total_default < 1:
        raise ValueError("maxTotalDepth must be >= 1")
    preferred = [str(value) for value in require_list(policy.get("preferredAnchorIds", []), "preferredAnchorIds")]
    anchor_ids = [str(anchor["anchorId"]) for anchor in anchors]
    unknown = sorted(set(preferred) - set(anchor_ids))
    if unknown:
        raise ValueError(f"preferredAnchorIds contains unknown anchors: {unknown}")
    order = preferred + [anchor_id for anchor_id in anchor_ids if anchor_id not in preferred]
    remaining = source_count - minimum_total
    while remaining:
        progressed = False
        for anchor_id in order:
            hint_max = int(hints[anchor_id].get("maxDepth", max_total_default))
            maximum = min(max_total_default, hint_max)
            if result[anchor_id] >= maximum:
                continue
            result[anchor_id] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            raise ValueError(
                f"Cannot fit {source_count} source tiles within locked/policy maximum depth; "
                f"capacity stopped at {sum(result.values())}"
            )
    return result


def build_capacity_data(
    event_model: dict[str, Any],
    visible_layout: dict[str, Any],
    depth_evidence: dict[str, Any],
    policy: dict[str, Any],
    event_model_path: Path,
    visible_layout_path: Path,
    depth_evidence_path: Path,
) -> dict[str, Any]:
    validate_event_model(event_model)
    validate_visible_layout(visible_layout)
    validate_depth_evidence(depth_evidence)
    source_count = len(event_model["tiles"])
    anchors = [require_dict(row, "anchors[]") for row in visible_layout["anchors"]]
    anchor_by_id = {str(anchor["anchorId"]): anchor for anchor in anchors}
    hints = {
        str(row["anchorId"]): require_dict(row, "anchorDepthHints[]")
        for row in depth_evidence["anchorDepthHints"]
    }
    if set(hints) != set(anchor_by_id):
        raise ValueError("Depth evidence must contain exactly one hint for every visible anchor")
    mode = str(policy.get("mode", "balanced"))
    if mode == "explicit-total-depth":
        totals = _explicit_depths(anchors, hints, policy, source_count)
    elif mode == "balanced":
        totals = _balanced_depths(anchors, hints, policy, source_count)
    else:
        raise ValueError("capacity policy mode must be explicit-total-depth or balanced")

    card_default = [float(visible_layout["cardBody"]["width"]), float(visible_layout["cardBody"]["height"])]
    offset = vector(policy.get("hiddenOffsetPerDepth", [0.0, 0.0]), "hiddenOffsetPerDepth")[:2]
    if abs(offset[0]) > card_default[0] * 0.05 or abs(offset[1]) > card_default[1] * 0.05:
        if policy.get("allowNearSharedCenters") is not True:
            raise ValueError(
                "hiddenOffsetPerDepth exceeds 5% of card size; set allowNearSharedCenters=true with visual justification"
            )
    slots: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    per_anchor: list[dict[str, Any]] = []
    for anchor in anchors:
        anchor_id = str(anchor["anchorId"])
        base_center = vector(anchor["center"], f"{anchor_id}.center")[:2]
        size = vector(anchor.get("size", card_default), f"{anchor_id}.size")[:2]
        total_depth = totals[anchor_id]
        hint = hints[anchor_id]
        minimum = int(hint.get("minDepth", 1))
        evidence_class = str(hint.get("evidenceClass", "unknown"))
        per_anchor.append({
            "anchorId": anchor_id,
            "totalDepth": total_depth,
            "evidenceMinDepth": minimum,
            "evidenceMaxDepth": int(hint.get("maxDepth", total_depth)),
            "surplusDepth": max(0, total_depth - minimum),
        })
        previous_slot: str | None = None
        for depth_index in range(total_depth):
            slot_id = f"{anchor_id}::d{depth_index}"
            if depth_index == 0:
                provenance = "observed-top-surface"
                visibility = "visible"
            elif depth_index < minimum:
                provenance = "observed-depth" if evidence_class == "observed" else "inferred-depth"
                visibility = "fully-hidden" if offset == [0.0, 0.0] else "near-shared"
            else:
                provenance = "synthesized-for-surplus"
                visibility = "fully-hidden" if offset == [0.0, 0.0] else "near-shared"
            center = [base_center[0] + offset[0] * depth_index, base_center[1] + offset[1] * depth_index]
            slots.append({
                "slotId": slot_id,
                "surfaceAnchorId": anchor_id,
                "depthIndex": depth_index,
                "center": center,
                "size": size,
                "row": int(anchor["row"]),
                "column": int(anchor["column"]),
                "depthBandId": anchor.get("depthBandId") or f"depth-{depth_index}",
                "visibility": visibility,
                "provenance": provenance,
                "source": {
                    "anchorEvidence": anchor.get("evidence"),
                    "depthEvidenceClass": evidence_class,
                },
            })
            if previous_slot is not None:
                edges.append({
                    "frontSlotId": previous_slot,
                    "backSlotId": slot_id,
                    "kind": "same-anchor-depth-chain",
                    "evidenceClass": "inferred" if provenance == "synthesized-for-surplus" else evidence_class,
                })
            previous_slot = slot_id
    for edge in depth_evidence.get("occlusionEdges", []):
        front_anchor = str(edge["frontAnchorId"])
        back_anchor = str(edge["backAnchorId"])
        edges.append({
            "frontSlotId": f"{front_anchor}::d0",
            "backSlotId": f"{back_anchor}::d0",
            "kind": "reference-occlusion",
            "evidenceClass": edge.get("evidenceClass"),
        })
    provenance_counts = Counter(str(slot["provenance"]) for slot in slots)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "capacity-plan",
        "createdAt": now_iso(),
        "mode": mode,
        "coordinateSystem": visible_layout["coordinateSystem"],
        "safeRegion": visible_layout["safeRegion"],
        "overlapThreshold": float(policy.get("overlapThreshold", 0.001)),
        "sourceTileCount": source_count,
        "visibleAnchorCount": len(anchors),
        "physicalSlotCount": len(slots),
        "hiddenSlotCount": len(slots) - len(anchors),
        "sourceFactsSha256": event_model["sourceFactsSha256"],
        "visibleLayoutSha256": sha256_file(visible_layout_path),
        "depthEvidenceSha256": sha256_file(depth_evidence_path),
        "eventModel": path_state(event_model_path),
        "visibleLayout": path_state(visible_layout_path),
        "depthEvidence": path_state(depth_evidence_path),
        "perAnchorCapacity": per_anchor,
        "provenanceCounts": dict(sorted(provenance_counts.items())),
        "hiddenOffsetPerDepth": offset,
        "slots": slots,
        "frontBackEdges": edges,
        "review": require_dict(policy.get("review"), "review"),
        "safety": {
            "visibleAnchorGeometryChanged": False,
            "hiddenCapacityMayExpandSilhouette": offset != [0.0, 0.0],
            "sourceFactsWritable": False,
        },
    }
    validate_capacity(result)
    return result


def build_capacity(
    event_model_path: Path,
    visible_layout_path: Path,
    depth_evidence_path: Path,
    policy_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    event_model = read_json(event_model_path)
    visible_layout = read_json(visible_layout_path)
    depth_evidence = read_json(depth_evidence_path)
    policy = read_json(policy_path)
    result = build_capacity_data(
        event_model,
        visible_layout,
        depth_evidence,
        policy,
        event_model_path,
        visible_layout_path,
        depth_evidence_path,
    )
    write_json(output_path, result)
    return result


def render_capacity_overlay(
    reference_image: Path,
    visible_layout_path: Path,
    capacity_path: Path,
    output_path: Path,
) -> None:
    visible = read_json(visible_layout_path)
    capacity = read_json(capacity_path)
    totals = {str(row["anchorId"]): int(row["totalDepth"]) for row in capacity["perAnchorCapacity"]}
    with Image.open(reference_image) as image:
        canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = ImageFont.load_default()
    default_size = [float(visible["cardBody"]["width"]), float(visible["cardBody"]["height"])]
    palette = {
        1: (74, 194, 132, 115),
        2: (255, 188, 62, 135),
        3: (238, 82, 78, 145),
    }
    for anchor in visible["anchors"]:
        anchor_id = str(anchor["anchorId"])
        total = totals[anchor_id]
        transform = visible["referenceToBoardTransform"]
        center = vector(anchor.get("referenceCenter"), f"{anchor_id}.referenceCenter")
        size = vector(
            anchor.get(
                "referenceSize",
                [default_size[0] / abs(float(transform["scaleX"])), default_size[1] / abs(float(transform["scaleY"]))],
            ),
            f"{anchor_id}.referenceSize",
        )
        box = (
            center[0] - size[0] / 2,
            center[1] - size[1] / 2,
            center[0] + size[0] / 2,
            center[1] + size[1] / 2,
        )
        fill = palette.get(total, (170, 90, 220, 145))
        draw.rounded_rectangle(box, radius=max(3, int(min(size) * 0.08)), fill=fill, outline=(255, 255, 255, 235), width=2)
        draw.text((box[0] + 5, box[1] + 5), f"{anchor_id}  d={total}", font=font, fill=(10, 10, 10, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
