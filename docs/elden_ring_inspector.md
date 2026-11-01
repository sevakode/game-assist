# Elden Ring: local fixed-region checksum inspection

Base: `b07990edc7891f1428ee3af8006cce0a06516827`.

This delivery is a read-only research diagnostic, **not game-save decoding or
verified gameplay support**. It answers whether one source-described PC byte
layout has the expected total extent and matching per-region checksums. It can
flag a checksum mismatch without exposing the save's contents. It cannot say
whether the game will load a file, whether it is authentic, which character is
active, or whether an item/boss/quest is present or absent.

## Use and contract

```sh
python -m decoders.elden_ring /private/local/snapshot.sl2
python -m unittest discover -s tests -p 'test_elden_ring.py' -v
```

`inspect_bytes(bytes, layout_id="er-pc-fixed-regions-v1")` returns only fixed
categories and source provenance. The layout identifier is our research scope,
**not a save-format version or game version**. Unknown layout identifiers,
non-BND4 inputs and unequal byte extents are unsupported. Short signatures,
invalid types, oversized inputs, unavailable checksum algorithms and mismatching
checksums fail closed. A size mismatch may mean truncation, trailing data or a
different layout; it is not proof of corruption.

Exit 0 / `status=known` means only `inspection_scope=fixed_region_checksums_only`:
the exact size and all twelve comparisons passed. `checksum_status` is
`match`, `mismatch` or `unknown`. The recognized structural category is only
`bnd4_signature_and_fixed_extent`. No save-derived numbers, strings, digests,
identifiers, filenames or paths are returned.

Argument errors return exit 2 with fixed `reason=invalid_arguments` JSON and
empty stderr. The CLI overrides argparse's error reporter and fixes its program
label so unknown arguments, extra paths and the executable path are not echoed.
`--help` prints static help and exits 0.

All of `game_identity_status`, `game_build_status`, `save_format_version_status`,
`bnd4_directory_status`, `payload_structure_status`, `semantic_mapping_status`
and `collected_item_status` remain `unknown`, even after success. In particular,
the bytes after the magic in the 0x300-byte header are opaque. A malformed BND4
directory can still have matching region checksums. The test suite deliberately
demonstrates this limitation instead of claiming full container validation.

No runtime dispatch, `summary_supported`, Belmont `SaveSummary`, registry,
catalog, HTTP/MCP surface or dependency changes are made. The existing general
inspector still returns Elden Ring as unsupported. Future integration must not
reinterpret checksum matches as verified game capabilities.

## Evidence and byte layout

The implementation is independently written Python using standard-library
hashing, from the following primary source descriptions. No upstream program,
script, game executable, regulation database or player save was downloaded or
executed. No third-party implementation is vendored.

Primary source: ClayAmore/ER-Save-Editor, pinned commit
`014107f0ca1cff867b5f7565cb79d6684f9b35df`, package version **0.0.22** (the tool
version, not an Elden Ring build). The repository carries MIT and Apache-2.0
license files; the consulted source is available under its
[MIT notice](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/LICENSE-MIT).
The [README](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/README.md)
describes PC and exported PlayStation saves, but supplies no exact tested game
build matrix. **Supported/tested game builds in this delivery: none established.**
PlayStation, compressed/encrypted wrappers and changed layouts are unsupported.

| Evidence | Limited fact used |
| --- | --- |
| [PC header](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/pc/save_header.rs) | Opaque 0x300-byte prefix |
| [PC save](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/pc/pc_save.rs) | Ten slot records, then user data 10 and 11 |
| [PC slot](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/pc/save_slot.rs) and [slot extent](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/common/save_slot.rs) | 16-byte MD5 followed by 0x280000 bytes; upstream checksum calculation establishes covered range |
| [User data 10](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/pc/user_data_10.rs) | 0x60010 total; initial 16-byte MD5 covers remaining 0x60000 bytes |
| [PC user data 11](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/pc/user_data_11.rs) and [extent](https://github.com/ClayAmore/ER-Save-Editor/blob/014107f0ca1cff867b5f7565cb79d6684f9b35df/src/save/common/user_data_11.rs) | Initial 16-byte MD5 covers 0x10 + 0x1e9fb0 + 0x56050 = 0x240010 bytes |

The total is 0x300 + 10 * 0x280010 + 0x60010 + 0x240020 =
**0x1ba03d0 (28,967,888) bytes**. These are container extents, not player or
collectible counts. No payload structure or regulation data is interpreted.
MD5 is used only to compare existing file-format checksums. It is not an
authentication mechanism. This module has no writer or repair facility.

Additional research, not copied into the implementation:

- [BenGrn/EldenRingSaveCopier SaveGame.cs](https://github.com/BenGrn/EldenRingSaveCopier/blob/273ac414a4de088b397d0e005f23bcf5169c4369/EldenRingSaveCopy/Saves/Model/SaveGame.cs),
  [MIT](https://github.com/BenGrn/EldenRingSaveCopier/blob/273ac414a4de088b397d0e005f23bcf5169c4369/LICENSE):
  independently agrees on slot payload start 0x310, payload size 0x280000,
  16-byte spacing and user data payload start 0x19003b0. Its broad version claim
  is not an exact build validation and is not adopted.
- [ClayAmore/ER-Save-Lib](https://github.com/ClayAmore/ER-Save-Lib) was considered;
  the inspected root did not establish a license. No code was reused.
- [SoulsFormatsNEXT BND4](https://github.com/soulsmods/SoulsFormatsNEXT/blob/master/SoulsFormats/Formats/Binder/BND4/BND4.cs)
  was considered for directory parsing; its [GPL-3.0 license](https://github.com/soulsmods/SoulsFormatsNEXT/blob/master/LICENSE)
  was identified. No code was copied, translated, linked or vendored; directory
  parsing is outside this delivery.

## Bounds, privacy and verification limits

The byte API accepts immutable `bytes` only and caps input at 32 MiB before
hashing. Exact extent gating precedes twelve constant-size slices. The inspector
never follows offsets/counts from untrusted input, allocates payload copies,
decompresses, decrypts, imports code, executes data or makes network requests.
Hashing is linear over about 29 MB; the memoryview adds no payload copy.

The CLI reuses the existing local snapshot reader: bounded double read,
regular-file check, symlink rejection and inode/size/time stability checks.
Use private stable parent directories on Linux. This is not race-proof hostile
directory traversal or proof that Steam Cloud synchronization has finished.
Two raw snapshots may occupy about 64 MiB while checking stability. Reads may
update filesystem access time; save contents and modification time are unchanged.

Tests use fabricated checksum envelopes, intentionally not real BND4 directories
or real game saves. They cover every region's checksum and both payload ends,
truncation, trailing bytes, unsupported layout/signature, type/size gates, opaque
header limitations, checksum-provider failure, redaction, read-only CLI and
unchanged runtime dispatch. Existing snapshot tests cover concurrent mutation.
Sentinel regressions check stdout and stderr for malformed CLI arguments, private
paths and help with a private program name. See `elden_ring_directory_research.md`
for the follow-up investigation of why directory validation remains unknown.

The evidence gap is explicit: no consented real fixture report, exact game-build
matrix, directory validation, active-slot selection, payload-version validation
or reviewed gameplay mapping. Those are prerequisites for future gameplay
capability work, not reasons to infer zero/absent progress now.

## Source attribution

For the primary MIT source, retain the notice:

MIT License

Copyright (c) 2024 ClayAmore

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
