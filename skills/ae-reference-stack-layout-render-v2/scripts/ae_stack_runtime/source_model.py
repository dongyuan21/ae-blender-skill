from __future__ import annotations

from pathlib import Path
from typing import Any

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
    sha256_json,
    unique,
    vector,
    write_json,
)
from .contracts import validate_board_inventory, validate_event_model
from .facts import event_facts_sha256


def _all_layers(inspection: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    comp_id_default = int(require_dict(inspection.get("comp"), "inspection.comp")["id"])
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for key in ("tileLayers", "moverLayers", "handLayers", "otherAnimatedLayers", "allLayers"):
        for raw in inspection.get(key, []) or []:
            if not isinstance(raw, dict):
                continue
            comp_id = int(raw.get("compId", comp_id_default))
            layer_index = int(raw["index"])
            result[(comp_id, layer_index)] = raw
    return result


def _position_snapshot(layer: dict[str, Any]) -> dict[str, Any]:
    transform = require_dict(layer.get("transform"), f"layer {layer.get('index')}.transform")
    return require_dict(transform.get("position"), f"layer {layer.get('index')}.transform.position")


def _scale_snapshot(layer: dict[str, Any]) -> dict[str, Any] | None:
    transform = layer.get("transform") or {}
    value = transform.get("scale")
    return value if isinstance(value, dict) else None


def _key_value(snapshot: dict[str, Any], key_number: int, label: str) -> list[float]:
    for row in snapshot.get("keys", []) or []:
        if int(row.get("keyNumber")) == key_number:
            return vector(row.get("value"), label)
    raise ValueError(f"{label}: key {key_number} is missing")


def _settled_position(layer: dict[str, Any], decision: dict[str, Any]) -> tuple[list[float], int | None]:
    snapshot = _position_snapshot(layer)
    key_count = int(snapshot.get("numKeys", 0))
    if key_count:
        key_number = require_int(decision.get("settledPositionKey"), f"layer {layer['index']}.settledPositionKey")
        if not 1 <= key_number <= key_count:
            raise ValueError(f"layer {layer['index']}: settledPositionKey outside 1..{key_count}")
        return _key_value(snapshot, key_number, "settled position"), key_number
    return vector(snapshot.get("value"), "position value"), None


def _settled_scale(layer: dict[str, Any], decision: dict[str, Any]) -> tuple[list[float] | None, int | None]:
    snapshot = _scale_snapshot(layer)
    if snapshot is None:
        return None, None
    key_count = int(snapshot.get("numKeys", 0))
    if key_count:
        raw = decision.get("settledScaleKey")
        if raw is None:
            return None, None
        key_number = require_int(raw, f"layer {layer['index']}.settledScaleKey")
        return _key_value(snapshot, key_number, "settled scale"), key_number
    value = snapshot.get("value")
    return (vector(value, "scale value") if value is not None else None), None


def _card_size(layer: dict[str, Any], decision: dict[str, Any], scale: list[float] | None) -> tuple[list[float], str]:
    if decision.get("cardSize") is not None:
        size = vector(decision["cardSize"], "decision.cardSize")[:2]
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError("cardSize must be positive")
        return size, "measured-or-authored"
    width = layer.get("sourceWidth")
    height = layer.get("sourceHeight")
    if width is None or height is None or scale is None:
        raise ValueError(
            f"layer {layer.get('index')}: cardSize is required because source dimensions or settled scale are unavailable"
        )
    size = [float(width) * abs(scale[0]) / 100.0, float(height) * abs(scale[1]) / 100.0]
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"layer {layer.get('index')}: derived card size is invalid")
    return size, "source-dimensions-times-settled-scale"


def _layer_fingerprint(layer: dict[str, Any]) -> dict[str, Any]:
    position = _position_snapshot(layer)
    scale = _scale_snapshot(layer)
    return {
        "compId": int(layer["compId"]),
        "layerIndex": int(layer["index"]),
        "layerName": str(layer["name"]),
        "sourceId": layer.get("sourceId"),
        "sourceName": layer.get("sourceName"),
        "positionKeyCount": int(position.get("numKeys", 0)),
        "scaleKeyCount": int(scale.get("numKeys", 0)) if scale else None,
        "inPoint": float(layer.get("inPoint", 0.0)),
        "outPoint": float(layer.get("outPoint", 0.0)),
        "parentIndex": layer.get("parentIndex"),
        "hasTrackMatte": bool(layer.get("hasTrackMatte", False)),
        "threeDLayer": bool(layer.get("threeDLayer", False)),
    }


