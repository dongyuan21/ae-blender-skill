---
name: ae-reference-stack-layout-render-v2
description: Stateful transfer of a visible game-tile/card stack from one raster reference into an editable After Effects source AEP while preserving the source click, match, removal, mover, hand, UI, audio, and render route. Uses immutable state receipts, independent visual review, a locked AE event model, deterministic hidden-capacity reconciliation, constrained tile-to-slot assignment, pre-write simulation, isolated AEP property transactions, and route-scoped QA. Intended for Codex 5.6 SOL at extra-high reasoning. Do not use for texture-only swaps, baked-only gameplay, or tasks that authorize borrowing the reference image's source AEP.
---

# AE Reference Stack Layout Render v2

Operate this Skill as a thin stateful orchestrator. Do not solve the whole task in one model response, do not keep progress only in conversation text, and do not let later stages rewrite earlier authority artifacts.

## Hard authority boundaries

Four artifacts are independent authorities:

1. `source-event-model.json` owns AE/gameplay facts: composition/layer identity, AE layer index/render order, in/out interval, click order/time, mover pairing, hand binding, face identity, and match group.
2. `visible-layout.json` owns only the visible top-surface reference geometry: ROI, silhouette, holes, row/branch grammar, anchor centers/sizes, and observable surface evidence.
3. `capacity-plan.json` reconciles visible anchors with the complete source tile count. It owns physical slots and clearly labels hidden depth as observed, inferred, or synthesized for surplus.
4. `assignment.json` owns only `tileId -> slotId`. Every row must contain exactly `tileId` and `slotId`.

Never place `zOrder`, `renderOrder`, `activeStart`, `activeEnd`, `clickTime`, `clickOrdinal`, or target coordinates in an assignment row. The simulator reads those facts from the locked event model and geometry from the locked capacity plan.

The reference image owns visible geometry. The source AEP owns executable behavior and final packaging. Never search for, inspect, or borrow the reference image's source AEP, coordinates, layers, or timeline.

## Invocation and model scope

- Intended model: Codex 5.6 SOL, reasoning extra-high. Other models are unverified.
- Do not invoke implicitly. The user must select or name this Skill.
- Use a fresh model context for each independent reviewer. A proposer must not approve its own overlay.
- Do not expose private chain-of-thought. Reviews contain findings, confidence, typed issues, and a concise decision rationale only.

## First action on every continuation

Run:

```bash
python scripts/ae_stack.py state-status --run-dir <run-dir>
```

Read `stateSha256`, `activePasses`, and `eligibleNodes`. Execute only an eligible node. Never edit `state/current.json` or receipt files manually.

Every node attempt ends with a CAS commit:

```bash
python scripts/ae_stack.py commit-node \
  --run-dir <run-dir> \
  --node <NODE> \
  --artifact <artifact.json> \
  --expected-state-sha <stateSha256-read-before-work> \
  --gate-status PASS|REVISE|BLOCKED \
  --maturity DRAFT|CANDIDATE|FINAL \
  --evidence <name>=<path>
```

A stale worker must fail CAS rather than overwrite newer state. A new upstream PASS automatically invalidates all active descendants.

## State graph

```text
INITIALIZED
  -> CAPABILITY_PREFLIGHT_PASSED
      -> SOURCE_ROUTE_LOCKED
          -> BOARD_INVENTORY_LOCKED
              -> EVENT_MODEL_LOCKED -------------------------+
      -> REFERENCE_ROI_LOCKED                                |
          -> VISIBLE_LAYOUT_LOCKED                           |
              -> DEPTH_EVIDENCE_LOCKED ----------------------+ 
                  -> CAPACITY_RECONCILED
                      -> ASSIGNMENT_SOLVED
                          -> SIMULATION_PASSED
                              -> PROPERTY_PLAN_FROZEN
                                  -> APPLY_READBACK_PASSED
                                      -> PREVIEW_ACCEPTED
                                          -> FULL_RENDER_PASSED
```

The source and reference branches may proceed independently after capability preflight. They converge only at `CAPACITY_RECONCILED`.

## Node ownership

