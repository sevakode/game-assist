# Selected Belmont container inspection

This local research module is separate from the four-field reader, MCP and API.
It consumes bytes or one explicitly selected stable copy; it writes nothing.

```sh
python -m decoders.belmont_structure /private/selected-copy.sav
python -m unittest discover -s tests -p test_belmont_structure.py -v
```

Evidence basis: the parent task reported redacted structural observations from
an owner-authorized read-only sample on 2026-11-01. This development environment
has **not** obtained or independently inspected that sample. Its Library transfer
failed and remains stopped. Public fixtures are small invented structures; they
do not reproduce private cardinalities, values, IDs or distributions. The parent
subsequently reported that API and CLI agreed on all five selected checks as
known on that authorized copy, with semantics still unknown and source integrity
unchanged. This is parent-reported validation, not a new local fixture run.

The exact supported format label is `1.1.3`; this is not an installed game build.
The selected checks are:

| Check | Type/shape checked | Meaning not established |
|---|---|---|
| `exploration_map` | `playerSave.worldRoomExplorationStates`: parallel unique string keys and JSON-string object values | Room identity, visited state |
| `chunks_arrays` | Each decoded object's `chunksExplorationState` is an array of exact JSON integers | Enum meanings, coverage, map percentage |
| `secret_arrays` | Each decoded object's `discoveredSecretZones` is an array of exact JSON integers | Secret identity, collection, permanent discovery |
| `world_map` | `worldSaves`: parallel unique string keys and object values | Human-readable world/location |
| `completion_counters` | Each world object's `currentCompletionItemCount` is an exact JSON integer | Progress, completed items, denominator |

`known` means only that all selected type/shape checks succeeded. Overall status
is `unknown` when selected fields are missing/null/wrongly typed, and unsupported
versions are `unsupported`. A malformed parallel map, duplicate JSON key, invalid
nested JSON or exhausted budget invalidates the inspection. No missing value is
converted to false or zero. A valid empty map has known container shape but unknown
child-field checks; valid empty arrays have known array shape only.

Additional object fields are allowed and not projected, but still consume the
shared traversal budget. This is a reduced inspection, not an exhaustive schema.
Integers are not assigned an enum range, uniqueness or nonnegative rule from one
sample. Booleans and decimal JSON numbers are rejected for the selected integer
fields. Negative/repeated/large integers in synthetic cases test this deliberate
absence of unsupported semantic constraints, not actual game values.

Limits reuse the existing reader's outer byte, node, depth, parallel-map and
nested-string safeguards. One node budget spans the outer JSON and every decoded
target string; nested byte and per-JSON-document depth caps also apply. Only
these target strings are recursively decoded. Existing entity-state semantics,
coordinates, spawn state and location IDs are not added to this inspector.

The return value/repr and CLI contain fixed statuses/reasons only: no raw strings,
collection sizes, scalar values, hashes, IDs, locations or inferred completion.
Exit 0 means selected structural checks passed; exit 2 means unavailable, incomplete
or unsupported; exit 130 means interrupted. Semantic mapping and collected-item
status are always unknown. Existing `belmont.safe_summary` is unchanged.

Next evidence: to establish meaning, use separately controlled
HP/mana, single-item, boss-transition and exploration before/after observations
with exact build/platform context, no-action controls and independent in-game
confirmation. A single sample cannot settle any of these mappings; see
[SAVE_CAPTURE.md](SAVE_CAPTURE.md). No transfer retry or new private file is needed
for the parent's structural validation.

## Integration checkpoint

Prepared against main `b07990edc7891f1428ee3af8006cce0a06516827`. That tree
contains `belmont.py` and `inspection.py` but not this selected-container module.
Both dependencies are byte-identical to the versions used for the earlier
parent-reviewed structural patch. The inspector implementation is unchanged;
this integration adds explicit exact-limit tests for outer bytes, UTF-8 nested
bytes, the combined node budget and parallel-map cardinality, plus outer depth
and non-finite unknown-field rejection. No new semantic coverage is asserted.

No `.agents/skills` or `AGENTS.md` instructions were present in the checked tree.
No existing decoder, registry pin, scalar projection, server, UI or device files
are modified by this integration. It is not a full parser for every unknown
field of the save: unclassified fields stay bounded and unprojected.
