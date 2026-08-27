from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA_VERSION = 2


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def require_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(f"{label} must be an integer")
    return int(value)


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def vector(value: Any, label: str, minimum: int = 2) -> list[float]:
    rows = require_list(value, label)
    if len(rows) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} numbers")
    return [require_number(item, f"{label}[{index}]") for index, item in enumerate(rows)]


def unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"Duplicate {label}: {sorted(set(duplicates))}")


def path_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def artifact_ref(path: Path, name: str | None = None) -> dict[str, Any]:
    state = path_state(path)
    return {"name": name or path.name, **state}


def rect_from_center(center: list[float], size: list[float]) -> tuple[float, float, float, float]:
    x, y = center[:2]
    width, height = size[:2]
    if width <= 0 or height <= 0:
        raise ValueError("Rectangle size must be positive")
    return x - width / 2.0, y - height / 2.0, x + width / 2.0, y + height / 2.0


def overlap_metrics(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float]:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    area = width * height
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    minimum_area = min(first_area, second_area)
    ratio = area / minimum_area if minimum_area > 0 else 0.0
    return area, ratio


@contextmanager
def exclusive_lock(path: Path, timeout: float = 15.0, poll: float = 0.1) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} created={now_iso()}\n".encode("utf-8"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring state lock: {path}")
            time.sleep(poll)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        path.unlink(missing_ok=True)


def with_xy(original: list[float], x: float, y: float) -> list[float]:
    result = [float(value) for value in original]
    if len(result) < 2:
        raise ValueError("Vector requires at least two values")
    result[0], result[1] = float(x), float(y)
    return result


def standard_safety() -> dict[str, bool]:
    return {
        "originalAepEdited": False,
        "referenceSourceAepUsed": False,
        "referenceSourceGeometryUsed": False,
    }
