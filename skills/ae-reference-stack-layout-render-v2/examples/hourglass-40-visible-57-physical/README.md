# 40-visible / 57-physical Golden Fixture

This fixture models the reviewed hourglass stack case:

- visible row counts: `[6,5,4,3,2,2,3,4,5,6]`;
- 40 visible top-surface anchors;
- 57 source tiles and physical slots;
- 17 hidden slots, explicitly marked `synthesized-for-surplus`;
- assignment rows restricted to `{tileId, slotId}`;
- expected simulation result: zero blocked clicks and zero occlusion-order violations.

The raster and overlays are synthetic regression evidence rather than a copy of the user's production artwork. JSON path fields are package-relative for portability. The test suite also regenerates the full fixture in a temporary directory and validates its hash lineage.
