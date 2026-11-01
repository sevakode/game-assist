# Optional bounded Witcher 3 LZ4 step

Apply after `witcher3-b07990e.patch` and `witcher3-cli-privacy-fix.patch`, whose
base is `b07990edc7891f1428ee3af8006cce0a06516827`. The original patch artifacts
remain unchanged. This step validates raw LZ4 blocks inside the already reviewed
SNFHFZLC envelope. It does not interpret the decompressed format or game state.

## Dependency and provenance

Optional requirement: `decoders/witcher3-requirements.txt`, `lz4==4.4.5`.
Main/server requirements and runtime capability flags are unchanged.

* [Official PyPI release](https://pypi.org/project/lz4/4.4.5/): Python >=3.9, native wheels available. This run used CPython 3.12.14 on Linux x86-64 and its published manylinux wheel.
* [Pinned wrapper source](https://github.com/python-lz4/python-lz4/blob/59b2d8176072bdee50d38cc68ec65c33b928a980/lz4/block/_block.c#L259), tag v4.4.5: explicit capacity is passed to `LZ4_decompress_safe_usingDict`; compressed source length is provided. No dictionary is supplied by our caller.
* [API documentation](https://python-lz4.readthedocs.io/en/stable/lz4.block.html): explicit `uncompressed_size` is a capacity; the wrapper can return fewer bytes. Our exact-size check is therefore mandatory. The online stable docs identify themselves as 4.3.2; the pinned 4.4.5 C implementation was checked as well.
* [Bindings license](https://github.com/python-lz4/python-lz4/blob/59b2d8176072bdee50d38cc68ec65c33b928a980/LICENSE): BSD-3-Clause, Steeve Morin. [Bundled LZ4 notice](https://github.com/python-lz4/python-lz4/blob/59b2d8176072bdee50d38cc68ec65c33b928a980/lz4libs/lz4.h): BSD-2-Clause, Yann Collet. Preserve package notices when distributing dependencies; no third-party implementation is vendored in this patch.

The Witcher container evidence and retained Atvaark MIT notice are in
[witcher3.md](witcher3.md). The reviewed reference decodes each chunk without a
shared dictionary, motivating independent raw block calls. This remains source
evidence, not a real-save compatibility test. No third-party build scripts were
run; installation used a published binary wheel with source-build fallback disabled.

## Boundaries

`decompress_bytes` first validates the entire envelope, every chunk range and
every budget, before loading the dependency or calling native code. It accepts
immutable bytes only. Limits are conservative tool policy, not game-format maxima:

| Resource | Limit |
| --- | --- |
| Input snapshot | 32 MiB |
| Number of blocks | 4096 |
| Compressed block | 16 MiB |
| Declared output per block | 16 MiB |
| Total declared and actual output | 64 MiB |

The 64 MiB output limit intentionally narrows the envelope inspector's 128 MiB
declaration limit because this step actually allocates output. Positive lengths,
complete compressed ranges and exact end offsets are required by the envelope
layer. There is no speculative buffer growth, retry, frame fallback, external
dictionary, nested decompression, or unchecked size prefix. Each returned block
must have exactly its declared length. Native error text is discarded.

Input blocks use memoryview slices. Output remains a tuple of independent byte
strings without a second whole-output concatenation. Account for native temporary
buffers and Python object overhead in addition to logical budgets; these limits
are not an OS-level RSS or wall-clock limit. Native code is not a sandbox. A future
remote integration would require its own worker resource/concurrency policy.

The `PrivatePayload` object has no content-bearing repr and is returned only when
all blocks succeed. No iterator, callback or partial result is exposed. Callers
must keep its bytes local and never serialize them into logs, HTTP or MCP. The
public `inspect_bytes` and CLI return fixed statuses, bounded numeric metadata
and dependency provenance only. Successful validation says
`compressed_payload_status: validated_lz4_blocks`; game identity/build, inner
format version, items, quests and all other semantic fields remain unknown.
Missing dependency or a version other than 4.4.5 is explicitly unsupported.

No output-file or writer option is provided. Existing snapshot safety and fixed
CLI argument errors are reused. `summary_supported` and gameplay dispatch remain
disabled. The inner format is not parsed, and valid LZ4 is not proof of a valid
Witcher save. No real fixture, game executable or user progress was used.

## Reproduction and tests

```sh
python -m venv /tmp/witcher3-lz4-venv
/tmp/witcher3-lz4-venv/bin/python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r decoders/witcher3-requirements.txt
/tmp/witcher3-lz4-venv/bin/python -m unittest discover -s tests -p 'test_witcher3*.py' -v
/tmp/witcher3-lz4-venv/bin/python -m decoders.witcher3_lz4 /private/stable/directory/save.sav
```

Validation: 19 focused tests passed with lz4 4.4.5 installed, **zero skips**.
These comprise 10 prior envelope/CLI tests, 2 dependency/preflight tests and 7
native-code tests. Native tests compress synthetic bytes with `store_size=False`
then exercise real decompression, including truncated/malformed blocks, smaller
and larger declarations, exact budget boundaries, and failure of the second block
after a successful first block. Additional mocks specifically check fixed error
messages and that all preflight failures occur before dependency/native calls.

Without the optional package, native tests explicitly skip; those skips are not
evidence of decompression working. The required native test run above did execute
them. Full discovery in the original environment without lz4 ran 738 tests,
OK with 111 skips (104 existing plus 7 optional native tests); the separate venv
run supplied the actual native validation. `pip check` in the venv passed.
Further support still requires owner-authorized, exact-build fixtures and
an independently reviewed inner-format/version gate.
