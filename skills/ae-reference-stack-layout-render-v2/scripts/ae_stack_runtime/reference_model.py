from __future__ import annotations

import math
import shutil
from collections import defaultdict, deque
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
    require_number,
    require_str,
    sha256_file,
    unique,
    vector,
    write_json,
)
from .contracts import validate_depth_evidence, validate_reference_roi, validate_visible_layout


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        alpha_extrema = None
        if "A" in image.getbands():
            alpha_extrema = list(image.getchannel("A").getextrema())
        return {
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "alphaExtrema": alpha_extrema,
        }


def analyze_reference(image_path: Path, output_dir: Path, card_width: float | None = None, card_height: float | None = None) -> dict[str, Any]:
    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = image_metadata(image_path)
    evidence_path = output_dir / "reference-pixel-evidence.png"
    analysis: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "reference-pixel-analysis",
        "createdAt": now_iso(),
        "referenceImage": {**path_state(image_path), **metadata},
        "method": "Pillow metadata plus optional OpenCV edge/line/corner/contour evidence",
        "manualReviewRequired": True,
        "directAepWriteAuthorized": False,
        "nextRequiredArtifacts": ["reference-roi", "visible-layout", "observed-depth"],
        "safety": {
            "referenceSourceAepUsed": False,
            "referenceSourceGeometryUsed": False,
        },
    }
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        raw = np.fromfile(str(image_path), dtype=np.uint8)
        source = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if source is None:
            raise RuntimeError("OpenCV could not decode the reference image")
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        median = float(np.median(gray))
        low = max(0, int(0.66 * median))
        high = min(255, int(1.33 * median))
        if high <= low:
            low, high = 50, 150
        edges = cv2.Canny(gray, low, high)
        min_line = max(12, int(min(source.shape[:2]) * 0.025))
        lines_raw = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180.0,
            threshold=25,
            minLineLength=min_line,
            maxLineGap=max(4, min_line // 3),
        )
        lines: list[dict[str, Any]] = []
        if lines_raw is not None:
            for raw_line in lines_raw[:500]:
                values = np.asarray(raw_line).reshape(-1)
                if values.size < 4:
                    continue
                x1, y1, x2, y2 = [int(value) for value in values[:4]]
                lines.append({
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "length": round(math.hypot(x2 - x1, y2 - y1), 3),
                    "angle": round(math.degrees(math.atan2(y2 - y1, x2 - x1)), 3),
                })
        lines.sort(key=lambda item: item["length"], reverse=True)
        corners_raw = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=500,
            qualityLevel=0.01,
            minDistance=max(3, min(source.shape[:2]) // 250),
            blockSize=5,
        )
        corners: list[list[float]] = []
        if corners_raw is not None:
            for point in corners_raw:
                values = np.asarray(point).reshape(-1)
                if values.size >= 2:
                    corners.append([round(float(values[0]), 3), round(float(values[1]), 3)])
        contours_raw, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[dict[str, Any]] = []
        image_area = source.shape[0] * source.shape[1]
        for contour in contours_raw:
            x, y, width, height = cv2.boundingRect(contour)
            area = width * height
            if area < image_area * 0.0004 or area > image_area * 0.25 or width < 8 or height < 8:
                continue
            aspect = width / float(height)
            if not 0.35 <= aspect <= 2.8:
                continue
            if card_width and not card_width * 0.45 <= width <= card_width * 1.7:
                continue
            if card_height and not card_height * 0.45 <= height <= card_height * 1.7:
                continue
            candidates.append({
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
                "center": [round(x + width / 2.0, 3), round(y + height / 2.0, 3)],
                "aspect": round(aspect, 4),
                "perimeter": round(float(cv2.arcLength(contour, True)), 3),
            })
        candidates.sort(key=lambda item: item["perimeter"], reverse=True)
        candidates = candidates[:200]
        overlay = source.copy()
        for line in lines[:150]:
            cv2.line(overlay, (line["x1"], line["y1"]), (line["x2"], line["y2"]), (30, 30, 235), 1, cv2.LINE_AA)
        for x, y in corners[:350]:
            cv2.circle(overlay, (int(round(x)), int(round(y))), 2, (30, 220, 30), -1, cv2.LINE_AA)
        for candidate in candidates[:80]:
            cv2.rectangle(
                overlay,
                (candidate["x"], candidate["y"]),
                (candidate["x"] + candidate["width"], candidate["y"] + candidate["height"]),
                (235, 150, 20),
                1,
                cv2.LINE_AA,
            )
        ok, encoded = cv2.imencode(".png", overlay)
        if not ok:
            raise RuntimeError("OpenCV could not encode evidence overlay")
        encoded.tofile(str(evidence_path))
        analysis.update({
            "opencvAvailable": True,
            "canny": {"low": low, "high": high, "edgePixelCount": int(np.count_nonzero(edges))},
            "lineSegmentCount": len(lines),
            "lineSegments": lines,
            "cornerCount": len(corners),
            "corners": corners,
            "contourCandidateCount": len(candidates),
            "contourCandidates": candidates,
            "evidenceOverlay": path_state(evidence_path),
            "legend": {"red": "Hough line", "green": "corner", "blue": "contour candidate"},
        })
    except (ImportError, ModuleNotFoundError) as error:
        shutil.copy2(image_path, evidence_path)
        analysis.update({
            "opencvAvailable": False,
            "opencvError": str(error),
            "evidenceOverlay": path_state(evidence_path),
        })
    output_path = output_dir / "reference-image-analysis.json"
    write_json(output_path, analysis)
    return {**analysis, "outputPath": str(output_path), "evidencePath": str(evidence_path)}


