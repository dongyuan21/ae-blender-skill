# GPT Handoffs

## General rule

Each model call receives only the artifacts and evidence needed for its node. Do not give a reviewer the proposer's hidden reasoning or tell it that approval is expected. The output is structured JSON plus a concise rationale.

## Visible layout proposer

Input:

- original full-resolution reference;
- locked ROI and exclusions;
- optional low-level pixel evidence;
- target board-comp dimensions/safe region;
- expected card body estimate.

Output:

- visible anchor draft;
- row/branch grammar;
- silhouette and holes;
- confidence and ambiguous regions;
- overlay/crop requests.

It does not receive source tile count or click schedule unless needed only to explain coordinate bounds. This prevents source behavior from shaping the visible reference model.

Template: `agents/prompts/visible-layout-proposer.md`.

## Visible layout reviewer

Use a fresh context. Input:

- original reference;
- locked ROI;
- proposer JSON;
- full overlay;
- row/dense-region crops.

Output:

- `approved` or `revise`;
- typed issues;
- corrected observations, not a replacement hidden-capacity design;
- independent-context assertion.

Template: `agents/prompts/visible-layout-reviewer.md`.

## Event model reviewer

Input:

- read-only AE inspection;
- board inventory;
- source render/contact sheet;
- proposed event draft;
- pair candidates.

Output:

- approval or typed ambiguity;
- static/mover/hand evidence;
- click/removal evidence;
- identity disagreements.

It cannot modify AE layer index, in/out points, source ID, or face identity to make a later layout feasible.

Template: `agents/prompts/event-model-reviewer.md`.

## Preview reviewer

Use a fresh context after fresh reopen/readback. Input:

- original reference;
- settled candidate frame;
- side-by-side/difference or overlay;
- capacity and assignment overlays;
- click/mover/hand event samples;
- simulation summary;
- route QA summary.

Output:

- accepted or revise;
- checks;
- typed issues using `failure-routing.md`;
- evidence references.

It never patches AE or rewrites an upstream artifact.

Template: `agents/prompts/preview-reviewer.md`.

## Context minimization

Do not feed raw thousands of Hough lines/corners into the primary layout call. Supply:

- summarized candidate card size;
- clustered rows/anchors;
- full pixel evidence artifact by path;
- selected uncertain regions.

Raw CV evidence remains auditable but should not dominate the model context.
