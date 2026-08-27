#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ae_stack_runtime.capacity import build_capacity, render_capacity_overlay
from ae_stack_runtime.common import (
    SCHEMA_VERSION,
    now_iso,
    path_state,
    read_json,
    require_dict,
    sha256_file,
    write_json,
)
from ae_stack_runtime.contracts import NODES, validate_node_artifact, validate_preview_qa
from ae_stack_runtime.property_plan import build_property_plan_with_route
from ae_stack_runtime.qa import route_qa
from ae_stack_runtime.reference_model import (
    analyze_reference,
    lock_depth_evidence,
    lock_reference_roi,
    lock_visible_layout,
)
from ae_stack_runtime.route import lock_source_route
from ae_stack_runtime.run_setup import capability_preflight, init_run
from ae_stack_runtime.simulation import simulate_from_files
from ae_stack_runtime.solver import solve_assignment_from_files
from ae_stack_runtime.source_model import build_board_inventory, build_event_model
from ae_stack_runtime.state import StateStore
from ae_stack_runtime.video import validate_full_render
from ae_stack_runtime.visuals import render_assignment_overlay


VERSION = "2.0.0"


def emit(value: Any, *, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream)


def default_run_id(source_aep: Path) -> str:
    return f"ae-stack-v2-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sha256_file(source_aep)[:8].lower()}"


def load_optional(path_value: str | None, default: Any) -> Any:
    return read_json(Path(path_value)) if path_value else default


def parse_evidence(values: list[str]) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    for value in values:
        if "=" not in value:
            raise ValueError("--evidence must use name=path")
        name, raw_path = value.split("=", 1)
        if not name.strip():
            raise ValueError("Evidence name must not be empty")
        rows.append((name.strip(), Path(raw_path).resolve()))
    return rows


def cmd_init_run(args: argparse.Namespace) -> int:
    source = Path(args.source_aep).resolve()
    run_id = args.run_id or default_run_id(source)
    result = init_run(
        source,
        Path(args.reference_image),
        Path(args.library),
        run_id,
        Path(args.source_video) if args.source_video else None,
    )
    emit(result)
    return 0


def cmd_capability_preflight(args: argparse.Namespace) -> int:
    result = capability_preflight(
        Path(args.output),
        afterfx=Path(args.afterfx) if args.afterfx else None,
        ffmpeg=Path(args.ffmpeg) if args.ffmpeg else None,
        ffprobe=Path(args.ffprobe) if args.ffprobe else None,
        require_afterfx=not args.no_require_afterfx,
        require_ffmpeg=not args.no_require_ffmpeg,
    )
    emit({"status": "passed" if result["allRequiredPassed"] else "failed", "output": str(Path(args.output).resolve()), **result})
    return 0 if result["allRequiredPassed"] else 2


def cmd_state_status(args: argparse.Namespace) -> int:
    emit(StateStore(Path(args.run_dir)).status())
    return 0


def cmd_commit_node(args: argparse.Namespace) -> int:
    issues = load_optional(args.issues_json, [])
    if isinstance(issues, dict) and "issues" in issues:
        issues = issues["issues"]
    if not isinstance(issues, list):
        raise ValueError("issues JSON must be an array or an object with an issues array")
    result = StateStore(Path(args.run_dir)).commit(
        node=args.node,
        artifact_path=Path(args.artifact),
        gate_status=args.gate_status,
        maturity=args.maturity,
        expected_state_sha256=args.expected_state_sha,
        evidence_paths=parse_evidence(args.evidence),
        metrics=load_optional(args.metrics_json, {}),
        issues=issues,
        retry_from=args.retry_from,
        producer=load_optional(args.producer_json, None),
    )
    emit({"status": "complete", **result})
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    result = StateStore(Path(args.run_dir)).invalidate(
        from_node=args.from_node,
        reason=args.reason,
        expected_state_sha256=args.expected_state_sha,
    )
    emit({"status": "complete", **result})
    return 0


def cmd_validate_artifact(args: argparse.Namespace) -> int:
    validate_node_artifact(args.node, read_json(Path(args.artifact)))
    emit({"status": "passed", "node": args.node, "artifact": path_state(Path(args.artifact))})
    return 0


def cmd_lock_source_route(args: argparse.Namespace) -> int:
    result = lock_source_route(Path(args.draft), Path(args.output))
    emit({"status": "complete", "output": path_state(Path(args.output)), "routeCompIds": result["routeScope"]["compIds"]})
    return 0


