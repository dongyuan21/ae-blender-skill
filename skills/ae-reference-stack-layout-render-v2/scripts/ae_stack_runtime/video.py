from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from .common import SCHEMA_VERSION, now_iso, path_state, sha256_file, write_json


def _fraction(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def validate_full_render(
    *,
    video: Path,
    protected_source: Path,
    expected_source_sha256: str,
    output_path: Path,
    ffprobe: str,
    ffmpeg: str,
    expected_duration: float | None = None,
    duration_tolerance: float = 0.05,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
) -> dict[str, Any]:
    video = video.resolve()
    protected_source = protected_source.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    if not protected_source.is_file():
        raise FileNotFoundError(protected_source)
    probe_command = [
        ffprobe,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(video),
    ]
    probe = subprocess.run(probe_command, capture_output=True, text=True, check=False)
    errors: list[str] = []
    if probe.returncode != 0:
        errors.append(f"ffprobe failed: {probe.stderr.strip()}")
        data: dict[str, Any] = {}
    else:
        data = json.loads(probe.stdout)
    streams = data.get("streams", []) if isinstance(data, dict) else []
    video_stream = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio_streams = [row for row in streams if row.get("codec_type") == "audio"]
    duration = float((data.get("format") or {}).get("duration", 0.0)) if isinstance(data, dict) else 0.0
    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    fps = _fraction(str(video_stream.get("avg_frame_rate", "0/0"))) if video_stream else 0.0
    if video_stream is None:
        errors.append("No video stream")
    if expected_duration is not None and abs(duration - expected_duration) > duration_tolerance:
        errors.append(f"Duration {duration:.6f} differs from expected {expected_duration:.6f}")
    if expected_width is not None and width != expected_width:
        errors.append(f"Width {width} differs from expected {expected_width}")
    if expected_height is not None and height != expected_height:
        errors.append(f"Height {height} differs from expected {expected_height}")
    if expected_fps is not None and abs(fps - expected_fps) > 0.01:
        errors.append(f"FPS {fps:.6f} differs from expected {expected_fps:.6f}")
    decode_command = [ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "-"]
    decode = subprocess.run(decode_command, capture_output=True, text=True, check=False)
    full_decode_passed = decode.returncode == 0
    if not full_decode_passed:
        errors.append(f"Full decode failed: {decode.stderr.strip()}")
    source_hash = sha256_file(protected_source)
    original_unchanged = source_hash.upper() == expected_source_sha256.upper()
    if not original_unchanged:
        errors.append("Protected original source hash changed")
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactType": "full-render-qa",
        "createdAt": now_iso(),
        "status": "passed" if not errors else "failed",
        "video": path_state(video),
        "protectedSource": path_state(protected_source),
        "expectedSourceSha256": expected_source_sha256.upper(),
        "originalSourceUnchanged": original_unchanged,
        "fullDecodePassed": full_decode_passed,
        "errors": errors,
        "probe": {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "videoCodec": video_stream.get("codec_name") if video_stream else None,
            "audioStreamCount": len(audio_streams),
            "frameCount": int(video_stream.get("nb_frames", 0)) if video_stream and str(video_stream.get("nb_frames", "")).isdigit() else None,
        },
        "commands": {"ffprobe": probe_command, "decode": decode_command},
    }
    write_json(output_path, result)
    return result