| Node | Producer | May decide | Must not decide |
|---|---|---|---|
| `CAPABILITY_PREFLIGHT_PASSED` | deterministic tool | host/tool availability | project meaning |
| `SOURCE_ROUTE_LOCKED` | GPT proposal + review | final comp, board comp, nesting route, route QA scope | tile identity or target layout |
| `BOARD_INVENTORY_LOCKED` | GPT classification + deterministic builder | include/exclude every candidate board layer | click schedule or target slots |
| `EVENT_MODEL_LOCKED` | GPT evidence review + deterministic builder | pair static/mover/hand evidence and confirm event facts | change AE layer order, in/out points, reference geometry |
| `REFERENCE_ROI_LOCKED` | GPT proposer/reviewer | board ROI and excluded UI/hand/background | hidden depth |
| `VISIBLE_LAYOUT_LOCKED` | independent proposer and reviewer | visible anchors, grammar, silhouette, holes | source tile count, hidden capacity |
| `DEPTH_EVIDENCE_LOCKED` | independent review | only observable/inferred front/back evidence and depth bounds | invent fully hidden tiles as visual fact |
| `CAPACITY_RECONCILED` | deterministic tool + policy review | physical slot count and provenance | modify visible anchor geometry or source facts |
| `ASSIGNMENT_SOLVED` | deterministic solver | one-to-one tile-to-slot mapping | write any gameplay fact or target coordinates into assignment rows |
| `SIMULATION_PASSED` | deterministic simulator | identity, bounds, click accessibility, match size, occlusion order | repair artifacts silently |
| `PROPERTY_PLAN_FROZEN` | deterministic builder | exact AE expected-old/new property transaction | move unlisted layers or reorder layers |
| `APPLY_READBACK_PASSED` | isolated AE worker + hash runner | apply and freshly read back frozen values | edit original AEP or accept new route regressions |
| `PREVIEW_ACCEPTED` | independent visual/behavior reviewer | candidate visual and event acceptance | directly patch AEP |
| `FULL_RENDER_PASSED` | deterministic video QA + final review | final technical promotion | waive failed safety/readback gates |

## Operating procedure

### 1. Initialize and preflight

```bash
python scripts/ae_stack.py init-run \
  --source-aep <source.aep> \
  --reference-image <reference.png> \
  --library <library-dir>
```

This stages a copy below `<library>/.staging/<run-id>`, hashes the original, creates immutable receipt storage, and never opens the original in AE.

Run capability preflight. On the real Windows AE host, require AfterFX, ffmpeg, and ffprobe.

### 2. Lock source route and inventory

Use a read-only inspection job on the staged AEP. Lock two distinct roles whenever applicable:

- edit the nested board composition;
- render the final wrapper composition.

Scope missing footage, expression errors, and watermark checks to the selected render route. Historical project-wide defects are evidence, not automatic blockers. Only a new route-critical regression blocks promotion.

Classify every board candidate. Every candidate must be included once or excluded with evidence. Do not equate click events with the full board inventory.

### 3. Lock the source event model

The event model copies, never predicts:

- `renderOrder = AE layerIndex` under the locked AE convention that smaller layer indices render in front;
- `activeStart = inPoint`;
- `activeEnd/removalTime = outPoint`;
- click schedule and mover/hand bindings from inspected keys and source evidence.

The canonical `sourceFactsSha256` is recomputed during validation. Any mutation to a gameplay/AE fact invalidates the artifact and every descendant.

### 4. Lock reference ROI, visible layout, and depth evidence

Use `agents/prompts/visible-layout-proposer.md` in one context. Generate a full-frame overlay plus dense-region/row crops where needed.

Use `agents/prompts/visible-layout-reviewer.md` in a fresh context. The reviewer sees the original image, overlay, structured draft, and crops, but not the proposer's private reasoning. `reviewerReview.independentContext` must be true.

Visible layout contains only visible top-surface anchors. Hidden capacity is not authored here.

Depth evidence may record observed or defensibly inferred front/back edges and min/max depth bounds. Fully hidden backfill remains `unknown` until capacity reconciliation.

