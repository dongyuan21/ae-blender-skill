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
    sha256_file,
    standard_safety,
    canonical_json_bytes,
    vector,
    with_xy,
    write_json,
)
from .contracts import validate_assignment, validate_capacity, validate_event_model, validate_property_plan, validate_simulation


def _layer_map(inspection: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}
    default_comp = int(require_dict(inspection.get("comp"), "inspection.comp")["id"])
    for key in ("tileLayers", "moverLayers", "handLayers", "otherAnimatedLayers", "allLayers"):
        for raw in inspection.get(key, []) or []:
            if not isinstance(raw, dict):
                continue
            comp_id = int(raw.get("compId", default_comp))
            result[(comp_id, int(raw["index"]))] = raw
    return result


def _property_snapshot(layer: dict[str, Any], name: str) -> dict[str, Any]:
    transform = require_dict(layer.get("transform"), f"layer {layer.get('index')}.transform")
    snapshot = transform.get(name)
    if not isinstance(snapshot, dict):
        raise ValueError(f"Layer {layer.get('index')} lacks transform.{name}")
    return snapshot


def _key_by_number(snapshot: dict[str, Any], key_number: int) -> dict[str, Any]:
    for raw in snapshot.get("keys", []) or []:
        if int(raw.get("keyNumber")) == int(key_number):
            return require_dict(raw, "property key")
    raise ValueError(f"Key {key_number} is missing")


def _make_update(
    layer: dict[str, Any],
    comp_id: int,
    property_name: str,
    snapshot: dict[str, Any],
    *,
    keys: list[dict[str, Any]] | None = None,
    new_value: list[float] | None = None,
    tolerance: float = 0.5,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "compId": comp_id,
        "layerIndex": int(layer["index"]),
        "layerName": str(layer["name"]),
        "sourceId": layer.get("sourceId"),
        "propertyMatchName": property_name,
        "expectedNumKeys": int(snapshot.get("numKeys", 0)),
    }
    if keys is not None:
        update["keys"] = keys
    else:
        update["expectedValue"] = vector(snapshot.get("value"), f"layer {layer['index']} {property_name} value")
        update["newValue"] = new_value
        update["tolerance"] = tolerance
    return update