def cmd_analyze_reference(args: argparse.Namespace) -> int:
    result = analyze_reference(
        Path(args.image),
        Path(args.output_dir),
        card_width=args.card_width,
        card_height=args.card_height,
    )
    emit({"status": "complete", **result})
    return 0


def cmd_lock_reference_roi(args: argparse.Namespace) -> int:
    result = lock_reference_roi(Path(args.image), Path(args.draft), Path(args.output))
    emit({"status": "complete", "output": path_state(Path(args.output)), "boardRoi": result["boardRoi"]})
    return 0


def cmd_lock_visible_layout(args: argparse.Namespace) -> int:
    result = lock_visible_layout(
        Path(args.roi),
        Path(args.draft),
        Path(args.output),
        Path(args.overlay) if args.overlay else None,
    )
    response: dict[str, Any] = {
        "status": "complete",
        "output": path_state(Path(args.output)),
        "topSurfaceAnchorCount": result["topSurfaceAnchorCount"],
        "rowCounts": result["grammar"].get("rowCounts"),
    }
    if args.overlay:
        response["overlay"] = path_state(Path(args.overlay))
    emit(response)
    return 0


def cmd_lock_depth_evidence(args: argparse.Namespace) -> int:
    result = lock_depth_evidence(Path(args.visible_layout), Path(args.draft), Path(args.output))
    emit({
        "status": "complete",
        "output": path_state(Path(args.output)),
        "anchorDepthHintCount": len(result["anchorDepthHints"]),
        "occlusionEdgeCount": len(result["occlusionEdges"]),
    })
    return 0


def cmd_build_board_inventory(args: argparse.Namespace) -> int:
    result = build_board_inventory(Path(args.inspection), Path(args.draft), Path(args.output))
    emit({
        "status": "complete",
        "output": path_state(Path(args.output)),
        "includedTileCount": result["includedTileCount"],
        "excludedCandidateCount": result["excludedCandidateCount"],
        "unclassifiedCandidateCount": len(result["unclassifiedCandidates"]),
    })
    return 0


def cmd_build_event_model(args: argparse.Namespace) -> int:
    result = build_event_model(Path(args.inspection), Path(args.inventory), Path(args.draft), Path(args.output))
    emit({
        "status": "complete",
        "output": path_state(Path(args.output)),
        "tileCount": result["tileCount"],
        "eventTileCount": result["eventTileCount"],
        "persistentTileCount": result["persistentTileCount"],
        "sourceFactsSha256": result["sourceFactsSha256"],
    })
    return 0


def cmd_build_capacity(args: argparse.Namespace) -> int:
    result = build_capacity(
        Path(args.event_model),
        Path(args.visible_layout),
        Path(args.depth_evidence),
        Path(args.policy),
        Path(args.output),
    )
    emit({
        "status": "complete",
        "output": path_state(Path(args.output)),
        "sourceTileCount": result["sourceTileCount"],
        "visibleAnchorCount": result["visibleAnchorCount"],
        "physicalSlotCount": result["physicalSlotCount"],
        "provenanceCounts": result["provenanceCounts"],
    })
    return 0


def cmd_render_capacity_overlay(args: argparse.Namespace) -> int:
    render_capacity_overlay(
        Path(args.reference),
        Path(args.visible_layout),
        Path(args.capacity),
        Path(args.output),
    )
    emit({"status": "complete", "output": path_state(Path(args.output))})
    return 0


def cmd_solve_assignment(args: argparse.Namespace) -> int:
    result = solve_assignment_from_files(
        Path(args.event_model),
        Path(args.capacity),
        Path(args.constraints) if args.constraints else None,
    )
    write_json(Path(args.output), result)
    emit({
        "status": result["status"],
        "output": path_state(Path(args.output)),
        "assignmentCount": result["assignmentCount"],
        "blockedClickCount": result["diagnostics"]["blockedClickCount"],
        "occlusionOrderViolationCount": result["diagnostics"]["occlusionOrderViolationCount"],
        "termination": result["solver"]["termination"],
        "nextAction": result["nextAction"],
    })
    return 0 if result["status"] == "solved" else 2


