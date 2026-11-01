# Witcher 3: bounded read-only envelope inspection

Base: `b07990edc7891f1428ee3af8006cce0a06516827` (Game Assist).
This is a local research tool, not a gameplay decoder or a validated game-save reader.
No game build is supported/verified for gameplay, including classic or next-gen.
There are no real-save tests. All fixtures are synthetic envelopes with opaque,
often deliberately invalid compressed bytes.

```sh
python -m decoders.witcher3 /private/stable/directory/save.sav
python -m unittest discover -s tests -p 'test_witcher3.py' -v
```

Exit 0 means only that the envelope and compressed byte ranges passed. Exit 2
means unknown or unsupported. It does not mean the game can load the file.
The program only reads a supplied local file and writes JSON to stdout. It does
not decompress, execute file content, write/repair saves, or make network calls.

## Evidence and rights

Primary format reference is rfvgyhn's fork of Atvaark's W3SavegameEditor,
commit `d96247169f2e669bb6b7e0bd42ace79b6b07627d`, whose commit subject is
`v0.2.1` (2020-01-20). That is the **tool version**, not a Witcher game version.
Its README does not establish a supported game-build matrix.

* [Header reader](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/W3SavegameEditor.Core/ChunkedLz4/ChunkedLz4FileHeader.cs): exact `SNFH` + `FZLC`, signed little-endian count and header size.
* [Table reader](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/W3SavegameEditor.Core/ChunkedLz4/ChunkedLz4FileTable.cs): three signed 32-bit integers per chunk.
* [Container reader](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/W3SavegameEditor.Core/ChunkedLz4/ChunkedLz4File.cs) and [chunk reader](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/W3SavegameEditor.Core/ChunkedLz4/Lz4Chunk.cs): sequential compressed chunks starting at header size; end offset equals stream position or zero; LZ4 payloads.
* [README](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/README.md) and [MIT license](https://github.com/rfvgyhn/W3SavegameEditor/blob/d96247169f2e669bb6b7e0bd42ace79b6b07627d/LICENSE), copyright 2015 Atvaark.

The Python inspector is an original bounded implementation based on these format
observations. No third-party program was built/run and no game data, executable,
save or identifier mapping was copied. The reference's MIT notice is retained
below conservatively. No dependency is added.

Other research leads, not implementation/version evidence: [solusipse's
decompressor](https://github.com/solusipse/witcher3-inventory-editor/blob/master/w3_decompress.c)
agrees on the outer structure; its README marks parsing unfinished, and no license
or exact supported build was established in this review, so no code was reused.
[GwentTracker](https://github.com/vishalgupta-git/GwentTracker) declares MIT and
claims 4.0/5.0 support, but those author claims and its semantic mappings were not
validated here and do not establish Game Assist compatibility.

## Accepted structural scope

| Offset | Representation | Meaning inspected |
| --- | --- | --- |
| 0 | 8 bytes | exact `SNFHFZLC` signature |
| 8 | little-endian signed int32 | chunk count |
| 12 | little-endian signed int32 | payload start / header size |
| 16 + 12*i | three little-endian signed int32 | compressed length, declared uncompressed length, end offset |

The whole descriptor table must fit before the payload. Chunks are contiguous,
in table order, within the input. Supplied nonzero ends must equal calculated
ends; zero is accepted for any chunk, matching the reference. Opaque bytes between
the table and payload are counted but never decoded or returned. Trailing bytes
are conservatively unsupported. Positive counts/lengths are required; zero-length
chunks and empty containers are outside this inspector's accepted subset.

Resource policy: 32 MiB input, 4096 chunks, 16 MiB declared output per chunk,
128 MiB declared output total. These are implementation limits, not format maxima.
No memory is allocated for declared output or payload copies. Inspection is
O(chunk count) with constant auxiliary space, after the bounded file snapshot.

Output fields: `chunk_count`, `payload_offset`, `opaque_header_bytes`,
`compressed_payload_bytes`, `declared_uncompressed_bytes`. The last field is
untrusted declared size, not measured decompression. Provenance includes the
pinned source revision and `real_save_validation: not_performed`.

`status: known` is explicitly scoped to `envelope_and_chunk_ranges_only`.
Compressed payload validity, save-format version, game build, item state and
semantic mapping remain `unknown`. Gameplay adapter remains `unsupported`.
There is no numeric version in the inspected envelope; the exact signature is
the format gate. **No version-gated semantic decoding is attempted.** The parser
cannot identify a game from this signature alone or detect corruption that
preserves the table/ranges. Files using a different container are unsupported.

## Integration and remaining evidence gap

The API parallels the categorical local inspection contract, but is deliberately
standalone. The common dispatch, remote server, profiles, catalog and dependencies
are unchanged. `summary_supported` remains false; this output must not be fed
into Belmont's four-field `SaveSummary` or used to trigger hints. Registry approval
is not parser enablement. No inventory, health, quest, boss, pickup or missable
claims can be made from the result.

The CLI reuses `decoders.inspection.read_snapshot`: bounded double read, regular
file check, symlink rejection and stable metadata checks. It is validated on
Linux, requires a private directory with stable parent directories, and does not
claim race-proof traversal or completed Cloud synchronization. Public errors are
fixed labels without paths, hashes, private strings or file contents.

Next evidence required before expanding support: owner-authorized real fixtures
with exact platform/game build and independently recorded expected structure;
safe bounded LZ4 validation/decompression; an established inner format/version
gate; independently reviewed field semantics and spoiler-safe projection. Neither
real fixtures nor a game executable are required to run the synthetic tests.

Tests cover every prefix truncation of a synthetic multichunk envelope, signed
integers, table and payload bounds, wrong end offsets, zero sentinels, trailing
data, policy boundaries, deterministic byte mutations, opaque-payload caveats,
unchanged runtime dispatch, read-only CLI behavior, and directory/symlink/FIFO
rejection. They prove these implementation properties only.

First-stage validation on the base above plus the original three files: 9 Witcher-specific tests
passed; full unittest discovery ran 728 tests, OK with 104 skipped. Registry and
catalog validation and Python compilation passed. Skipped tests and absence of
real-save validation are not counted as compatibility evidence.

The later CLI privacy fix and optional LZ4 step are separate incremental patches.
See [optional LZ4 validation](witcher3_lz4.md) for its own tests and limitations;
the first-stage figures above do not include that work.

## Reference MIT notice

The MIT License (MIT)

Copyright (c) 2015 Atvaark

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