def build_board_inventory_data(inspection: dict[str, Any], draft: dict[str, Any], inspection_path: Path) -> dict[str, Any]:
    comp = require_dict(inspection.get("comp"), "inspection.comp")
    board_comp_id = require_int(draft.get("boardCompId", comp.get("id")), "boardCompId")
    if board_comp_id != int(comp.get("id")):
        raise ValueError("draft.boardCompId must match inspection.comp.id")
    candidate_mode = str(draft.get("candidateMode", "tileLayers"))
    if candidate_mode not in {"tileLayers", "allLayers"}:
        raise ValueError("candidateMode must be tileLayers or allLayers")
    candidates_raw = inspection.get(candidate_mode) or []
    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    for raw in candidates_raw:
        layer = require_dict(raw, f"inspection.{candidate_mode}[]")
        key = (int(layer.get("compId", board_comp_id)), int(layer["index"]))
        candidates[key] = layer
    if not candidates:
        raise ValueError(f"inspection.{candidate_mode} contains no candidates")

    decisions = require_list(draft.get("decisions"), "decisions")
    decision_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for index, raw in enumerate(decisions):
        decision = require_dict(raw, f"decisions[{index}]")
        key = (
            require_int(decision.get("compId", board_comp_id), f"decisions[{index}].compId"),
            require_int(decision.get("layerIndex"), f"decisions[{index}].layerIndex"),
        )
        if key in decision_by_key:
            raise ValueError(f"Duplicate decision for layer {key}")
        decision_by_key[key] = decision
    unclassified = sorted(set(candidates) - set(decision_by_key))
    unknown = sorted(set(decision_by_key) - set(candidates))
    if unknown:
        raise ValueError(f"Decisions refer to non-candidate layers: {unknown[:20]}")

    tiles: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for key in sorted(candidates, key=lambda row: row[1]):
        layer = candidates[key]
        decision = decision_by_key.get(key)
        if decision is None:
            continue
        include = decision.get("include")
        if include is not True and include is not False:
            raise ValueError(f"Layer {key}: include must be true or false")
        expected_name = decision.get("expectedLayerName")
        if expected_name is not None and str(layer.get("name")) != str(expected_name):
            raise ValueError(f"Layer {key}: name mismatch {layer.get('name')!r} != {expected_name!r}")
        expected_source = decision.get("expectedSourceId")
        if expected_source is not None and int(layer.get("sourceId")) != int(expected_source):
            raise ValueError(f"Layer {key}: sourceId mismatch")
        if include is False:
            exclusions.append({
                "compId": key[0],
                "layerIndex": key[1],
                "layerName": str(layer.get("name")),
                "sourceId": layer.get("sourceId"),
                "enabled": bool(layer.get("enabled", False)),
                "reason": require_str(decision.get("reason"), f"layer {key}.reason"),
            })
            continue
        if layer.get("enabled") is not True and not decision.get("includeDisabledJustification"):
            raise ValueError(f"Layer {key} is disabled; includeDisabledJustification is required")
        position, settled_position_key = _settled_position(layer, decision)
        scale, settled_scale_key = _settled_scale(layer, decision)
        card_size, size_provenance = _card_size(layer, decision, scale)
        tile_id = str(decision.get("tileId") or f"c{key[0]}-l{key[1]}-s{layer.get('sourceId', 'none')}")
        fingerprint = _layer_fingerprint(layer)
        tiles.append({
            "tileId": tile_id,
            "compId": key[0],
            "layerIndex": key[1],
            "layerName": str(layer.get("name")),
            "sourceId": layer.get("sourceId"),
            "sourceName": layer.get("sourceName"),
            "faceId": str(decision.get("faceId") or f"source:{layer.get('sourceId') or layer.get('sourceName') or tile_id}"),
            "enabled": bool(layer.get("enabled", False)),
            "renderOrder": key[1],
            "inPoint": float(layer.get("inPoint", 0.0)),
            "outPoint": float(layer.get("outPoint", 0.0)),
            "startTime": float(layer.get("startTime", 0.0)),
            "originalPosition": position,
            "settledPositionKey": settled_position_key,
            "originalScale": scale,
            "settledScaleKey": settled_scale_key,
            "cardSize": card_size,
            "cardSizeProvenance": size_provenance,
            "sourceBandId": decision.get("sourceBandId"),
            "parentIndex": layer.get("parentIndex"),
            "hasTrackMatte": bool(layer.get("hasTrackMatte", False)),
            "threeDLayer": bool(layer.get("threeDLayer", False)),
            "layerFingerprint": fingerprint,
            "layerFingerprintSha256": sha256_json(fingerprint),
        })

    unique([tile["tileId"] for tile in tiles], "tile IDs")
    if not tiles:
        raise ValueError("No board tiles were included")
    review = require_dict(draft.get("review"), "review")
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "board-inventory",
        "createdAt": now_iso(),
        "boardCompId": board_comp_id,
        "boardComp": {
            "id": board_comp_id,
            "name": comp.get("name"),
            "width": comp.get("width"),
            "height": comp.get("height"),
            "duration": comp.get("duration"),
            "frameRate": comp.get("frameRate"),
        },
        "candidateMode": candidate_mode,
        "candidateCount": len(candidates),
        "includedTileCount": len(tiles),
        "excludedCandidateCount": len(exclusions),
        "tiles": tiles,
        "excludedCandidates": exclusions,
        "unclassifiedCandidates": [
            {"compId": comp_id, "layerIndex": layer_index}
            for comp_id, layer_index in unclassified
        ],
        "inspection": path_state(inspection_path),
        "review": review,
    }
    validate_board_inventory(result)
    return result


