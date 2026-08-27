# Workflow

## 1. Run discipline

The runtime is artifact-driven. Conversation text is not durable progress. At every continuation:

1. run `state-status`;
2. capture `stateSha256`;
3. select one node from `eligibleNodes`;
4. read only that node's required upstream artifacts and relevant evidence;
5. produce one main JSON artifact plus evidence files;
6. validate it;
7. CAS-commit the attempt;
8. stop or continue from the new state.

Never overwrite a locked artifact. Write a new draft/output and commit a new receipt attempt. A new upstream PASS invalidates active descendants automatically.

## 2. Source branch

### Source route

Lock:

- final render comp;
- editable board comp;
- full nesting path from final to board;
- route comp IDs;
- route-critical footage IDs;
- accepted route QA baseline;
- render/edit roles.

Board and final comp may be the same only with an explicit justification.

### Board inventory

Run read-only AE inspection on the staged AEP. Classify every candidate as included or excluded. Included tiles retain:

- comp ID;
- layer index and name;
- source ID/name;
- in/out/start time;
- settled Position/Scale key or static value;
- measured/derived card size;
- parent/matte/3D flags;
- a layer fingerprint hash.

No unclassified candidate may remain in a PASS artifact.

### Event model

Events are a reviewed projection of inspected facts. For each tile:

- render order is copied from layer index;
- active interval is copied from in/out points;
- click time and ordinal must be supported by source evidence;
- mover source identity and in-point continuity are verified;
- hand key and finger offset are verified;
- face identity cannot be rewritten by an event draft.

The builder computes a canonical `sourceFactsSha256`; validators recompute it. Any behavioral mutation must produce a different event artifact and invalidate all descendants.

## 3. Reference branch

### ROI

The ROI includes the target stack and excludes hand, tray, UI, text, background ornaments, and unrelated effects. Record every explicit exclusion.

### Visible layout

Represent the reference as a grammar, not a raw CV dump. Preferred fields include:

- family (`hourglass-rows`, `pyramid`, `branch`, `grid-with-holes`, etc.);
- row counts and row offsets;
- visible anchor centers and card sizes;
- silhouette and negative-space regions;
- observed confidence;
- reference-to-board transform.

A visible anchor is one visible top-surface position. It is not a count of all fully hidden cards behind that surface.

Use separate proposer and reviewer contexts. The locked artifact requires both approved reviews and `reviewerReview.independentContext: true`.

### Depth evidence

Record only:

- min/max depth bounds per visible anchor;
- observed or defensibly inferred occlusion edges;
- evidence class and concise rationale.

Use `unknown` when a single raster cannot establish fully hidden depth. Do not disguise source-count reconciliation as visual observation.

## 4. Convergence branch

### Capacity reconciliation

Input: locked event model, visible layout, depth evidence, and a capacity policy.

Output: exactly one physical slot per source tile. Every slot has:

- unique slot ID;
- owning visible surface anchor;
- depth index contiguous from zero;
- board-comp center and size;
- provenance;
- front/back constraints.

The visible top slot always remains at the locked visible anchor. Hidden offsets above 5% of card size require explicit opt-in because they may alter the silhouette.

### Assignment

The solver may use fixed, allowed, and forbidden tile-slot constraints. The output mapping is deliberately weak:

```json
{"tileId": "tile-017", "slotId": "r05-c01::d2"}
```

No other row fields are legal.

### Simulation

The simulator validates:

- exact tile/slot coverage;
- source/capacity lineage;
- safe bounds;
- overlap graph;
- active blockers at every click;
- AE layer-order consistency with capacity front/back edges;
- match group size, when configured.

Only a passed report with `writeAuthorized: true` may proceed.

## 5. AE transaction branch

Build one frozen Property Plan. It computes target values from the mapping but obtains expected old values from the current inspection. Do not manually edit the plan after validation.

The AE runner enforces:

- staged input and distinct staged output;
- protected original hash;
- dependency hashes before/after;
- expected comp/layer/source identity;
- expected key count and old values;
- readback after write;
- fresh reopen verification;
- route-scoped regression checks.

## 6. Promotion branch

A preview review must inspect the settled frame and event samples. Typed failures are routed to the earliest authoritative node. QA does not patch the project.

Final promotion requires:

- original AEP unchanged;
- no source/reference authority violation;
- zero simulation hard errors;
- all property readbacks exact within tolerance;
- no new route-critical missing footage, expression error, or enabled watermark;
- independently accepted visual/behavior preview;
- intended final comp rendered;
- ffprobe metadata checks and ffmpeg full decode pass.