### 5. Reconcile capacity

Run `build-capacity`. It must produce exactly one physical slot for every source tile while preserving all visible anchors.

Slot provenance is explicit:

- `observed-top-surface`;
- `observed-depth`;
- `inferred-depth`;
- `synthesized-for-surplus`.

Do not concentrate surplus at one fallback center unless later reveal behavior and visual evidence justify it. Generate `capacity-overlay.png` and review it before committing.

### 6. Solve and simulate

Run `solve-assignment`. GPT may author constraints such as fixed/allowed/forbidden tile-slot pairs, but it may not handwrite the final mapping with hidden source facts.

A solved assignment must have:

- complete and unique tile coverage;
- complete and unique slot coverage;
- zero identity errors;
- zero bounds errors;
- zero blocked clicks;
- zero reference/same-anchor occlusion-order violations;
- valid match-group size when configured.

Then run `simulate`. Only a `passed` report with `writeAuthorized: true` may advance to a property plan.

### 7. Freeze and apply the AE transaction

Build a property plan from the current inspection, event model, capacity, assignment, simulation, and source route. The builder verifies all lineage hashes.

The transaction contains exact:

- comp/layer/source identity;
- expected key count;
- expected old static/key value;
- new value;
- tolerance;
- route QA baseline;
- dependency and disabled-layer locks.

Duplicate writes to one property are coalesced when they target distinct keys. Conflicting writes to the same key are rejected before AE runs.

Run `apply_property_plan_v2.jsx` through `scripts/run_afterfx_job.py` on a staged input and distinct staged output. The runner must protect both the staged input and original source hash. Reopen the output using `verify_property_plan_v2.jsx`; do not treat same-session readback as sufficient.

### 8. Preview, route failures, and final render

Generate:

- settled frame;
- reference/preview side-by-side;
- visible-layout overlay;
- capacity overlay;
- assignment overlay;
- event contact sheet or short clips around every changed click/mover/hand event.

Use `agents/prompts/preview-reviewer.md` in a fresh context. QA returns typed issue codes only from `references/failure-routing.md`. Run `route-qa`; invalidate the earliest authoritative retry node and descendants. QA never edits the AEP directly.

After preview acceptance, render the final wrapper comp. Run full ffprobe metadata checks and an ffmpeg full decode while rehashing the original AEP. Promote only after all final gates pass.

## Candidate and final semantics

- `DRAFT`: evidence or a model proposal; not authorized for AE write.
- `CANDIDATE`: an isolated AEP/preview may exist and safety gates pass, but independent visual/final QA is incomplete or requests revision.
- `FINAL`: fresh reopen/readback, preview review, full render QA, route QA, and original-source immutability all pass.
- `REVISE`: safe progress exists, but the named authoritative node must be regenerated.
- `BLOCKED`: safe continuation is impossible, such as no editable board interval, unresolved critical identity, inability to open/save an isolated AEP, or a route-critical dependency preventing meaningful output.

Never hide a safe candidate merely because it is imperfect. Never call an unclickable or unverified candidate final.

## Required references

Read progressively:

- `references/workflow.md` for every run.
- `references/state-machine.md` before committing or retrying nodes.
- `references/artifact-authority.md` before authoring any JSON draft.
- `references/gpt-handoffs.md` before proposer/reviewer calls.
- `references/ae-transaction-and-route-qa.md` before any AE write.
- `references/failure-routing.md` before preview/final QA.
- `references/cli-reference.md` for command inputs and outputs.

## Packaged proof fixture

`examples/hourglass-40-visible-57-physical/` is the regression case derived from the reviewed scenario:

- row counts: `[6,5,4,3,2,2,3,4,5,6]`;
- 40 visible top-surface anchors;
- 57 source tiles/physical slots;
- 17 hidden slots marked `synthesized-for-surplus`;
- assignment rows contain only `tileId` and `slotId`;
- zero blocked clicks and zero occlusion-order violations.

Run:

```bash
python scripts/ae_stack.py self-test
```

Do not bypass a failed test, validator, state CAS, or independent visual gate by editing a locked artifact in place.
