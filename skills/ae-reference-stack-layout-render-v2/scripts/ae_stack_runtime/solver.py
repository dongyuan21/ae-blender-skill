from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

from .common import (
    SCHEMA_VERSION,
    now_iso,
    overlap_metrics,
    read_json,
    rect_from_center,
    sha256_file,
    sha256_json,
    vector,
)
from .contracts import validate_assignment, validate_capacity, validate_event_model
from .simulation import simulate_mapping


FORBIDDEN_ASSIGNMENT_FIELDS = {
    "zOrder",
    "renderOrder",
    "activeStart",
    "activeEnd",
    "clickTime",
    "clickOrdinal",
    "targetPosition",
}


def _slot_graph(capacity: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, int]]:
    slots = capacity["slots"]
    rectangles = {
        str(slot["slotId"]): rect_from_center(
            vector(slot["center"], "slot.center")[:2],
            vector(slot["size"], "slot.size")[:2],
        )
        for slot in slots
    }
    threshold = float(capacity.get("overlapThreshold", 0.001))
    graph: dict[str, set[str]] = {slot_id: set() for slot_id in rectangles}
    ids = list(rectangles)
    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            area, ratio = overlap_metrics(rectangles[first], rectangles[second])
            if area > 0 and ratio >= threshold:
                graph[first].add(second)
                graph[second].add(first)
    return graph, {slot_id: len(neighbors) for slot_id, neighbors in graph.items()}


def _tile_risk(tiles: list[dict[str, Any]]) -> dict[str, float]:
    selected = [tile for tile in tiles if tile.get("clickTime") is not None]
    maximum_ordinal = max((int(tile["clickOrdinal"]) for tile in selected), default=0)
    result: dict[str, float] = {}
    for tile in tiles:
        tile_id = str(tile["tileId"])
        vulnerability = 0
        if tile.get("clickTime") is not None:
            click = float(tile["clickTime"])
            vulnerability = sum(
                1
                for other in tiles
                if other["tileId"] != tile_id
                and int(other["renderOrder"]) < int(tile["renderOrder"])
                and float(other["activeStart"]) <= click < float(other["activeEnd"])
            )
        blocker_potential = sum(
            1
            for target in selected
            if target["tileId"] != tile_id
            and int(tile["renderOrder"]) < int(target["renderOrder"])
            and float(tile["activeStart"]) <= float(target["clickTime"]) < float(tile["activeEnd"])
        )
        early_weight = (
            maximum_ordinal - int(tile["clickOrdinal"]) + 1
            if tile.get("clickOrdinal") is not None
            else 0
        )
        result[tile_id] = vulnerability * 8.0 + blocker_potential * 5.0 + early_weight * 0.2
    return result


def _constraints(constraints: dict[str, Any]) -> tuple[dict[str, str], dict[str, set[str]], set[tuple[str, str]]]:
    fixed: dict[str, str] = {}
    allowed: dict[str, set[str]] = {}
    forbidden: set[tuple[str, str]] = set()
    for index, row in enumerate(constraints.get("fixedAssignments", [])):
        if not isinstance(row, dict):
            raise ValueError(f"fixedAssignments[{index}] must be an object")
        tile_id = str(row["tileId"])
        slot_id = str(row["slotId"])
        if tile_id in fixed:
            raise ValueError(f"Duplicate fixed assignment for {tile_id}")
        fixed[tile_id] = slot_id
    for index, row in enumerate(constraints.get("allowedSlots", [])):
        if not isinstance(row, dict):
            raise ValueError(f"allowedSlots[{index}] must be an object")
        tile_id = str(row["tileId"])
        allowed[tile_id] = {str(value) for value in row.get("slotIds", [])}
        if not allowed[tile_id]:
            raise ValueError(f"allowedSlots[{index}].slotIds must not be empty")
    for index, row in enumerate(constraints.get("forbiddenAssignments", [])):
        if not isinstance(row, dict):
            raise ValueError(f"forbiddenAssignments[{index}] must be an object")
        forbidden.add((str(row["tileId"]), str(row["slotId"])))
    return fixed, allowed, forbidden


