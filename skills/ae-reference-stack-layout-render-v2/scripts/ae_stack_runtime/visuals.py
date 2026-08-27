from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .common import read_json, vector
from .contracts import validate_assignment, validate_capacity, validate_event_model, validate_visible_layout


def render_assignment_overlay(
    reference_image: Path,
    visible_layout_path: Path,
    event_model_path: Path,
    capacity_path: Path,
    assignment_path: Path,
    output_path: Path,
) -> None:
    visible = read_json(visible_layout_path)
    event = read_json(event_model_path)
    capacity = read_json(capacity_path)
    assignment = read_json(assignment_path)
    validate_visible_layout(visible)
    validate_event_model(event)
    validate_capacity(capacity)
    validate_assignment(assignment)

    tile_by_id = {str(row["tileId"]): row for row in event["tiles"]}
    tile_for_slot = {str(row["slotId"]): str(row["tileId"]) for row in assignment["assignments"]}
    slots_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for slot in capacity["slots"]:
        slots_by_anchor[str(slot["surfaceAnchorId"])].append(slot)
    anchors = {str(row["anchorId"]): row for row in visible["anchors"]}

    with Image.open(reference_image) as image:
        canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = ImageFont.load_default()
    transform = visible["referenceToBoardTransform"]
    default_size = [
        float(visible["cardBody"]["width"]) / abs(float(transform["scaleX"])),
        float(visible["cardBody"]["height"]) / abs(float(transform["scaleY"])),
    ]
    for anchor_id, anchor in anchors.items():
        center = vector(anchor["referenceCenter"], f"{anchor_id}.referenceCenter")
        size = vector(anchor.get("referenceSize", default_size), f"{anchor_id}.referenceSize")
        box = (
            center[0] - size[0] / 2,
            center[1] - size[1] / 2,
            center[0] + size[0] / 2,
            center[1] + size[1] / 2,
        )
        depth_slots = sorted(slots_by_anchor[anchor_id], key=lambda row: int(row["depthIndex"]))
        top_tile = tile_by_id[tile_for_slot[str(depth_slots[0]["slotId"])]]
        draw.rounded_rectangle(box, radius=max(3, int(min(size) * 0.08)), fill=(72, 148, 238, 58), outline=(255, 255, 255, 235), width=2)
        draw.text(
            (box[0] + 4, box[1] + 4),
            f"{anchor_id}\nL{top_tile['layerIndex']} {top_tile.get('faceId', '')}",
            font=font,
            fill=(8, 8, 8, 255),
        )
        if len(depth_slots) > 1:
            hidden = [
                f"d{slot['depthIndex']}:L{tile_by_id[tile_for_slot[str(slot['slotId'])]]['layerIndex']}"
                for slot in depth_slots[1:]
            ]
            draw.text((box[0] + 4, box[3] - 12 * len(hidden) - 2), "\n".join(hidden), font=font, fill=(80, 0, 0, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
