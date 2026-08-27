# JSON Schemas

These Draft 2020-12 schemas document the public artifact boundary of the Skill. They are intentionally strict around authority-bearing fields, especially `assignment.assignments[]`, source-event facts, capacity provenance, and Property Plan safety flags.

The Python validators in `scripts/ae_stack_runtime/contracts.py` remain the execution authority because they also enforce cross-field invariants, unique identities, hash lineage, acyclic front/back constraints, and AE-specific semantics that JSON Schema alone cannot express.
