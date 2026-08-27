from __future__ import annotations

from typing import Any, Iterable

from .common import sha256_json


EVENT_FACT_FIELDS: tuple[str, ...] = (
    "tileId",
    "compId",
    "layerIndex",
    "layerName",
    "sourceId",
    "faceId",
    "renderOrder",
    "activeStart",
    "activeEnd",
    "removalTime",
    "clickOrdinal",
    "clickTime",
    "matchGroupId",
    "originalPosition",
    "settledPositionKey",
    "originalScale",
    "settledScaleKey",
    "cardSize",
    "moverBinding",
    "handBindings",
    "layerFingerprintSha256",
)


def event_facts_payload(tiles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the canonical, immutable gameplay/AE fact projection.

    Fields outside this projection may be presentation metadata. Any mutation to
    a field that can affect assignment, simulation, or AE edits changes the
    source-facts hash and invalidates downstream artifacts.
    """
    return [
        {key: row.get(key) for key in EVENT_FACT_FIELDS}
        for row in sorted(tiles, key=lambda value: (int(value["compId"]), int(value["renderOrder"]), str(value["tileId"])))
    ]


def event_facts_sha256(tiles: Iterable[dict[str, Any]]) -> str:
    return sha256_json(event_facts_payload(tiles))