def _soft_cost(
    tile: dict[str, Any],
    slot: dict[str, Any],
    *,
    degree: int,
    risk: float,
    max_render_order: int,
    max_depth: int,
    card_diagonal: float,
    weights: dict[str, float],
) -> float:
    original = vector(tile["originalPosition"], "tile.originalPosition")[:2]
    center = vector(slot["center"], "slot.center")[:2]
    movement = math.hypot(center[0] - original[0], center[1] - original[1]) / max(card_diagonal, 1.0)
    render_rank = (int(tile["renderOrder"]) - 1) / max(max_render_order - 1, 1)
    depth_rank = int(slot["depthIndex"]) / max(max_depth, 1)
    depth_mismatch = abs(render_rank - depth_rank)
    congestion = risk * degree
    synthesized_penalty = 1.0 if slot.get("provenance") == "synthesized-for-surplus" else 0.0
    return (
        weights["movement"] * movement
        + weights["depth"] * depth_mismatch
        + weights["risk"] * congestion
        + weights["synthesized"] * synthesized_penalty
    )


def _initial_assignment(
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    constraints: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    tiles = list(event_model["tiles"])
    slots = list(capacity["slots"])
    tile_map = {str(tile["tileId"]): tile for tile in tiles}
    slot_map = {str(slot["slotId"]): slot for slot in slots}
    fixed, allowed, forbidden = _constraints(constraints)
    if set(fixed) - set(tile_map):
        raise ValueError(f"Fixed assignments reference unknown tiles: {sorted(set(fixed) - set(tile_map))}")
    if set(fixed.values()) - set(slot_map):
        raise ValueError(f"Fixed assignments reference unknown slots: {sorted(set(fixed.values()) - set(slot_map))}")
    if len(set(fixed.values())) != len(fixed):
        raise ValueError("Fixed assignments use the same slot more than once")

    graph, degrees = _slot_graph(capacity)
    risks = _tile_risk(tiles)
    remaining_tiles = [tile for tile in tiles if tile["tileId"] not in fixed]
    remaining_slots = [slot for slot in slots if slot["slotId"] not in set(fixed.values())]
    if len(remaining_tiles) != len(remaining_slots):
        raise ValueError("Tile/slot counts do not match after fixed assignments")

    all_sizes = [vector(slot["size"], "slot.size")[:2] for slot in slots]
    card_diagonal = sum(math.hypot(size[0], size[1]) for size in all_sizes) / max(len(all_sizes), 1)
    max_render = max(int(tile["renderOrder"]) for tile in tiles)
    max_depth = max(int(slot["depthIndex"]) for slot in slots)
    weights = {
        "movement": float(constraints.get("movementWeight", 1.0)),
        "depth": float(constraints.get("depthWeight", 8.0)),
        "risk": float(constraints.get("riskWeight", 12.0)),
        "synthesized": float(constraints.get("synthesizedSlotWeight", 0.2)),
    }

    matrix: list[list[float]] = []
    impossible = 1e15
    for tile in remaining_tiles:
        row: list[float] = []
        tile_id = str(tile["tileId"])
        for slot in remaining_slots:
            slot_id = str(slot["slotId"])
            if tile_id in allowed and slot_id not in allowed[tile_id]:
                row.append(impossible)
                continue
            if (tile_id, slot_id) in forbidden:
                row.append(impossible)
                continue
            row.append(
                _soft_cost(
                    tile,
                    slot,
                    degree=degrees[slot_id],
                    risk=risks[tile_id],
                    max_render_order=max_render,
                    max_depth=max_depth,
                    card_diagonal=card_diagonal,
                    weights=weights,
                )
            )
        matrix.append(row)

    mapping = dict(fixed)
    algorithm = "greedy-risk-degree"
    try:
        import numpy as np  # type: ignore
        from scipy.optimize import linear_sum_assignment  # type: ignore

        costs = np.asarray(matrix, dtype=float)
        row_ids, column_ids = linear_sum_assignment(costs)
        if any(costs[row, column] >= impossible / 2 for row, column in zip(row_ids, column_ids)):
            raise ValueError("Assignment constraints make at least one tile impossible to place")
        for row, column in zip(row_ids, column_ids):
            mapping[str(remaining_tiles[int(row)]["tileId"])] = str(remaining_slots[int(column)]["slotId"])
        algorithm = "scipy-hungarian-plus-min-conflicts"
    except (ImportError, ModuleNotFoundError):
        # Deterministic fallback: highest-risk tiles receive the lowest-cost
        # currently available slot.
        order = sorted(
            range(len(remaining_tiles)),
            key=lambda index: (-risks[str(remaining_tiles[index]["tileId"])], int(remaining_tiles[index]["renderOrder"])),
        )
        available = set(range(len(remaining_slots)))
        for row_index in order:
            candidates = sorted(available, key=lambda column: (matrix[row_index][column], column))
            if not candidates or matrix[row_index][candidates[0]] >= impossible / 2:
                raise ValueError("Assignment constraints make at least one tile impossible to place")
            column = candidates[0]
            available.remove(column)
            mapping[str(remaining_tiles[row_index]["tileId"])] = str(remaining_slots[column]["slotId"])

    return mapping, {
        "initialAlgorithm": algorithm,
        "slotDegrees": degrees,
        "tileRisks": risks,
        "weights": weights,
        "cardDiagonal": card_diagonal,
        "allowedSlots": {key: sorted(value) for key, value in allowed.items()},
        "forbiddenAssignmentCount": len(forbidden),
        "fixedAssignmentCount": len(fixed),
    }


def _assignment_artifact(mapping: dict[str, str]) -> dict[str, Any]:
    return {
        "assignments": [
            {"tileId": tile_id, "slotId": slot_id}
            for tile_id, slot_id in sorted(mapping.items())
        ]
    }


def _soft_mapping_cost(
    mapping: dict[str, str],
    event_model: dict[str, Any],
    capacity: dict[str, Any],
) -> float:
    tile_map = {str(tile["tileId"]): tile for tile in event_model["tiles"]}
    slot_map = {str(slot["slotId"]): slot for slot in capacity["slots"]}
    total = 0.0
    for tile_id, slot_id in mapping.items():
        original = vector(tile_map[tile_id]["originalPosition"], "originalPosition")[:2]
        center = vector(slot_map[slot_id]["center"], "slot.center")[:2]
        total += math.hypot(center[0] - original[0], center[1] - original[1])
    return total


def _objective(
    mapping: dict[str, str],
    event_model: dict[str, Any],
    capacity: dict[str, Any],
) -> tuple[int, int, int, float, dict[str, Any]]:
    diagnostics = simulate_mapping(event_model, capacity, _assignment_artifact(mapping))
    return (
        int(diagnostics["blockedClickCount"]),
        int(diagnostics["occlusionOrderViolationCount"]),
        int(diagnostics["blockingOrderViolationCount"]),
        _soft_mapping_cost(mapping, event_model, capacity),
        diagnostics,
    )


def _local_repair(
    mapping: dict[str, str],
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    constraints: dict[str, Any],
    initial_info: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    fixed = {str(row["tileId"]) for row in constraints.get("fixedAssignments", []) if isinstance(row, dict)}
    allowed = {str(row["tileId"]): {str(value) for value in row.get("slotIds", [])} for row in constraints.get("allowedSlots", []) if isinstance(row, dict)}
    forbidden = {(str(row["tileId"]), str(row["slotId"])) for row in constraints.get("forbiddenAssignments", []) if isinstance(row, dict)}
    degrees: dict[str, int] = initial_info["slotDegrees"]
    randomizer = random.Random(int(constraints.get("seed", 0)))
    max_iterations = int(constraints.get("maxRepairIterations", 200))
    candidate_limit = int(constraints.get("candidateSwapLimit", 80))
    random_swap_samples = int(constraints.get("randomSwapSamples", 120))

    def allowed_swap(first: str, second: str) -> bool:
        first_slot = mapping[second]
        second_slot = mapping[first]
        if first in fixed or second in fixed:
            return False
        if first in allowed and first_slot not in allowed[first]:
            return False
        if second in allowed and second_slot not in allowed[second]:
            return False
        if (first, first_slot) in forbidden or (second, second_slot) in forbidden:
            return False
        return True

    best = dict(mapping)
    best_objective = _objective(best, event_model, capacity)
    history: list[dict[str, Any]] = [{
        "iteration": 0,
        "blockedClickCount": best_objective[0],
        "occlusionOrderViolationCount": best_objective[1],
        "blockingOrderViolationCount": best_objective[2],
        "movementCost": round(best_objective[3], 4),
    }]
    if best_objective[0] == 0 and best_objective[1] == 0:
        return best, {"iterations": 0, "history": history, "termination": "initial-assignment-passed"}

    tile_ids = sorted(mapping)
    no_improvement_rounds = 0
    for iteration in range(1, max_iterations + 1):
        diagnostics = best_objective[4]
        involved: list[str] = []
        for blocked in diagnostics.get("blockedClicks", []):
            involved.append(str(blocked["tileId"]))
            involved.extend(str(row["tileId"]) for row in blocked.get("blockers", []))
        involved = list(dict.fromkeys(involved))
        low_degree_tiles = sorted(tile_ids, key=lambda tile_id: (degrees[best[tile_id]], tile_id))[:candidate_limit]
        candidates: set[tuple[str, str]] = set()
        for first in involved:
            for second in low_degree_tiles:
                if first != second:
                    candidates.add(tuple(sorted((first, second))))
        # Deterministic random samples help leave a local arrangement where a
        # blocker must move together with an unrelated tile.
        for _ in range(random_swap_samples):
            first, second = randomizer.sample(tile_ids, 2)
            candidates.add(tuple(sorted((first, second))))

        candidate_best: tuple[int, int, int, float, dict[str, Any]] | None = None
        candidate_pair: tuple[str, str] | None = None
        for first, second in sorted(candidates):
            if not allowed_swap(first, second):
                continue
            trial = dict(best)
            trial[first], trial[second] = trial[second], trial[first]
            objective = _objective(trial, event_model, capacity)
            if candidate_best is None or objective[:4] < candidate_best[:4]:
                candidate_best = objective
                candidate_pair = (first, second)

        if candidate_best is None or candidate_pair is None or candidate_best[:4] >= best_objective[:4]:
            no_improvement_rounds += 1
            if no_improvement_rounds >= int(constraints.get("maxNoImprovementRounds", 2)):
                break
            continue
        first, second = candidate_pair
        best[first], best[second] = best[second], best[first]
        best_objective = candidate_best
        no_improvement_rounds = 0
        history.append({
            "iteration": iteration,
            "swap": [first, second],
            "blockedClickCount": best_objective[0],
            "occlusionOrderViolationCount": best_objective[1],
            "blockingOrderViolationCount": best_objective[2],
            "movementCost": round(best_objective[3], 4),
        })
        if best_objective[0] == 0 and best_objective[1] == 0:
            return best, {"iterations": iteration, "history": history, "termination": "zero-hard-violation-solution"}

    return best, {
        "iterations": history[-1]["iteration"],
        "history": history,
        "termination": "no-improving-swap",
    }


def solve_assignment(
    event_model: dict[str, Any],
    capacity: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    *,
    event_model_path: Path | None = None,
    capacity_path: Path | None = None,
    constraints_path: Path | None = None,
) -> dict[str, Any]:
    validate_event_model(event_model)
    validate_capacity(capacity)
    if event_model["sourceFactsSha256"] != capacity["sourceFactsSha256"]:
        raise ValueError("Capacity plan was built from a different source-event-model")
    constraints = constraints or {}
    mapping, initial_info = _initial_assignment(event_model, capacity, constraints)
    repaired, repair_info = _local_repair(mapping, event_model, capacity, constraints, initial_info)
    diagnostics = simulate_mapping(event_model, capacity, _assignment_artifact(repaired))
    status = "solved" if all(
        diagnostics[key] == 0
        for key in (
            "blockedClickCount",
            "occlusionOrderViolationCount",
            "identityErrorCount",
            "boundsErrorCount",
            "matchErrorCount",
        )
    ) else "needs_revision"
    rows = [{"tileId": tile_id, "slotId": slot_id} for tile_id, slot_id in sorted(repaired.items())]
    for row in rows:
        if FORBIDDEN_ASSIGNMENT_FIELDS.intersection(row):
            raise AssertionError("Solver leaked source facts into assignment rows")
    capacity_hash = sha256_file(capacity_path) if capacity_path else sha256_json(capacity)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "assignment",
        "createdAt": now_iso(),
        "status": status,
        "sourceFactsSha256": event_model["sourceFactsSha256"],
        "capacityPlanSha256": capacity_hash,
        "constraintsSha256": sha256_file(constraints_path) if constraints_path else sha256_json(constraints),
        "assignmentCount": len(rows),
        "assignments": rows,
        "solver": {
            **initial_info,
            **repair_info,
            "deterministicSeed": int(constraints.get("seed", 0)),
            "sourceFactsWritable": False,
        },
        "diagnostics": diagnostics,
        "nextAction": None if status == "solved" else {
            "retryFrom": "CAPACITY_RECONCILED"
            if diagnostics["blockedClickCount"] > 0 or diagnostics["occlusionOrderViolationCount"] > 0
            else "ASSIGNMENT_SOLVED",
            "reason": "No assignment satisfying accessibility, visible occlusion order, identity, and bounds was found",
        },
    }
    if status == "solved":
        validate_assignment(result)
    return result


def solve_assignment_from_files(
    event_model_path: Path,
    capacity_path: Path,
    constraints_path: Path | None = None,
) -> dict[str, Any]:
    return solve_assignment(
        read_json(event_model_path),
        read_json(capacity_path),
        read_json(constraints_path) if constraints_path else {},
        event_model_path=event_model_path,
        capacity_path=capacity_path,
        constraints_path=constraints_path,
    )
