# AE Transaction and Route-Scoped QA

## Isolation

All AE operations target files below:

```text
<library>/.staging/<run-id>/
```

The original source AEP is copied and hashed during `init-run`. It is never opened or saved by the JSX workers. `run_afterfx_job.py` hashes:

- staged input before/after;
- protected original before/after;
- dependency lock files before/after;
- output AEP after save.

Input and output AEP paths must differ.

## Inspect worker

`inspect_stack_v2.jsx` is read-only and returns:

- comp metadata;
- complete layer snapshots;
- tile/mover/hand pattern candidates;
- static/mover pair candidates;
- route-scoped missing footage;
- route-scoped expression errors;
- watermark layers;
- baseline issue keys.

Name patterns only produce candidates. GPT classification plus deterministic identity checks lock the inventory.

## Property transaction

The plan targets only `ADBE Position` and optional `ADBE Scale`. Every target includes comp ID, layer index/name, source ID, expected key count, expected old values, and new values.

For keyed Position:

- the settled key moves to the assigned slot;
- on-screen keys translate by the same delta;
- clearly offscreen vertical keys preserve Y and only adopt the target X, avoiding entry/exit path damage.

Mover start keys and bound hand keys move to the same tile target with their locked offsets.

## Apply worker

`apply_property_plan_v2.jsx`:

1. verifies staging paths and plan safety flags;
2. validates dependency/disabled-layer locks;
3. validates every expected old property value;
4. applies one undo-group transaction;
5. validates in-session readback;
6. saves to a distinct output AEP;
7. evaluates route-scoped regressions;
8. closes without additional saves.

In-session readback is necessary but not sufficient.

## Fresh reopen verifier

`verify_property_plan_v2.jsx` opens the output AEP in a separate worker invocation and validates:

- exact planned values;
- dependencies;
- required disabled layers;
- route-scoped missing footage;
- route-scoped expression errors;
- enabled watermarks.

The Python runner then adds the external hash proof required by the `apply-readback` contract.

## Route baselines

The canonical baseline keys are:

```json
{
  "acceptedMissingKeys": [],
  "acceptedExpressionErrorKeys": [],
  "acceptedEnabledWatermarkKeys": []
}
```

A historical project-wide defect does not block a candidate unless it is route-critical or becomes a new regression. Do not silently accept a new issue by adding it to the baseline after apply; the baseline is locked with the source route before edits.

## Windows execution pattern

```powershell
python scripts\ae_stack.py make-ae-job ...
python scripts\run_afterfx_job.py `
  --afterfx "C:\Program Files\Adobe\Adobe After Effects 2026\Support Files\AfterFX.exe" `
  --worker scripts\ae\inspect_stack_v2.jsx `
  --job <job.json>
```

Use the apply worker for a staged input/output pair, then the verify worker on the output. Keep the full runner stdout and result JSON in the run logs.
