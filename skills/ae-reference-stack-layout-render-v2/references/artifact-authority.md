# Artifact Authority Contracts

## Authority matrix

| Field or decision | Sole authority |
|---|---|
| AE comp/layer/source identity | `source-event-model` derived from inspection/inventory |
| Render front/back convention | event model (`renderOrder = layerIndex`) |
| Active interval and removal | event model (`inPoint/outPoint`) |
| Click schedule | event model |
| Face/match/mover/hand identity | event model |
| Visible stack silhouette and holes | `visible-layout` |
| Visible surface anchors | `visible-layout` |
| Observable/inferred front/back evidence | `observed-depth` |
| Hidden physical capacity | `capacity-plan` |
| Tile-to-slot mapping | `assignment` |
| Target AE property values | `property-plan` derived from assignment/capacity |
| Actual applied values | `apply-readback` |
| Candidate visual acceptance | `preview-qa` |
| Final media validity | `full-render-qa` |

No artifact may silently duplicate and override another artifact's authority.

## Source event facts

Canonical fact fields include:

```text
tileId, compId, layerIndex, layerName, sourceId, faceId,
renderOrder, activeStart, activeEnd, removalTime,
clickOrdinal, clickTime, matchGroupId,
originalPosition, settledPositionKey,
originalScale, settledScaleKey, cardSize,
moverBinding, handBindings, layerFingerprintSha256
```

`sourceFactsSha256` is calculated over the canonical sorted projection. A stale or hand-edited event artifact fails validation.

## Visible layout

Coordinates are explicit:

- `referenceCoordinateSystem`: raster pixels;
- `coordinateSystem`: board-comp coordinates;
- `referenceToBoardTransform`: scale and offset;
- each anchor stores reference and board centers/sizes.

This prevents ambiguous mixing of screenshot pixels and AE comp coordinates.

Every visible anchor rectangle must remain inside `safeRegion`. Exact duplicate visible centers are forbidden; hidden depth belongs in capacity.

## Depth evidence versus hidden design

`observed-depth` uses three per-anchor evidence classes:

- `observed`: visible pixels directly support the depth bound;
- `inferred`: a defensible relation follows from visible occlusion/stack grammar;
- `unknown`: fully hidden depth is not knowable from this raster.

Capacity slot provenance is separate. A hidden slot can be `synthesized-for-surplus` even when the policy chooses its anchor deliberately.

## Capacity plan

Hard invariants:

- `physicalSlotCount == sourceTileCount`;
- `visibleAnchorCount` anchors each own at least depth zero;
- depth indices per anchor are contiguous from zero;
- slot IDs are unique;
- every front/back edge references valid slots;
- all slot rectangles fit the safe region;
- source and visible/depth lineage hashes are present.

## Assignment

Each row has this exact schema:

```json
{
  "tileId": "tile-001",
  "slotId": "r01-c01::d0"
}
```

The following are forbidden in assignment rows:

```text
zOrder, renderOrder, activeStart, activeEnd,
clickTime, clickOrdinal, targetPosition
```

Adding any extra field fails validation even when its value happens to be correct.

## Simulation

Simulation is not authorized by a plausible mapping alone. It requires:

- exact event source-fact hash;
- exact capacity artifact hash;
- exact assignment artifact hash;
- `assignmentMayOverrideSourceFacts: false`;
- all hard-error counters equal zero.

## Property plan

The plan is a transaction, not a high-level instruction. Each update names the target property and carries exact old/new values. Multiple writes to one keyed property are merged; conflicting writes to one key are rejected.

A plan never reorders layers by default. Layer reordering would require a separate audited capability because it can break index-based expressions, parents, track mattes, and external scripts.
