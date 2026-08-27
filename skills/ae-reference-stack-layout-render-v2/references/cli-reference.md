# CLI Reference

Use `python scripts/ae_stack.py <command> --help` for argument details.

## Run and state

```text
init-run               stage/hash inputs and initialize state
capability-preflight   check Python/Pillow/AfterFX/ffmpeg/ffprobe
state-status           show active authorities, CAS hash, eligible nodes
commit-node            validate and CAS-commit one node attempt
invalidate             invalidate a node and descendants
validate-artifact      validate one node artifact without committing
```

## Source branch

```text
make-ae-job --mode inspect
lock-source-route
build-board-inventory
build-event-model
```

Typical inspect worker:

```powershell
python scripts\ae_stack.py make-ae-job `
  --mode inspect `
  --project <staged-source-copy.aep> `
  --library <library> `
  --comp-id <board-comp-id> `
  --source-route <source-route.json> `
  --result <inspection-result.json> `
  --output <inspect-job.json>

python scripts\run_afterfx_job.py `
  --afterfx <AfterFX.exe> `
  --worker scripts\ae\inspect_stack_v2.jsx `
  --job <inspect-job.json>
```

## Reference branch

```text
analyze-reference      bounded pixel/CV evidence; never writes AEP
lock-reference-roi
lock-visible-layout    optional overlay output
lock-depth-evidence
```

## Convergence and simulation

```text
build-capacity
render-capacity-overlay
solve-assignment
simulate
render-assignment-overlay
```

## AE transaction

```text
build-property-plan
make-ae-job --mode apply
make-ae-job --mode verify
```

Apply runner:

```powershell
python scripts\run_afterfx_job.py `
  --afterfx <AfterFX.exe> `
  --worker scripts\ae\apply_property_plan_v2.jsx `
  --job <apply-job.json>
```

Then run the verifier on the output AEP using `verify_property_plan_v2.jsx`.

## QA

```text
build-preview-qa
route-qa
validate-video
self-test
```

`validate-video` requires the original source path and its initialization SHA-256. It runs ffprobe, full ffmpeg decode, and original-source rehash.

## Commit pattern

```bash
STATE_SHA=$(python scripts/ae_stack.py state-status --run-dir <run-dir> ...)
python scripts/ae_stack.py commit-node \
  --run-dir <run-dir> \
  --node VISIBLE_LAYOUT_LOCKED \
  --artifact <visible-layout.json> \
  --expected-state-sha <captured-state-sha> \
  --gate-status PASS \
  --maturity DRAFT \
  --evidence overlay=<visible-layout-overlay.png>
```

Capture the JSON field rather than parsing the human display by hand in production automation.
