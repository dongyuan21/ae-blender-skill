from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from .common import SCHEMA_VERSION, now_iso, path_state, sha256_file, standard_safety, write_json
from .state import StateStore


def _image_state(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        value = {
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
        }
        if "A" in image.getbands():
            value["alphaExtrema"] = list(image.getchannel("A").getextrema())
    return {**path_state(path), **value}


def init_run(
    source_aep: Path,
    reference_image: Path,
    library: Path,
    run_id: str,
    source_video: Path | None = None,
) -> dict[str, Any]:
    source_aep = source_aep.resolve()
    reference_image = reference_image.resolve()
    library = library.resolve()
    if not source_aep.is_file() or source_aep.suffix.lower() != ".aep":
        raise FileNotFoundError(f"Source AEP is missing or not .aep: {source_aep}")
    if not reference_image.is_file() or reference_image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise FileNotFoundError(f"Reference image is missing or unsupported: {reference_image}")
    if source_video is not None:
        source_video = source_video.resolve()
        if not source_video.is_file():
            raise FileNotFoundError(source_video)
    if any(character in run_id for character in '<>:"/\\|?*') or run_id in {".", "..", ""}:
        raise ValueError(f"Unsafe run ID: {run_id}")
    source_hash = sha256_file(source_aep)
    run_dir = library / ".staging" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)
    paths = {
        name: run_dir / name
        for name in ("input", "evidence", "drafts", "artifacts", "state", "editable", "renders", "logs", "delivery")
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=False)
    staged_aep = paths["input"] / "source-copy.aep"
    staged_reference = paths["input"] / f"reference{reference_image.suffix.lower()}"
    shutil.copy2(source_aep, staged_aep)
    shutil.copy2(reference_image, staged_reference)
    staged_video = None
    if source_video is not None:
        staged_video = paths["input"] / f"source-video{source_video.suffix.lower()}"
        shutil.copy2(source_video, staged_video)
    if sha256_file(staged_aep) != source_hash:
        raise RuntimeError("Staged AEP hash does not match original")
    if sha256_file(source_aep) != source_hash:
        raise RuntimeError("Original AEP changed during staging")
    artifact = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "run-initialization",
        "createdAt": now_iso(),
        "runId": run_id,
        "runDirectory": str(run_dir),
        "libraryPath": str(library),
        "source": {
            "originalAep": path_state(source_aep),
            "stagedAep": path_state(staged_aep),
            "originalUnchanged": True,
            "sourceVideo": path_state(staged_video) if staged_video is not None else None,
        },
        "reference": {
            "originalImage": path_state(reference_image),
            "stagedImage": _image_state(staged_reference),
        },
        "paths": {name: str(path) for name, path in paths.items()},
        "safety": standard_safety(),
    }
    initialization_path = paths["artifacts"] / "run-initialization.json"
    write_json(initialization_path, artifact)
    state = StateStore(run_dir)
    status = state.initialize(run_id, initialization_path)
    return {
        "status": "complete",
        "runDirectory": str(run_dir),
        "initializationArtifact": str(initialization_path),
        "state": status,
    }


def capability_preflight(
    output_path: Path,
    *,
    afterfx: Path | None,
    ffmpeg: Path | None,
    ffprobe: Path | None,
    require_afterfx: bool = True,
    require_ffmpeg: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append({
        "name": "python-version",
        "required": True,
        "passed": sys.version_info >= (3, 10),
        "actual": sys.version.split()[0],
        "expected": ">=3.10",
    })
    checks.append({
        "name": "pillow-import",
        "required": True,
        "passed": True,
        "actual": Image.__version__ if hasattr(Image, "__version__") else "available",
    })
    for name, path, required in (
        ("afterfx", afterfx, require_afterfx),
        ("ffmpeg", ffmpeg, require_ffmpeg),
        ("ffprobe", ffprobe, require_ffmpeg),
    ):
        raw = str(path) if path is not None else None
        resolved: str | None = None
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_file():
                resolved = str(candidate.resolve())
            else:
                resolved = shutil.which(raw)
        checks.append({
            "name": name,
            "required": required,
            "passed": resolved is not None,
            "path": resolved,
            "requested": raw,
        })
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "capability-preflight",
        "createdAt": now_iso(),
        "checks": checks,
        "allRequiredPassed": all(row["passed"] for row in checks if row["required"]),
    }
    write_json(output_path, result)
    return result