def lock_reference_roi(reference_image: Path, draft_path: Path, output_path: Path) -> dict[str, Any]:
    draft = read_json(draft_path)
    metadata = image_metadata(reference_image)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "reference-roi",
        "createdAt": now_iso(),
        "referenceImage": {**path_state(reference_image), **metadata},
        "boardRoi": require_dict(draft.get("boardRoi"), "boardRoi"),
        "excludedRegions": require_list(draft.get("excludedRegions", []), "excludedRegions"),
        "review": require_dict(draft.get("review"), "review"),
        "analysis": draft.get("analysis"),
    }
    validate_reference_roi(result)
    write_json(output_path, result)
    return result


def _draw_anchor_overlay(reference_image: Path, layout: dict[str, Any], output_path: Path) -> None:
    with Image.open(reference_image) as image:
        canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    transform = layout["referenceToBoardTransform"]
    scale_x = float(transform["scaleX"])
    scale_y = float(transform["scaleY"])
    default_size = [
        float(layout["cardBody"]["width"]) / abs(scale_x),
        float(layout["cardBody"]["height"]) / abs(scale_y),
    ]
    font = ImageFont.load_default()
    for anchor in layout["anchors"]:
        center = vector(anchor.get("referenceCenter"), "anchor.referenceCenter")
        size = vector(anchor.get("referenceSize", default_size), "anchor.referenceSize")
        left = center[0] - size[0] / 2.0
        top = center[1] - size[1] / 2.0
        right = center[0] + size[0] / 2.0
        bottom = center[1] + size[1] / 2.0
        row = int(anchor["row"])
        fill = (55 + (row * 37) % 160, 120 + (row * 23) % 100, 220 - (row * 29) % 130, 48)
        outline = (255, 255, 255, 230)
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=max(3, int(min(size) * 0.08)),
            fill=fill,
            outline=outline,
            width=2,
        )
        draw.text((left + 4, top + 4), str(anchor["anchorId"]), font=font, fill=(10, 10, 10, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def lock_visible_layout(
    roi_path: Path,
    draft_path: Path,
    output_path: Path,
    overlay_path: Path | None = None,
) -> dict[str, Any]:
    roi = read_json(roi_path)
    validate_reference_roi(roi)
    draft = read_json(draft_path)
    reference_width = float(roi["referenceImage"]["width"])
    reference_height = float(roi["referenceImage"]["height"])
    coordinate = require_dict(
        draft.get("coordinateSystem", {"space": "board-comp", "width": reference_width, "height": reference_height}),
        "coordinateSystem",
    )
    coordinate = {
        "space": str(coordinate.get("space", "board-comp")),
        "width": require_number(coordinate.get("width"), "coordinateSystem.width"),
        "height": require_number(coordinate.get("height"), "coordinateSystem.height"),
    }
    mapping_raw = require_dict(draft.get("referenceToBoardTransform", {}), "referenceToBoardTransform")
    mapping = {
        "scaleX": float(mapping_raw.get("scaleX", coordinate["width"] / reference_width)),
        "scaleY": float(mapping_raw.get("scaleY", coordinate["height"] / reference_height)),
        "offsetX": float(mapping_raw.get("offsetX", 0.0)),
        "offsetY": float(mapping_raw.get("offsetY", 0.0)),
    }
    if abs(mapping["scaleX"]) < 1e-12 or abs(mapping["scaleY"]) < 1e-12:
        raise ValueError("referenceToBoardTransform scale must be non-zero")
    safe = require_dict(
        draft.get(
            "safeRegion",
            {"left": 0.0, "top": 0.0, "right": coordinate["width"], "bottom": coordinate["height"]},
        ),
        "safeRegion",
    )
    default_card = require_dict(draft.get("cardBody"), "cardBody")
    default_board_size = [float(default_card["width"]), float(default_card["height"])]
    roi_box = roi["boardRoi"]
    anchors: list[dict[str, Any]] = []
    ids: list[str] = []
    reference_centers: list[tuple[float, float]] = []
    for index, raw in enumerate(require_list(draft.get("anchors"), "anchors")):
        anchor = dict(require_dict(raw, f"anchors[{index}]"))
        anchor_id = require_str(anchor.get("anchorId"), f"anchors[{index}].anchorId")
        ids.append(anchor_id)
        reference_center_raw = anchor.get("referenceCenter")
        board_center_raw = anchor.get("center")
        if reference_center_raw is None and board_center_raw is None:
            raise ValueError(f"{anchor_id}: center or referenceCenter is required")
        if reference_center_raw is None:
            board_center = vector(board_center_raw, f"{anchor_id}.center")[:2]
            reference_center = [
                (board_center[0] - mapping["offsetX"]) / mapping["scaleX"],
                (board_center[1] - mapping["offsetY"]) / mapping["scaleY"],
            ]
        else:
            reference_center = vector(reference_center_raw, f"{anchor_id}.referenceCenter")[:2]
            board_center = [
                reference_center[0] * mapping["scaleX"] + mapping["offsetX"],
                reference_center[1] * mapping["scaleY"] + mapping["offsetY"],
            ]
            if board_center_raw is not None:
                declared = vector(board_center_raw, f"{anchor_id}.center")[:2]
                if abs(declared[0] - board_center[0]) > 0.5 or abs(declared[1] - board_center[1]) > 0.5:
                    raise ValueError(f"{anchor_id}: center disagrees with referenceCenter transform")
        if not (
            float(roi_box["left"]) <= reference_center[0] <= float(roi_box["right"])
            and float(roi_box["top"]) <= reference_center[1] <= float(roi_box["bottom"])
        ):
            raise ValueError(f"{anchor_id}: referenceCenter is outside locked board ROI")
        reference_centers.append((round(reference_center[0], 4), round(reference_center[1], 4)))
        board_size = vector(anchor.get("size", default_board_size), f"{anchor_id}.size")[:2]
        reference_size = vector(
            anchor.get(
                "referenceSize",
                [board_size[0] / abs(mapping["scaleX"]), board_size[1] / abs(mapping["scaleY"])],
            ),
            f"{anchor_id}.referenceSize",
        )[:2]
        anchor.update({
            "center": board_center,
            "size": board_size,
            "referenceCenter": reference_center,
            "referenceSize": reference_size,
        })
        anchors.append(anchor)
    unique(ids, "anchor IDs")
    if len(set(reference_centers)) != len(reference_centers):
        raise ValueError("Visible anchors must not share an exact reference center; hidden capacity belongs in capacity-plan")
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "visible-layout",
        "createdAt": now_iso(),
        "referenceRoi": path_state(roi_path),
        "referenceImage": roi["referenceImage"],
        "referenceCoordinateSystem": {"space": "reference-image", "width": reference_width, "height": reference_height},
        "coordinateSystem": coordinate,
        "referenceToBoardTransform": mapping,
        "safeRegion": safe,
        "cardBody": default_card,
        "grammar": require_dict(draft.get("grammar"), "grammar"),
        "anchors": anchors,
        "topSurfaceAnchorCount": len(anchors),
        "silhouette": draft.get("silhouette", []),
        "holes": draft.get("holes", []),
        "proposerReview": require_dict(draft.get("proposerReview"), "proposerReview"),
        "reviewerReview": require_dict(draft.get("reviewerReview"), "reviewerReview"),
        "safety": {
            "referenceSourceAepUsed": False,
            "referenceSourceGeometryUsed": False,
            "hiddenCapacityAuthored": False,
        },
    }
    validate_visible_layout(result)
    write_json(output_path, result)
    if overlay_path is not None:
        reference_image = Path(str(roi["referenceImage"]["path"]))
        _draw_anchor_overlay(reference_image, result, overlay_path)
    return result


def _validate_acyclic(anchor_ids: set[str], edges: list[dict[str, Any]]) -> None:
    graph: dict[str, list[str]] = defaultdict(list)
    indegree = {anchor_id: 0 for anchor_id in anchor_ids}
    for edge in edges:
        front = str(edge["frontAnchorId"])
        back = str(edge["backAnchorId"])
        if front not in anchor_ids or back not in anchor_ids:
            raise ValueError(f"Occlusion edge refers to unknown anchor: {front}->{back}")
        graph[front].append(back)
        indegree[back] += 1
    queue = deque(sorted(anchor_id for anchor_id, degree in indegree.items() if degree == 0))
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for child in graph[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(anchor_ids):
        raise ValueError("Occlusion edges contain a cycle")


def lock_depth_evidence(visible_layout_path: Path, draft_path: Path, output_path: Path) -> dict[str, Any]:
    visible = read_json(visible_layout_path)
    validate_visible_layout(visible)
    draft = read_json(draft_path)
    hints = require_list(draft.get("anchorDepthHints"), "anchorDepthHints")
    edges = require_list(draft.get("occlusionEdges", []), "occlusionEdges")
    anchor_ids = {str(row["anchorId"]) for row in visible["anchors"]}
    hinted = {str(require_dict(row, "anchorDepthHints[]").get("anchorId")) for row in hints}
    missing_hints = sorted(anchor_ids - hinted)
    unknown_hints = sorted(hinted - anchor_ids)
    if missing_hints:
        raise ValueError(f"Every visible anchor requires a depth hint, missing: {missing_hints[:20]}")
    if unknown_hints:
        raise ValueError(f"Depth hints refer to unknown anchors: {unknown_hints[:20]}")
    _validate_acyclic(anchor_ids, [require_dict(row, "occlusionEdges[]") for row in edges])
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "observed-depth",
        "createdAt": now_iso(),
        "visibleLayout": path_state(visible_layout_path),
        "visibleLayoutSha256": sha256_file(visible_layout_path),
        "anchorDepthHints": hints,
        "occlusionEdges": edges,
        "review": require_dict(draft.get("review"), "review"),
    }
    validate_depth_evidence(result)
    write_json(output_path, result)
    return result
