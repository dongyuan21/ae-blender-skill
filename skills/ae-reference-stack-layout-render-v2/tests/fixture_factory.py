from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ae_stack_runtime.capacity import build_capacity, render_capacity_overlay
from ae_stack_runtime.common import now_iso, read_json, write_json
from ae_stack_runtime.property_plan import build_property_plan_with_route
from ae_stack_runtime.reference_model import lock_depth_evidence, lock_reference_roi, lock_visible_layout
from ae_stack_runtime.route import lock_source_route
from ae_stack_runtime.simulation import simulate_from_files
from ae_stack_runtime.solver import solve_assignment_from_files
from ae_stack_runtime.source_model import build_board_inventory, build_event_model
from ae_stack_runtime.visuals import render_assignment_overlay


ROW_COUNTS = [6, 5, 4, 3, 2, 2, 3, 4, 5, 6]
DEPTH_MATRIX = [
    [1, 1, 2, 2, 1, 1],
    [1, 1, 2, 1, 1],
    [1, 2, 2, 1],
    [1, 2, 1],
    [3, 2],
    [2, 3],
    [1, 2, 1],
    [1, 2, 2, 1],
    [1, 1, 1, 1, 1],
    [1, 1, 2, 2, 1, 1],
]


def approved_review(*, independent: bool = False, rationale: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"status": "approved", "issues": []}
    if independent:
        value["independentContext"] = True
    if rationale:
        value["rationale"] = rationale
    return value


def anchor_rows() -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for row, count in enumerate(ROW_COUNTS, 1):
        y = 330 + (row - 1) * 135
        start_x = 540 - (count - 1) * 65
        for column in range(1, count + 1):
            x = start_x + (column - 1) * 130
            anchors.append({
                "anchorId": f"r{row:02d}-c{column:02d}",
                "row": row,
                "column": column,
                "referenceCenter": [x, y],
                "referenceSize": [110, 90],
                "evidence": "observed",
                "confidence": 1.0,
            })
    return anchors