def cmd_simulate(args: argparse.Namespace) -> int:
    result = simulate_from_files(Path(args.event_model), Path(args.capacity), Path(args.assignment))
    write_json(Path(args.output), result)
    emit({
        "status": result["status"],
        "output": path_state(Path(args.output)),
        "writeAuthorized": result["writeAuthorized"],
        "blockedClickCount": result["blockedClickCount"],
        "occlusionOrderViolationCount": result["occlusionOrderViolationCount"],
        "identityErrorCount": result["identityErrorCount"],
        "boundsErrorCount": result["boundsErrorCount"],
    })
    return 0 if result["status"] == "passed" else 2


def cmd_render_assignment_overlay(args: argparse.Namespace) -> int:
    render_assignment_overlay(
        Path(args.reference),
        Path(args.visible_layout),
        Path(args.event_model),
        Path(args.capacity),
        Path(args.assignment),
        Path(args.output),
    )
    emit({"status": "complete", "output": path_state(Path(args.output))})
    return 0


def cmd_build_property_plan(args: argparse.Namespace) -> int:
    result = build_property_plan_with_route(
        Path(args.inspection),
        Path(args.event_model),
        Path(args.capacity),
        Path(args.assignment),
        Path(args.simulation),
        Path(args.source_route),
        Path(args.options) if args.options else None,
        Path(args.output),
    )
    emit({
        "status": "complete",
        "output": path_state(Path(args.output)),
        "propertyUpdateCount": result["propertyUpdateCount"],
        "routeCompIds": result["routeScope"].get("compIds", []),
    })
    return 0


def cmd_make_ae_job(args: argparse.Namespace) -> int:
    result_path = Path(args.result).resolve()
    if args.mode == "inspect":
        if not args.project or args.comp_id is None or not args.library:
            raise ValueError("inspect requires --project, --comp-id, and --library")
        route = read_json(Path(args.source_route)) if args.source_route else None
        scope = route.get("routeScope") if isinstance(route, dict) else None
        job = {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "inspect",
            "projectPath": str(Path(args.project).resolve()),
            "libraryPath": str(Path(args.library).resolve()),
            "resultPath": str(result_path),
            "compId": int(args.comp_id),
            "routeCompIds": scope.get("compIds", []) if isinstance(scope, dict) else None,
            "routeCriticalFootageItemIds": scope.get("routeCriticalFootageItemIds", []) if isinstance(scope, dict) else None,
            "tileLayerNamePattern": args.tile_pattern,
            "moverLayerNamePattern": args.mover_pattern,
            "handLayerNamePattern": args.hand_pattern,
            "watermarkPattern": args.watermark_pattern,
            "includeAllLayers": True,
        }
    elif args.mode == "apply":
        for name in ("source_project", "output_project", "protected_source", "library", "plan"):
            if getattr(args, name) is None:
                raise ValueError(f"apply requires --{name.replace('_', '-')}")
        job = {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "apply",
            "sourceProjectPath": str(Path(args.source_project).resolve()),
            "outputProjectPath": str(Path(args.output_project).resolve()),
            "protectedSourcePath": str(Path(args.protected_source).resolve()),
            "libraryPath": str(Path(args.library).resolve()),
            "planPath": str(Path(args.plan).resolve()),
            "resultPath": str(result_path),
            "watermarkPattern": args.watermark_pattern,
        }
    else:
        for name in ("project", "protected_source", "library", "plan"):
            if getattr(args, name) is None:
                raise ValueError(f"verify requires --{name.replace('_', '-')}")
        job = {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "verify",
            "projectPath": str(Path(args.project).resolve()),
            "protectedSourcePath": str(Path(args.protected_source).resolve()),
            "libraryPath": str(Path(args.library).resolve()),
            "planPath": str(Path(args.plan).resolve()),
            "resultPath": str(result_path),
            "watermarkPattern": args.watermark_pattern,
        }
    write_json(Path(args.output), job)
    emit({"status": "complete", "mode": args.mode, "output": path_state(Path(args.output)), "job": job})
    return 0


def cmd_build_preview_qa(args: argparse.Namespace) -> int:
    draft = read_json(Path(args.draft))
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "preview-qa",
        "createdAt": now_iso(),
        "status": draft.get("status"),
        "independentReview": draft.get("independentReview"),
        "checks": draft.get("checks", []),
        "issues": draft.get("issues", []),
        "evidence": draft.get("evidence", []),
        "reviewer": draft.get("reviewer"),
    }
    validate_preview_qa(result)
    write_json(Path(args.output), result)
    emit({"status": "complete", "output": path_state(Path(args.output)), "checkCount": len(result["checks"])})
    return 0


