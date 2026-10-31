# Local structural inspection and controlled comparisons

This developer tool is **not connected to MCP, the hosted server, or Deck**.
It does not produce trusted `ParserEvidence`, pickup IDs, hints, completion
percentages, or an attestation. Existing `safe_summary`, profile registry,
reader revision pins and BEL-01 evidence schemas are unchanged.

## Supported scope

| Selected AppID | Format gate | Result |
|---|---|---|
| Belmont `4231820` | Existing reader validates JSON `1.1.3` | `known` **structure only**; existing four-scalar safe summary; categorical comparison |
| Elden Ring `1245620` | First four bytes may equal `BND4` | `unsupported`; optional `bnd4_signature_only` observation, not header/container/slot validation |
| Witcher 3 `292030` | No format enabled | `unsupported`; no guessed magic or decompression |
| Other AppID | No adapter | `unsupported` |

Invalid/missing/unstable input is `unknown`; a non-supported pair has
`structural_changes_detected: null`, never false. Game build, semantic mapping
and collected-item status always remain `unknown`. `known` does not mean the
maximum resource, collected upgrades, a valid ER save, or a known game patch.
No real private save was available or tested in this development environment.

The ER signature reference is the author's
[BND4 implementation](https://github.com/JKAnderson/SoulsFormats/blob/master/SoulsFormats/Binder/BND4/BND4.cs).
Its [LICENSE](https://github.com/JKAnderson/SoulsFormats/blob/master/LICENSE)
was inspected on 2026-10-31 and says GPL-3.0. No source, dependency, binary,
header parser or table from that project is incorporated or executed here.
The signature observation alone does not expand the published ER coverage.
A future full adapter requires a pinned source/licensing review and exact
format/build evidence; the repository's MIT license is not a blanket permission.

## Run locally on deliberately selected copies

Use a private directory outside the repository; Linux file reading is the
validated platform. Parent directories must not be concurrently changed.
No recursive search, account access, Cloud download, or save write occurs.
The file reader double-reads a regular file with size/metadata checks, rejects
symlinks and limits input to 32 MiB. This is not proof of Cloud synchronization
or a sandbox against malicious filesystem races. Parsing is in-process with
the existing reader's depth/node limits, not an isolated timed worker.

```sh
python -m decoders.inspection --appid 4231820 /private/selected-copy.sav
python -m decoders.inspection --appid 4231820 /private/before.sav --compare /private/after.sav
python -m unittest discover -s tests -p test_inspection.py -v
```

Exit 0 means the narrow structural operation succeeded. Exit 2 means unsupported
or unavailable input. Output contains no paths, filenames, hashes, raw nested
values, world/entity IDs or entity counts. Inspection retains the already
allowlisted four scalar values; comparison emits **categories only**.
Do not copy shell command histories with personal paths into public reports.

Comparison preserves integer/decimal/boolean/string/null distinctions and
uses exact decimal parsing, so small decimal changes cannot vanish through
float rounding. Missing is separate from null/zero. Object key ordering is
ignored; array ordering is never normalized or treated as entity identity.
Duplicate JSON keys and malformed nested entity JSON are rejected by the
existing reader. Nested encoded entity strings are compared as opaque strings:
whitespace changes inside them can flag an unknown change; their fields are
not classified. An outer array difference is `positional_only`.

All outer JSON fields participate in comparison, including unclassified noise.
Any unclassified change produces `other_unknown / unknown`; this deliberately
blocks a clean control review. Missing scalar observations also remain unknown.
This is a conservative candidate generator, not a way to automatically pass
BEL-01. No private correspondence map or candidate-item flag is inferred.

## Minimal observations needed next

For **one** HP or mana pickup, keep the following locally with owner consent:

1. Exact installed game build, platform, DLC/mod context, format version;
   confirmation that copies refer to the same selected slot/playthrough.
2. A stable no-action control pair, one stable immediately-before/after pair
   for a single pickup, and a comparable independent repeat with its control.
   No save editing/rollback is required or authorized by this protocol.
3. Independently observed current resource, explicitly displayed maximum,
   fragment counter if visible, and whether spending, healing, autosave,
   another pickup or random events occurred. Unknown observations stay unknown.
4. Run each pair locally. Copy only categorical `observations` into trials in
   the existing `knowledge/evidence_template.json`; fill capture, consent and
   ground-truth fields truthfully. Never set them automatically from this tool.
5. A reviewer must examine any unclassified/positional changes locally, establish
   stable per-item correspondence independently, and review redaction and exact
   build/revision scope. A clean scalar delta alone cannot establish pickup
   identity. `review_blockers()` checks readiness, not factual truth.

Without those observations, HP/mana maxima, completed upgrade counts, pickup
mapping and spoiler-safe missable reminders remain unknown. For ER and W3,
first obtain a selected, consented local fixture and version/platform context;
this tool does not infer progress from their unsupported state.