def _draw_reference(path: Path, anchors: list[dict[str, Any]]) -> None:
    image = Image.new("RGB", (1080, 1920), (238, 239, 242))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((85, 170, 995, 1745), radius=42, fill=(41, 48, 61), outline=(18, 22, 29), width=6)
    for anchor in anchors:
        x, y = anchor["referenceCenter"]
        width, height = anchor["referenceSize"]
        box = (x - width / 2, y - height / 2, x + width / 2, y + height / 2)
        row = int(anchor["row"])
        fill = (122 + (row * 13) % 82, 158 + (row * 17) % 72, 208 - (row * 11) % 85)
        draw.rounded_rectangle(box, radius=12, fill=fill, outline=(250, 250, 252), width=3)
        draw.ellipse((x - 14, y - 14, x + 14, y + 14), fill=(255, 255, 255), outline=(31, 35, 43), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _inspection(anchors: list[dict[str, Any]]) -> tuple[dict[str, Any], list[tuple[str, int, list[float]]]]:
    physical: list[tuple[str, int, list[float]]] = []
    anchor_by_id = {row["anchorId"]: row for row in anchors}
    for row_index, depth_row in enumerate(DEPTH_MATRIX, 1):
        for column_index, total_depth in enumerate(depth_row, 1):
            anchor_id = f"r{row_index:02d}-c{column_index:02d}"
            center = list(anchor_by_id[anchor_id]["referenceCenter"])
            for depth_index in range(total_depth):
                physical.append((anchor_id, depth_index, center))
    layers: list[dict[str, Any]] = []
    for layer_index, (_, _, center) in enumerate(physical, 1):
        layers.append({
            "compId": 101,
            "index": layer_index,
            "name": f"tile{layer_index:03d}",
            "enabled": True,
            "inPoint": 0.0,
            "outPoint": float(layer_index) + 0.25,
            "startTime": 0.0,
            "sourceId": 1000 + layer_index,
            "sourceName": f"face-{layer_index % 9}",
            "sourceType": "footage",
            "sourceWidth": 110,
            "sourceHeight": 90,
            "parentIndex": None,
            "hasTrackMatte": False,
            "threeDLayer": False,
            "transform": {
                "anchor": {"numKeys": 0, "value": [55, 45], "keys": []},
                "position": {"numKeys": 0, "value": center, "keys": []},
                "scale": {"numKeys": 0, "value": [100, 100], "keys": []},
                "rotation": {"numKeys": 0, "value": 0, "keys": []},
                "opacity": {"numKeys": 0, "value": 100, "keys": []},
            },
        })
    inspection = {
        "ok": True,
        "mode": "synthetic-read-only-stack-inspection-v2",
        "projectPath": "synthetic-hourglass.aep",
        "comp": {"id": 101, "name": "BOARD", "width": 1080, "height": 1920, "duration": 60.0, "frameRate": 30.0},
        "tileLayers": layers,
        "moverLayers": [],
        "handLayers": [],
        "otherAnimatedLayers": [],
        "allLayers": layers,
        "pairCandidates": [],
        "routeCriticalMissing": [],
        "routeExpressionErrors": [],
        "watermarkLayers": [],
        "baselineIssueKeys": {
            "acceptedMissingKeys": [],
            "acceptedMissingFootageKeys": [],
            "acceptedExpressionErrorKeys": [],
            "acceptedEnabledWatermarkKeys": [],
        },
    }
    return inspection, physical


def create_hourglass_fixture(output_dir: Path, *, build_property_plan: bool = True) -> dict[str, Path]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    anchors = anchor_rows()
    reference = output_dir / "synthetic-reference.png"
    _draw_reference(reference, anchors)

    roi_draft = {
        "boardRoi": {"left": 80, "top": 165, "right": 1000, "bottom": 1750},
        "excludedRegions": [],
        "review": approved_review(rationale="Synthetic fixture ROI contains only the board and stack."),
    }
    write_json(output_dir / "reference-roi-draft.json", roi_draft)
    lock_reference_roi(reference, output_dir / "reference-roi-draft.json", output_dir / "reference-roi.json")

    layout_draft = {
        "coordinateSystem": {"space": "board-comp", "width": 1080, "height": 1920},
        "referenceToBoardTransform": {"scaleX": 1.0, "scaleY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        "safeRegion": {"left": 80, "top": 165, "right": 1000, "bottom": 1750},
        "cardBody": {"width": 110, "height": 90},
        "grammar": {"family": "hourglass-rows", "rowCounts": ROW_COUNTS},
        "anchors": anchors,
        "silhouette": {"kind": "hourglass", "rowCounts": ROW_COUNTS},
        "holes": [],
        "proposerReview": approved_review(rationale="The draft contains exactly 40 visible top-surface anchors."),
        "reviewerReview": approved_review(independent=True, rationale="Independent overlay review confirms row counts and silhouette."),
    }
    write_json(output_dir / "visible-layout-draft.json", layout_draft)
    lock_visible_layout(
        output_dir / "reference-roi.json",
        output_dir / "visible-layout-draft.json",
        output_dir / "visible-layout.json",
        output_dir / "visible-layout-overlay.png",
    )

    depth_hints: list[dict[str, Any]] = []
    total_depth_by_anchor: dict[str, int] = {}
    for row_index, depth_row in enumerate(DEPTH_MATRIX, 1):
        for column_index, total_depth in enumerate(depth_row, 1):
            anchor_id = f"r{row_index:02d}-c{column_index:02d}"
            depth_hints.append({
                "anchorId": anchor_id,
                "minDepth": 1,
                "maxDepth": total_depth,
                "evidenceClass": "unknown",
                "rationale": "A single settled raster proves the visible surface, not fully hidden capacity.",
            })
            total_depth_by_anchor[anchor_id] = total_depth
    depth_draft = {
        "anchorDepthHints": depth_hints,
        "occlusionEdges": [],
        "review": approved_review(rationale="Hidden depth is explicitly deferred to capacity reconciliation."),
    }
    write_json(output_dir / "observed-depth-draft.json", depth_draft)
    lock_depth_evidence(
        output_dir / "visible-layout.json",
        output_dir / "observed-depth-draft.json",
        output_dir / "observed-depth.json",
    )

    inspection, physical = _inspection(anchors)
    write_json(output_dir / "synthetic-inspection.json", inspection)
    inventory_draft = {
        "boardCompId": 101,
        "candidateMode": "tileLayers",
        "decisions": [
            {
                "compId": 101,
                "layerIndex": index,
                "expectedLayerName": f"tile{index:03d}",
                "expectedSourceId": 1000 + index,
                "include": True,
                "tileId": f"tile-{index:03d}",
                "faceId": f"face-{index % 9}",
            }
            for index in range(1, len(physical) + 1)
        ],
        "review": approved_review(rationale="All 57 enabled synthetic board tiles are classified exactly once."),
    }
    write_json(output_dir / "board-inventory-draft.json", inventory_draft)
    build_board_inventory(
        output_dir / "synthetic-inspection.json",
        output_dir / "board-inventory-draft.json",
        output_dir / "board-inventory.json",
    )

    event_draft = {
        "pairTimeTolerance": 0.1,
        "removalTimeTolerance": 0.05,
        "requireContiguousOrdinals": True,
        "events": [
            {
                "tileId": f"tile-{index:03d}",
                "clickOrdinal": index,
                "clickTime": float(index),
                "declaredRemovalTime": float(index) + 0.25,
            }
            for index in range(1, len(physical) + 1)
        ],
        "review": approved_review(rationale="Synthetic click schedule is locked to AE in/out and layer identities."),
    }
    write_json(output_dir / "source-event-model-draft.json", event_draft)
    build_event_model(
        output_dir / "synthetic-inspection.json",
        output_dir / "board-inventory.json",
        output_dir / "source-event-model-draft.json",
        output_dir / "source-event-model.json",
    )

    capacity_policy = {
        "mode": "explicit-total-depth",
        "totalDepthByAnchor": total_depth_by_anchor,
        "hiddenOffsetPerDepth": [0.0, 0.0],
        "overlapThreshold": 0.001,
        "review": approved_review(
            rationale="40 visible anchors plus 17 synthesized hidden slots reconcile exactly to 57 source tiles."
        ),
    }
    write_json(output_dir / "capacity-policy.json", capacity_policy)
    build_capacity(
        output_dir / "source-event-model.json",
        output_dir / "visible-layout.json",
        output_dir / "observed-depth.json",
        output_dir / "capacity-policy.json",
        output_dir / "capacity-plan.json",
    )
    render_capacity_overlay(
        reference,
        output_dir / "visible-layout.json",
        output_dir / "capacity-plan.json",
        output_dir / "capacity-overlay.png",
    )

    constraints = {
        "seed": 0,
        "maxRepairIterations": 500,
        "candidateSwapLimit": 100,
        "randomSwapSamples": 300,
        "maxNoImprovementRounds": 3,
        "movementWeight": 20.0,
        "depthWeight": 40.0,
        "riskWeight": 0.0,
        "synthesizedSlotWeight": 0.0,
    }
    write_json(output_dir / "assignment-constraints.json", constraints)
    assignment = solve_assignment_from_files(
        output_dir / "source-event-model.json",
        output_dir / "capacity-plan.json",
        output_dir / "assignment-constraints.json",
    )
    write_json(output_dir / "assignment.json", assignment)
    if assignment["status"] != "solved":
        raise RuntimeError(f"Golden fixture assignment failed: {assignment['diagnostics']}")

    simulation = simulate_from_files(
        output_dir / "source-event-model.json",
        output_dir / "capacity-plan.json",
        output_dir / "assignment.json",
    )
    write_json(output_dir / "simulation-report.json", simulation)
    if simulation["status"] != "passed":
        raise RuntimeError(f"Golden fixture simulation failed: {simulation}")
    render_assignment_overlay(
        reference,
        output_dir / "visible-layout.json",
        output_dir / "source-event-model.json",
        output_dir / "capacity-plan.json",
        output_dir / "assignment.json",
        output_dir / "assignment-overlay.png",
    )

    route_draft = {
        "finalComp": {"id": 201, "name": "FINAL", "width": 1080, "height": 1920},
        "boardComp": {"id": 101, "name": "BOARD", "width": 1080, "height": 1920},
        "nestingPath": [
            {"compId": 201, "compName": "FINAL"},
            {"compId": 101, "compName": "BOARD"},
        ],
        "routeScope": {"compIds": [201, 101], "routeCriticalFootageItemIds": []},
        "qaBaseline": {
            "acceptedMissingKeys": [],
            "acceptedExpressionErrorKeys": [],
            "acceptedEnabledWatermarkKeys": [],
        },
        "renderSettings": {"renderCompId": 201, "editCompId": 101},
        "review": approved_review(rationale="Edit BOARD and render FINAL."),
    }
    write_json(output_dir / "source-route-draft.json", route_draft)
    lock_source_route(output_dir / "source-route-draft.json", output_dir / "source-route.json")

    if build_property_plan:
        write_json(output_dir / "property-plan-options.json", {})
        build_property_plan_with_route(
            output_dir / "synthetic-inspection.json",
            output_dir / "source-event-model.json",
            output_dir / "capacity-plan.json",
            output_dir / "assignment.json",
            output_dir / "simulation-report.json",
            output_dir / "source-route.json",
            output_dir / "property-plan-options.json",
            output_dir / "property-plan.json",
        )

    summary = {
        "schemaVersion": 2,
        "artifactType": "golden-fixture-summary",
        "createdAt": now_iso(),
        "visibleAnchorCount": 40,
        "physicalSlotCount": 57,
        "hiddenSlotCount": 17,
        "rowCounts": ROW_COUNTS,
        "depthMatrix": DEPTH_MATRIX,
        "expected": {
            "assignmentStatus": "solved",
            "simulationStatus": "passed",
            "blockedClickCount": 0,
            "occlusionOrderViolationCount": 0,
        },
    }
    write_json(output_dir / "fixture-summary.json", summary)
    return {path.name: path for path in output_dir.iterdir() if path.is_file()}
