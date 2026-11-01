# BND4 directory investigation and CLI privacy correction

This is an incremental follow-up to `elden-ring-b07990e.patch`, SHA-256
`db2903a2dcc909760978cc9bf92816d35f27f89525a70658f35ecce7ed8a97b9`,
on repository base `b07990edc7891f1428ee3af8006cce0a06516827`.
The original delivered patch is unchanged.

## Outcome

The CLI now handles argparse failures using a fixed error category and a fixed
program label. Unknown options, extra arguments and missing option values no
longer print user-controlled text to stderr. The correction adds sentinel
regressions for both stdout and stderr, including static help and path failures.

**No directory parser is added.** The compatible sources below establish useful
field candidates but do not establish a safe variant-selection rule for this ER
layout. Guessing that every 32-byte record has one meaning would strengthen the
claim beyond the evidence. `bnd4_directory_status` therefore remains `unknown`.
This is an evidence limitation, not a tool denial or an access request.

## Primary sources inspected

1. **usrbinsam/bnd4**, revision
   `1952e6b092cc22bb3992f5bf09d81d9bf4366afc`, package 0.1.0,
   [BSD-3-Clause license](https://github.com/usrbinsam/bnd4/blob/1952e6b092cc22bb3992f5bf09d81d9bf4366afc/LICENSE).
   Its [header declaration](https://github.com/usrbinsam/bnd4/blob/1952e6b092cc22bb3992f5bf09d81d9bf4366afc/src/header.rs)
   gives a 64-byte little-endian header, including count, entry-header size,
   data offset and Unicode flag. Most flag bytes remain unknown.
   Its [entry declaration](https://github.com/usrbinsam/bnd4/blob/1952e6b092cc22bb3992f5bf09d81d9bf4366afc/src/entry_header.rs)
   always consumes 32 bytes: padding u64, size u64, data offset u32, name offset
   u32, unused u64. Its [reader](https://github.com/usrbinsam/bnd4/blob/1952e6b092cc22bb3992f5bf09d81d9bf4366afc/src/file.rs)
   does not select or reject record variants using format flags or the declared
   entry-header size. The ER unit test only opens a fixture and prints the header;
   it does not assert directory variant or exact game-build compatibility.
   The [README](https://github.com/usrbinsam/bnd4/blob/1952e6b092cc22bb3992f5bf09d81d9bf4366afc/README.md)
   describes ported reverse-engineering work but does not identify its upstream
   provenance. No source code was copied or translated; fixture bytes were not
   fetched, and the library was not executed.

2. **soulsmods/fstools-rs**, revision
   `1931951a9937e900a6071e5b29dc6c190774430c`,
   [MIT](https://github.com/soulsmods/fstools-rs/blob/1931951a9937e900a6071e5b29dc6c190774430c/LICENSE-MIT)
   and Apache-2.0 license files.
   Its [BND4 source](https://github.com/soulsmods/fstools-rs/blob/1931951a9937e900a6071e5b29dc6c190774430c/crates/formats/src/bnd4.rs)
   names little-endian header fields including raw format, extended mode and
   buckets offset. The entry reader always consumes 36 bytes, including both
   compressed/uncompressed sizes, a data offset, ID and name offset. It records
   raw format and header size but does not use them to select/reject entry
   variants. It does not establish the ER save-directory/checksum relationship
   or a tested ER save game-build matrix. No code was reused or executed.

3. **ClayAmore/ER-Save-Editor**, pinned MIT source already documented in
   `elden_ring_inspector.md`: the PC header is copied as an opaque 0x300-byte
   region, not parsed into directory records. It confirms fixed checksum
   regions but cannot independently settle the directory mapping.

4. **ClayAmore/EldenRingSaveTemplate**:
   [repository](https://github.com/ClayAmore/EldenRingSaveTemplate).
   Repository metadata reports no license; the inspected SL2 template prologue
   does not grant one. It is not a compatible implementation source for this
   delivery. **SoulsFormats/SoulsFormatsNEXT** and
   **Kalmarv/fromsoft-formats** report GPL-3.0 licensing and were excluded from
   implementation reuse. Public availability is not treated as permission to
   copy code into this MIT project.

## Exact remaining evidence gap

Before implementing directory validation, establish from a compatible primary
source the relationship between header bit ordering/format flags and record
layout: compressed-size fields, optional uncompressed size, data-offset width,
optional ID, name offset, and any padding. Also establish accepted header
version/extension values, bounded name encoding/termination, and whether each
ER directory extent includes its preceding 16-byte checksum. A generic BND4
parser or a fixed total file size alone does not establish those ER rules.

After that, implement bounds before every read, bounded record/name loops,
non-overlapping directory/name/data ranges, directory-to-checksum extent
agreement, and rejection of unsupported variants. Tests must cover malformed
counts/flags/sizes, overlaps, out-of-range names/offsets, truncation and trailing
data. Such acceptance/rejection tests would currently be based on guessed
fixtures, so **no claim that malformed or overlapping BND4 directories are
detected is made**. The existing opaque-header regression explicitly shows that
matching checksums leave directory validation unknown.

No game executables, third-party player saves, regulation payloads, new access,
writer/cheat functions or runtime gameplay capabilities are involved. Exact
game-build support and real-save validation remain unestablished.