def cmd_route_qa(args: argparse.Namespace) -> int:
    result = route_qa(read_json(Path(args.qa)))
    if args.output:
        write_json(Path(args.output), result)
    emit(result)
    return 0 if result["status"] != "UNMAPPED" else 2


def cmd_validate_video(args: argparse.Namespace) -> int:
    result = validate_full_render(
        video=Path(args.video),
        protected_source=Path(args.original_source),
        expected_source_sha256=args.original_source_sha,
        output_path=Path(args.output),
        ffprobe=args.ffprobe,
        ffmpeg=args.ffmpeg,
        expected_duration=args.expected_duration,
        duration_tolerance=args.duration_tolerance,
        expected_width=args.expected_width,
        expected_height=args.expected_height,
        expected_fps=args.expected_fps,
    )
    emit(result)
    return 0 if result["status"] == "passed" else 2


def cmd_self_test(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v"],
        text=True,
        check=False,
    )
    return int(process.returncode)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Stateful AE reference-stack transfer runtime")
    root.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = root.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init-run", help="stage inputs and initialize the immutable receipt DAG")
    command.add_argument("--source-aep", required=True)
    command.add_argument("--reference-image", required=True)
    command.add_argument("--library", required=True)
    command.add_argument("--run-id")
    command.add_argument("--source-video")
    command.set_defaults(func=cmd_init_run)

    command = sub.add_parser("capability-preflight", help="check Python, Pillow, AfterFX, ffmpeg, and ffprobe")
    command.add_argument("--output", required=True)
    command.add_argument("--afterfx")
    command.add_argument("--ffmpeg", default="ffmpeg")
    command.add_argument("--ffprobe", default="ffprobe")
    command.add_argument("--no-require-afterfx", action="store_true")
    command.add_argument("--no-require-ffmpeg", action="store_true")
    command.set_defaults(func=cmd_capability_preflight)

    command = sub.add_parser("state-status", help="show active receipts, state hash, and eligible nodes")
    command.add_argument("--run-dir", required=True)
    command.set_defaults(func=cmd_state_status)

    command = sub.add_parser("commit-node", help="CAS-commit one immutable node receipt")
    command.add_argument("--run-dir", required=True)
    command.add_argument("--node", required=True, choices=NODES[1:])
    command.add_argument("--artifact", required=True)
    command.add_argument("--expected-state-sha", required=True)
    command.add_argument("--gate-status", required=True, choices=["PASS", "REVISE", "BLOCKED"])
    command.add_argument("--maturity", choices=["DRAFT", "CANDIDATE", "FINAL"], default="DRAFT")
    command.add_argument("--evidence", action="append", default=[], help="name=path; repeatable")
    command.add_argument("--metrics-json")
    command.add_argument("--issues-json")
    command.add_argument("--retry-from", choices=NODES[1:])
    command.add_argument("--producer-json")
    command.set_defaults(func=cmd_commit_node)

    command = sub.add_parser("invalidate", help="CAS-invalidate a node and every descendant")
    command.add_argument("--run-dir", required=True)
    command.add_argument("--from-node", required=True, choices=NODES[1:])
    command.add_argument("--reason", required=True)
    command.add_argument("--expected-state-sha", required=True)
    command.set_defaults(func=cmd_invalidate)

    command = sub.add_parser("validate-artifact", help="validate a node artifact without committing it")
    command.add_argument("--node", required=True, choices=NODES[1:])
    command.add_argument("--artifact", required=True)
    command.set_defaults(func=cmd_validate_artifact)

    command = sub.add_parser("lock-source-route", help="lock final comp, board comp, route closure, and QA baseline")
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_lock_source_route)

    command = sub.add_parser("analyze-reference", help="produce bounded CV evidence; never author geometry")
    command.add_argument("--image", required=True)
    command.add_argument("--output-dir", required=True)
    command.add_argument("--card-width", type=float)
    command.add_argument("--card-height", type=float)
    command.set_defaults(func=cmd_analyze_reference)

    command = sub.add_parser("lock-reference-roi", help="lock reviewed board ROI and excluded UI/hand regions")
    command.add_argument("--image", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_lock_reference_roi)

    command = sub.add_parser("lock-visible-layout", help="lock visible top-surface anchors after independent overlay review")
    command.add_argument("--roi", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--overlay")
    command.set_defaults(func=cmd_lock_visible_layout)

    command = sub.add_parser("lock-depth-evidence", help="lock only observable/inferred front-back evidence")
    command.add_argument("--visible-layout", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_lock_depth_evidence)

    command = sub.add_parser("build-board-inventory", help="classify every board-layer candidate from AE inspection")
    command.add_argument("--inspection", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_build_board_inventory)

    command = sub.add_parser("build-event-model", help="lock AE-owned layer order, active intervals, clicks, movers, and hand bindings")
    command.add_argument("--inspection", required=True)
    command.add_argument("--inventory", required=True)
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_build_event_model)

    command = sub.add_parser("build-capacity", help="expand visible anchors to exactly one physical slot per source tile")
    command.add_argument("--event-model", required=True)
    command.add_argument("--visible-layout", required=True)
    command.add_argument("--depth-evidence", required=True)
    command.add_argument("--policy", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_build_capacity)

    command = sub.add_parser("render-capacity-overlay", help="draw per-anchor depth totals on the reference")
    command.add_argument("--reference", required=True)
    command.add_argument("--visible-layout", required=True)
    command.add_argument("--capacity", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_render_capacity_overlay)

    command = sub.add_parser("solve-assignment", help="solve tileId -> slotId without writable gameplay facts")
    command.add_argument("--event-model", required=True)
    command.add_argument("--capacity", required=True)
    command.add_argument("--constraints")
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_solve_assignment)

    command = sub.add_parser("simulate", help="simulate using locked event facts and capacity geometry")
    command.add_argument("--event-model", required=True)
    command.add_argument("--capacity", required=True)
    command.add_argument("--assignment", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_simulate)

    command = sub.add_parser("render-assignment-overlay", help="draw source layer identities and hidden depth per visible anchor")
    command.add_argument("--reference", required=True)
    command.add_argument("--visible-layout", required=True)
    command.add_argument("--event-model", required=True)
    command.add_argument("--capacity", required=True)
    command.add_argument("--assignment", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_render_assignment_overlay)

    command = sub.add_parser("build-property-plan", help="freeze exact AE expected-old/new updates")
    command.add_argument("--inspection", required=True)
    command.add_argument("--event-model", required=True)
    command.add_argument("--capacity", required=True)
    command.add_argument("--assignment", required=True)
    command.add_argument("--simulation", required=True)
    command.add_argument("--source-route", required=True)
    command.add_argument("--options")
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_build_property_plan)

    command = sub.add_parser("make-ae-job", help="create a deterministic inspect/apply/verify AE worker job")
    command.add_argument("--mode", required=True, choices=["inspect", "apply", "verify"])
    command.add_argument("--output", required=True, help="job JSON output")
    command.add_argument("--result", required=True, help="worker result JSON path")
    command.add_argument("--library")
    command.add_argument("--project")
    command.add_argument("--source-project")
    command.add_argument("--output-project")
    command.add_argument("--protected-source")
    command.add_argument("--plan")
    command.add_argument("--source-route")
    command.add_argument("--comp-id", type=int)
    command.add_argument("--tile-pattern", default="^tile[0-9]+$")
    command.add_argument("--mover-pattern", default="movetop|move|fly")
    command.add_argument("--hand-pattern", default="hand|finger")
    command.add_argument("--watermark-pattern", default="watermark|水印")
    command.set_defaults(func=cmd_make_ae_job)

    command = sub.add_parser("build-preview-qa", help="normalize and validate an independent preview review")
    command.add_argument("--draft", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(func=cmd_build_preview_qa)

    command = sub.add_parser("route-qa", help="route typed failures to the earliest authoritative retry node")
    command.add_argument("--qa", required=True)
    command.add_argument("--output")
    command.set_defaults(func=cmd_route_qa)

    command = sub.add_parser("validate-video", help="probe and fully decode the final render while rehashing the original AEP")
    command.add_argument("--video", required=True)
    command.add_argument("--original-source", required=True)
    command.add_argument("--original-source-sha", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--expected-duration", type=float)
    command.add_argument("--duration-tolerance", type=float, default=0.05)
    command.add_argument("--expected-width", type=int)
    command.add_argument("--expected-height", type=int)
    command.add_argument("--expected-fps", type=float)
    command.add_argument("--ffprobe", default="ffprobe")
    command.add_argument("--ffmpeg", default="ffmpeg")
    command.set_defaults(func=cmd_validate_video)

    command = sub.add_parser("self-test", help="run the packaged regression suite")
    command.set_defaults(func=cmd_self_test)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except Exception as error:
        emit({"status": "error", "error": str(error)}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