def build_board_inventory(inspection_path: Path, draft_path: Path, output_path: Path) -> dict[str, Any]:
    inspection = read_json(inspection_path)
    draft = read_json(draft_path)
    result = build_board_inventory_data(inspection, draft, inspection_path)
    write_json(output_path, result)
    return result


def _lookup_layer(layers: dict[tuple[int, int], dict[str, Any]], comp_id: int, layer_index: int, label: str) -> dict[str, Any]:
    layer = layers.get((comp_id, layer_index))
    if layer is None:
        raise ValueError(f"{label} layer is missing from inspection: {comp_id}/{layer_index}")
    return layer


def _validate_hand_binding(
    binding: dict[str, Any],
    layers: dict[tuple[int, int], dict[str, Any]],
    comp_id: int,
    tile_position: list[float],
) -> dict[str, Any]:
    layer_index = require_int(binding.get("layerIndex"), "handBinding.layerIndex")
    layer = _lookup_layer(layers, comp_id, layer_index, "hand")
    position = _position_snapshot(layer)
    key_number = require_int(binding.get("keyNumber"), "handBinding.keyNumber")
    old_value = _key_value(position, key_number, "hand key")
    if binding.get("offset") is not None:
        offset = vector(binding["offset"], "handBinding.offset")
    else:
        offset = [old_value[0] - tile_position[0], old_value[1] - tile_position[1]]
    return {
        "compId": comp_id,
        "layerIndex": layer_index,
        "layerName": str(layer.get("name")),
        "keyNumber": key_number,
        "expectedOld": old_value,
        "fingerOffset": offset[:2],
    }


