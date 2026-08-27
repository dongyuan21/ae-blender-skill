# State Machine and Receipts

## Why receipts exist

A phase label in a prompt is not a durable state. v2 records every attempt as an immutable receipt and keeps only a CAS-updated pointer in `state/current.json`.

Each receipt contains:

- run ID;
- monotonically increasing sequence;
- node and attempt;
- gate status and maturity;
- parent receipt hash;
- prerequisite receipt hashes;
- main artifact path/hash;
- evidence artifact paths/hashes;
- metrics and typed issues;
- retry target;
- invalidated descendants;
- next eligible nodes;
- producer identity.

## CAS rule

A worker reads `stateSha256` before work and supplies it to `commit-node`. If another worker commits first, the stale worker fails. It must reread state and determine whether its artifact is still applicable.

Do not retry a CAS mismatch by substituting the new hash without rechecking upstream artifact hashes.

## PASS, REVISE, BLOCKED

- `PASS`: validates and becomes the active authority for its node. Any active descendants are invalidated because their lineage used an older attempt.
- `REVISE`: records the failed attempt, invalidates this node and descendants, and leaves its prerequisites active.
- `BLOCKED`: same invalidation semantics as REVISE, but indicates safe progress cannot continue without an external resolution.

## Maturity

- `DRAFT`: evidence or logical artifact; not an AE write authorization.
- `CANDIDATE`: isolated AEP/preview may exist, final visual/technical promotion incomplete.
- `FINAL`: all downstream gates pass.

Maturity does not override gate status.

## Parallel source/reference branches

After capability preflight, these can proceed independently:

```text
SOURCE_ROUTE -> BOARD_INVENTORY -> EVENT_MODEL
REFERENCE_ROI -> VISIBLE_LAYOUT -> DEPTH_EVIDENCE
```

They converge at `CAPACITY_RECONCILED`. A source-branch retry does not invalidate reference artifacts unless the changed source count or facts affect capacity and descendants; the DAG handles this through convergence lineage.

## Manual invalidation

Use:

```bash
python scripts/ae_stack.py invalidate \
  --run-dir <run-dir> \
  --from-node <NODE> \
  --reason "<typed reason>" \
  --expected-state-sha <sha>
```

This invalidates the named node and descendants. Never delete receipts.

## Receipt examples

A PASS receipt may report:

```json
{
  "node": "VISIBLE_LAYOUT_LOCKED",
  "attempt": 2,
  "gateStatus": "PASS",
  "maturity": "DRAFT",
  "prerequisiteReceipts": {
    "REFERENCE_ROI_LOCKED": "..."
  },
  "mainArtifact": {
    "name": "visible-layout",
    "path": ".../visible-layout-attempt-02.json",
    "sha256": "..."
  },
  "evidenceArtifacts": [
    {"name": "full-overlay", "path": "...", "sha256": "..."}
  ]
}
```

A preview REVISE attempt may set `retryFrom` after `route-qa` chooses the earliest authority node.
