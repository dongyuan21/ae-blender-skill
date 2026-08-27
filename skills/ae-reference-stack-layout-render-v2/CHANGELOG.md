# Changelog

## 2.0.0

- Replaced the monolithic phase prompt with an immutable receipt DAG and CAS state updates.
- Split source behavior, visible reference geometry, hidden capacity, and assignment into separate authority artifacts.
- Restricted assignment rows to `tileId` and `slotId` only.
- Added canonical source-fact hashing and downstream lineage verification.
- Added deterministic capacity reconciliation, assignment solver, click-accessibility simulation, and occlusion-order validation.
- Added independent proposer/reviewer prompt contracts.
- Added route-scoped missing-footage/expression/watermark QA with accepted baselines.
- Added isolated AE property transactions, expected-old checks, duplicate-key coalescing, conflict rejection, and fresh reopen/readback.
- Added typed QA failure routing.
- Added a 40-visible/57-physical Golden Fixture and packaged regression suite.
- Added strict Draft 2020-12 schemas for the source event model, visible layout, capacity plan, assignment, simulation report, property plan, and immutable receipts.
- Hardened capacity provenance/count/bounds/DAG validation and apply-readback external hash proof.
- Added a package-level offline validator and 12 regression tests.