def build_event_model_data(
    inspection: dict[str, Any],
    inventory: dict[str, Any],
    draft: dict[str, Any],
    inspection_path: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    validate_board_inventory(inventory)
    all_layers = _all_layers(inspection)
    events = require_list(draft.get("events", []), "events")
    event_by_tile: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(events):
        event = require_dict(raw, f"events[{index}]")
        tile_id = require_str(event.get("tileId"), f"events[{index}].tileId")
        if tile_id in event_by_tile:
            raise ValueError(f"Duplicate event for tile {tile_id}")
        event_by_tile[tile_id] = event
    inventory_tiles = {str(row["tileId"]): row for row in inventory["tiles"]}
    unknown = sorted(set(event_by_tile) - set(inventory_tiles))
    if unknown:
        raise ValueError(f"Event draft contains unknown tiles: {unknown}")

    result_tiles: list[dict[str, Any]] = []
    click_events: list[dict[str, Any]] = []
    pair_tolerance = float(draft.get("pairTimeTolerance", 0.1))
    removal_tolerance = float(draft.get("removalTimeTolerance", 0.05))
    for tile_id, tile in inventory_tiles.items():
        event = event_by_tile.get(tile_id)
        row = {
            "tileId": tile_id,
            "compId": int(tile["compId"]),
            "layerIndex": int(tile["layerIndex"]),
            "layerName": str(tile["layerName"]),
            "sourceId": tile.get("sourceId"),
            "sourceName": tile.get("sourceName"),
            "faceId": str(tile.get("faceId") or f"source:{tile.get('sourceId')}"),
            "renderOrder": int(tile["layerIndex"]),
            "activeStart": float(tile["inPoint"]),
            "activeEnd": float(tile["outPoint"]),
            "removalTime": float(tile["outPoint"]),
            "originalPosition": vector(tile["originalPosition"], f"{tile_id}.originalPosition"),
            "settledPositionKey": tile.get("settledPositionKey"),
            "originalScale": tile.get("originalScale"),
            "settledScaleKey": tile.get("settledScaleKey"),
            "cardSize": vector(tile["cardSize"], f"{tile_id}.cardSize")[:2],
            "sourceBandId": tile.get("sourceBandId"),
            "layerFingerprintSha256": tile.get("layerFingerprintSha256"),
            "clickOrdinal": None,
            "clickTime": None,
            "matchGroupId": None,
            "moverBinding": None,
            "handBindings": [],
        }
        if event is not None:
            click_time = require_number(event.get("clickTime"), f"{tile_id}.clickTime")
            click_ordinal = require_int(event.get("clickOrdinal"), f"{tile_id}.clickOrdinal")
            if not row["activeStart"] <= click_time < row["activeEnd"]:
                raise ValueError(f"{tile_id}: clickTime is outside source in/out interval")
            declared_removal = event.get("declaredRemovalTime")
            if declared_removal is not None and abs(float(declared_removal) - row["activeEnd"]) > removal_tolerance:
                raise ValueError(
                    f"{tile_id}: declaredRemovalTime {declared_removal} disagrees with locked source outPoint {row['activeEnd']}"
                )
            row["clickTime"] = click_time
            row["clickOrdinal"] = click_ordinal
            row["matchGroupId"] = event.get("matchGroupId")
            if event.get("faceId") is not None and str(event["faceId"]) != row["faceId"]:
                raise ValueError(f"{tile_id}: event faceId would rewrite inventory identity")
            mover_index = event.get("moverLayerIndex")
            if mover_index is not None:
                mover_index = require_int(mover_index, f"{tile_id}.moverLayerIndex")
                mover = _lookup_layer(all_layers, row["compId"], mover_index, "mover")
                if mover.get("sourceId") != row["sourceId"]:
                    raise ValueError(f"{tile_id}: mover sourceId does not match static tile sourceId")
                time_delta = float(mover.get("inPoint", 0.0)) - row["activeEnd"]
                if abs(time_delta) > pair_tolerance and not event.get("pairingOverrideJustification"):
                    raise ValueError(
                        f"{tile_id}: mover inPoint differs from static outPoint by {time_delta:.6f}; "
                        "pairingOverrideJustification is required"
                    )
                row["moverBinding"] = {
                    "compId": row["compId"],
                    "layerIndex": mover_index,
                    "layerName": str(mover.get("name")),
                    "sourceId": mover.get("sourceId"),
                    "startKey": require_int(event.get("moverStartKey", 1), f"{tile_id}.moverStartKey"),
                    "timeDelta": time_delta,
                    "pairingConfidence": float(event.get("pairingConfidence", 1.0)),
                    "pairingOverrideJustification": event.get("pairingOverrideJustification"),
                }
            hand_rows = require_list(event.get("handBindings", []), f"{tile_id}.handBindings")
            row["handBindings"] = [
                _validate_hand_binding(require_dict(item, f"{tile_id}.handBindings[]"), all_layers, row["compId"], row["originalPosition"])
                for item in hand_rows
            ]
            click_events.append({
                "ordinal": click_ordinal,
                "tileId": tile_id,
                "time": click_time,
                "removalTime": row["activeEnd"],
                "faceId": row["faceId"],
                "matchGroupId": row["matchGroupId"],
            })
        result_tiles.append(row)

    unique([str(row["clickOrdinal"]) for row in result_tiles if row["clickOrdinal"] is not None], "click ordinals")
    click_events.sort(key=lambda row: (int(row["ordinal"]), float(row["time"])))
    if draft.get("requireContiguousOrdinals", True) and click_events:
        ordinals = [int(row["ordinal"]) for row in click_events]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError(f"click ordinals must be contiguous 1..N, got {ordinals}")
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "source-event-model",
        "createdAt": now_iso(),
        "boardCompId": inventory["boardCompId"],
        "boardComp": inventory.get("boardComp"),
        "factsLocked": True,
        "sourceFactsSha256": event_facts_sha256(result_tiles),
        "tileCount": len(result_tiles),
        "eventTileCount": len(click_events),
        "persistentTileCount": len(result_tiles) - len(click_events),
        "matchGroupSize": int(draft["matchGroupSize"]) if draft.get("matchGroupSize") is not None else None,
        "tiles": result_tiles,
        "clickEvents": click_events,
        "inspection": path_state(inspection_path),
        "boardInventory": path_state(inventory_path),
        "review": require_dict(draft.get("review"), "review"),
    }
    validate_event_model(result)
    return result


def build_event_model(
    inspection_path: Path,
    inventory_path: Path,
    draft_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    inspection = read_json(inspection_path)
    inventory = read_json(inventory_path)
    draft = read_json(draft_path)
    result = build_event_model_data(inspection, inventory, draft, inspection_path, inventory_path)
    write_json(output_path, result)
    return result