def _coalesce_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge updates that target the same AE property and reject ambiguous writes.

    Hand layers commonly serve several click events, so separate tile bindings may
    target distinct keys of one Position property. AE receives one property
    transaction with a single expected key count. Conflicting writes to the same
    key are rejected before any JSX is authorized.
    """
    merged: dict[tuple[int, int, str], dict[str, Any]] = {}
    order: list[tuple[int, int, str]] = []
    for update in updates:
        key = (int(update["compId"]), int(update["layerIndex"]), str(update["propertyMatchName"]))
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(update)
            if isinstance(update.get("keys"), list):
                merged[key]["keys"] = [dict(row) for row in update["keys"]]
            order.append(key)
            continue
        for identity_key in ("layerName", "sourceId", "expectedNumKeys"):
            if existing.get(identity_key) != update.get(identity_key):
                raise ValueError(f"Conflicting property identity for {key}: {identity_key}")
        existing_keyed = isinstance(existing.get("keys"), list)
        update_keyed = isinstance(update.get("keys"), list)
        if existing_keyed != update_keyed:
            raise ValueError(f"Cannot mix keyed and static writes for {key}")
        if not existing_keyed:
            if canonical_json_bytes(existing) != canonical_json_bytes(update):
                raise ValueError(f"Conflicting duplicate static property write for {key}")
            continue
        by_number = {int(row["keyNumber"]): row for row in existing["keys"]}
        for row in update["keys"]:
            number = int(row["keyNumber"])
            prior = by_number.get(number)
            if prior is not None:
                if canonical_json_bytes(prior) != canonical_json_bytes(row):
                    raise ValueError(f"Conflicting duplicate key write for {key}, key {number}")
                continue
            clone = dict(row)
            existing["keys"].append(clone)
            by_number[number] = clone
        existing["keys"].sort(key=lambda row: int(row["keyNumber"]))
    return [merged[key] for key in order]

def _verify_tile_identity(layer: dict[str, Any], tile: dict[str, Any]) -> None:
    if int(layer.get("index")) != int(tile["layerIndex"]):
        raise ValueError(f"{tile['tileId']}: layer index mismatch")
    if str(layer.get("name")) != str(tile["layerName"]):
        raise ValueError(f"{tile['tileId']}: layer name mismatch")
    if layer.get("sourceId") != tile.get("sourceId"):
        raise ValueError(f"{tile['tileId']}: sourceId mismatch")
    if int(tile["renderOrder"]) != int(tile["layerIndex"]):
        raise ValueError(f"{tile['tileId']}: renderOrder is not locked to layerIndex")


def build_property_plan_data(
    inspection: dict[str, Any],
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    assignment: dict[str, Any],
    simulation: dict[str, Any],
    edit_policy: dict[str, Any],
    inspection_path: Path,
    event_model_path: Path,
    capacity_path: Path,
    assignment_path: Path,
    simulation_path: Path,
) -> dict[str, Any]:
    validate_event_model(event_model)
    validate_capacity(capacity)
    validate_assignment(assignment)
    validate_simulation(simulation)
    if assignment.get("sourceFactsSha256") != event_model.get("sourceFactsSha256"):
        raise ValueError("Assignment source facts do not match event model")
    if assignment.get("capacityPlanSha256") != sha256_file(capacity_path):
        raise ValueError("Assignment capacity hash does not match current capacity plan")
    if simulation.get("sourceFactsSha256") != event_model.get("sourceFactsSha256"):
        raise ValueError("Simulation source facts do not match the current event model")
    if simulation.get("capacityPlanSha256") != sha256_file(capacity_path):
        raise ValueError("Simulation was not run against the current capacity bytes")
    if simulation.get("assignmentSha256") != sha256_file(assignment_path):
        raise ValueError("Simulation was not run against the current assignment bytes")
    layers = _layer_map(inspection)
    tile_by_id = {str(row["tileId"]): require_dict(row, "event_model.tiles[]") for row in event_model["tiles"]}
    slot_by_id = {str(row["slotId"]): require_dict(row, "capacity.slots[]") for row in capacity["slots"]}
    mapping = {str(row["tileId"]): str(row["slotId"]) for row in require_list(assignment["assignments"], "assignments")}
    if set(mapping) != set(tile_by_id) or set(mapping.values()) != set(slot_by_id):
        raise ValueError("Assignment coverage differs from event-model/capacity sets")
    comp_info = require_dict(inspection.get("comp"), "inspection.comp")
    comp_height = float(comp_info.get("height", 0.0))
    if comp_height <= 0:
        raise ValueError("Inspection comp height is missing")
    property_updates: list[dict[str, Any]] = []
    uniform_scale = edit_policy.get("uniformScalePercent")
    if uniform_scale is not None:
        uniform_scale = float(uniform_scale)
        if uniform_scale <= 0:
            raise ValueError("uniformScalePercent must be positive")
    for tile_id in sorted(tile_by_id, key=lambda value: int(tile_by_id[value]["renderOrder"])):
        tile = tile_by_id[tile_id]
        slot = slot_by_id[mapping[tile_id]]
        comp_id = int(tile["compId"])
        layer_index = int(tile["layerIndex"])
        layer = layers.get((comp_id, layer_index))
        if layer is None:
            raise ValueError(f"Inspection lacks tile layer {comp_id}/{layer_index}")
        _verify_tile_identity(layer, tile)
        target = vector(slot["center"], f"{tile_id}.target center")
        position = _property_snapshot(layer, "position")
        key_count = int(position.get("numKeys", 0))
        if key_count:
            settled_number = tile.get("settledPositionKey")
            if settled_number is None:
                raise ValueError(f"{tile_id}: settledPositionKey is required for keyed tile")
            settled_number = int(settled_number)
            settled_old = vector(_key_by_number(position, settled_number)["value"], "settled position")
            delta_x, delta_y = target[0] - settled_old[0], target[1] - settled_old[1]
            key_updates: list[dict[str, Any]] = []
            for raw_key in position.get("keys", []) or []:
                key = require_dict(raw_key, "position key")
                old = vector(key["value"], "position key value")
                if old[1] < -10 or old[1] > comp_height + 10:
                    new = with_xy(old, target[0], old[1])
                else:
                    new = with_xy(old, old[0] + delta_x, old[1] + delta_y)
                key_updates.append({
                    "keyNumber": int(key["keyNumber"]),
                    "expectedOld": old,
                    "newValue": new,
                    "tolerance": 0.5,
                })
            property_updates.append(_make_update(layer, comp_id, "ADBE Position", position, keys=key_updates))
        else:
            old = vector(position.get("value"), "position value")
            property_updates.append(
                _make_update(layer, comp_id, "ADBE Position", position, new_value=with_xy(old, target[0], target[1]))
            )

        if uniform_scale is not None:
            scale = _property_snapshot(layer, "scale")
            scale_key_count = int(scale.get("numKeys", 0))
            if scale_key_count:
                settled_scale_key = tile.get("settledScaleKey")
                if settled_scale_key is None:
                    raise ValueError(f"{tile_id}: settledScaleKey required when uniformScalePercent is used")
                settled_scale = vector(_key_by_number(scale, int(settled_scale_key))["value"], "settled scale")
            else:
                settled_scale = vector(scale.get("value"), "scale value")
            if abs(settled_scale[0]) < 1e-9 or abs(settled_scale[1]) < 1e-9:
                raise ValueError(f"{tile_id}: zero settled scale")
            ratio_x, ratio_y = uniform_scale / settled_scale[0], uniform_scale / settled_scale[1]
            if scale_key_count:
                updates = []
                for raw_key in scale.get("keys", []) or []:
                    key = require_dict(raw_key, "scale key")
                    old = vector(key["value"], "scale key value")
                    new = list(old)
                    new[0], new[1] = old[0] * ratio_x, old[1] * ratio_y
                    updates.append({
                        "keyNumber": int(key["keyNumber"]),
                        "expectedOld": old,
                        "newValue": new,
                        "tolerance": 0.05,
                    })
                property_updates.append(_make_update(layer, comp_id, "ADBE Scale", scale, keys=updates))
            else:
                old = vector(scale.get("value"), "scale value")
                new = list(old)
                new[0], new[1] = uniform_scale, uniform_scale
                property_updates.append(_make_update(layer, comp_id, "ADBE Scale", scale, new_value=new, tolerance=0.05))

        mover_binding = tile.get("moverBinding")
        if isinstance(mover_binding, dict):
            mover_index = int(mover_binding["layerIndex"])
            mover = layers.get((comp_id, mover_index))
            if mover is None:
                raise ValueError(f"Inspection lacks mover {comp_id}/{mover_index}")
            if mover.get("sourceId") != tile.get("sourceId"):
                raise ValueError(f"{tile_id}: mover source mismatch")
            mover_position = _property_snapshot(mover, "position")
            mover_key_number = int(mover_binding.get("startKey", 1))
            old = vector(_key_by_number(mover_position, mover_key_number)["value"], "mover start")
            new = with_xy(old, target[0], target[1])
            property_updates.append(
                _make_update(
                    mover,
                    comp_id,
                    "ADBE Position",
                    mover_position,
                    keys=[{
                        "keyNumber": mover_key_number,
                        "expectedOld": old,
                        "newValue": new,
                        "tolerance": 0.5,
                    }],
                )
            )

        for hand_binding in tile.get("handBindings", []) or []:
            binding = require_dict(hand_binding, f"{tile_id}.handBindings[]")
            hand_index = int(binding["layerIndex"])
            hand = layers.get((comp_id, hand_index))
            if hand is None:
                raise ValueError(f"Inspection lacks hand layer {comp_id}/{hand_index}")
            if str(hand.get("name")) != str(binding.get("layerName")):
                raise ValueError(f"{tile_id}: hand layer name mismatch")
            hand_position = _property_snapshot(hand, "position")
            key_number = int(binding["keyNumber"])
            old = vector(_key_by_number(hand_position, key_number)["value"], "hand position")
            offset = vector(binding["fingerOffset"], "hand fingerOffset")
            new = with_xy(old, target[0] + offset[0], target[1] + offset[1])
            property_updates.append(
                _make_update(
                    hand,
                    comp_id,
                    "ADBE Position",
                    hand_position,
                    keys=[{
                        "keyNumber": key_number,
                        "expectedOld": old,
                        "newValue": new,
                        "tolerance": 0.5,
                    }],
                )
            )

    property_updates = _coalesce_updates(property_updates)

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "property-plan",
        "createdAt": now_iso(),
        "safety": standard_safety(),
        "propertyUpdateCount": len(property_updates),
        "propertyUpdates": property_updates,
        "dependencyLocks": require_list(edit_policy.get("dependencyLocks", []), "dependencyLocks"),
        "requiredDisabledLayers": require_list(edit_policy.get("requiredDisabledLayers", []), "requiredDisabledLayers"),
        "qaBaseline": require_dict(edit_policy.get("qaBaseline", {}), "qaBaseline"),
        "routeScope": require_dict(edit_policy.get("routeScope", {}), "routeScope"),
        "editPolicy": {
            "uniformScaleApplied": uniform_scale is not None,
            "uniformScalePercent": uniform_scale,
        },
        "provenance": {
            "sourceFactsSha256": event_model["sourceFactsSha256"],
            "capacityPlanSha256": sha256_file(capacity_path),
            "assignmentSha256": sha256_file(assignment_path),
            "simulationSha256": sha256_file(simulation_path),
            "inspectionSha256": sha256_file(inspection_path),
        },
        "inputs": {
            "inspection": path_state(inspection_path),
            "eventModel": path_state(event_model_path),
            "capacityPlan": path_state(capacity_path),
            "assignment": path_state(assignment_path),
            "simulation": path_state(simulation_path),
        },
    }
    validate_property_plan(result)
    return result


def build_property_plan(
    inspection_path: Path,
    event_model_path: Path,
    capacity_path: Path,
    assignment_path: Path,
    simulation_path: Path,
    edit_policy_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    result = build_property_plan_data(
        read_json(inspection_path),
        read_json(event_model_path),
        read_json(capacity_path),
        read_json(assignment_path),
        read_json(simulation_path),
        read_json(edit_policy_path),
        inspection_path,
        event_model_path,
        capacity_path,
        assignment_path,
        simulation_path,
    )
    result["editPolicyInput"] = path_state(edit_policy_path)
    write_json(output_path, result)
    return result


def build_property_plan_with_route(
    inspection_path: Path,
    event_model_path: Path,
    capacity_path: Path,
    assignment_path: Path,
    simulation_path: Path,
    source_route_path: Path,
    options_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    from .contracts import validate_source_route

    source_route = read_json(source_route_path)
    validate_source_route(source_route)
    options = read_json(options_path) if options_path is not None else {}
    edit_policy = dict(options)
    edit_policy["routeScope"] = source_route["routeScope"]
    edit_policy["qaBaseline"] = source_route["qaBaseline"]
    edit_policy.setdefault("dependencyLocks", [])
    edit_policy.setdefault("requiredDisabledLayers", [])
    result = build_property_plan_data(
        read_json(inspection_path),
        read_json(event_model_path),
        read_json(capacity_path),
        read_json(assignment_path),
        read_json(simulation_path),
        edit_policy,
        inspection_path,
        event_model_path,
        capacity_path,
        assignment_path,
        simulation_path,
    )
    result["sourceRoute"] = path_state(source_route_path)
    result["options"] = path_state(options_path) if options_path is not None else None
    result["provenance"]["sourceRouteSha256"] = sha256_file(source_route_path)
    write_json(output_path, result)
    return result
