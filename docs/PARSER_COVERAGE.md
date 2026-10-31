# Read-only save parser coverage — research gate

Checked **2026-10-31**. This is source research, **not implemented or validated game support**. No third-party executables/packages were downloaded or run during this research pass. Later authorized private-fixture findings are recorded below; no raw player saves are included in this repository. Sources below are project authors' repositories/docs. They may contain spoilers: do not open them automatically in the player UI.

## Decision summary

| Steam game | Current defensible position | Quest / inventory / boss / missable coverage |
|---|---|---|
| Castlevania: Belmont's Curse — `4231820` | No reusable, licensed, version-tested parser established in this review | All unknown in Game Assist; never infer completion from file metadata |
| Elden Ring — `1245620` | Later parsing candidate; permissive but partial candidates exist | Some event facts feasible; inventory depends on candidate; missability requires separate tested rules |
| The Witcher 3 — `292030` | Legacy decoding reference exists, but current-build semantic support unproven | Generic variables are not verified quest/inventory/boss facts; all four remain gated |

Steam achievements are account evidence, not a complete per-character, current-playthrough inventory or quest state. A locked achievement is not proof of a missed opportunity. No candidate establishes a spoiler-free “all achievements guaranteed” planner.

## Implementation priority

The user's first priority is **Belmont's Curse HP/mana pickup mapping**, not Elden Ring. Start with consented paired saves immediately before and after **one** known pickup on the exact game version, plus independently recorded in-game ground truth. Increased maximum HP/mana alone does **not** identify which pickup was collected or establish an item/location ID. Distinguish a verified pickup ID from an aggregate stat change; unresolved mappings stay unknown. A community world/location database is a separate enrichment source with its own provenance, license and spoiler controls—not proof that a particular save contains that pickup.

## Elden Ring candidates

### 1. Small read-only TypeScript spike: `zebbedaja/er-save-parser`

- [README](https://github.com/zebbedaja/er-save-parser) targets PC saves, exposes character slots and selected event flags, and explicitly leaves equipment/inventory on its TODO list.
- [Actual parser](https://github.com/zebbedaja/er-save-parser/blob/main/src/parser.ts) **skips inventory, storage and equipment**; decodes a bundled event-flag list. [Types](https://github.com/zebbedaja/er-save-parser/blob/main/src/types.ts) expose raw version fields, not a compatibility guarantee. Do not advertise inventory or comprehensive quest coverage.
- [LICENSE inspected](https://github.com/zebbedaja/er-save-parser/blob/main/LICENSE): MIT, copyright 2026 Daniel Zsebedits. Preserve notices if reused; separately audit dependency/data provenance.
- Input-buffer parsing suits an isolated read-only adapter. Latest commit date/release support matrix was not established (commit-history fetch failed); repository availability is not proof of maintenance. No patch/DLC/Proton compatibility validated here.

### 2. Python alternative: `Hapfel1/elden-ring-save-parser-lib`

- [README](https://github.com/Hapfel1/elden-ring-save-parser-lib) advertises character, inventory and equipment parsing plus editing/repair. [LICENSE inspected](https://github.com/Hapfel1/elden-ring-save-parser-lib/blob/main/LICENSE): MIT, copyright 2025 Hapfel.
- [save.py inspected](https://github.com/Hapfel1/elden-ring-save-parser-lib/blob/main/elden_ring_save_parser_lib/save.py): `from_file` opens binary read-only, recognizes PC/PS signatures and delegates slot decoding. **Exceptions can become empty slot objects**, so an adapter must not translate parse failures into “not obtained.” The object also retains the original path for saving: never expose its write/repair API.
- Inventory semantics, DLC coverage, version matrix and current maintenance were not established. This is a separate repository from the manager below: neither its license nor capabilities automatically transfer.

### 3. Maintained research lead, NOT a distributable dependency: `Hapfel1/er-save-manager`

- [Author releases](https://github.com/Hapfel1/er-save-manager/releases) show v2.3.0 dated 2026-10-19. [README](https://github.com/Hapfel1/er-save-manager) describes inventory, event flags, quest tracking, pickups and world-state tools, but also extensive save mutation.
- [Actual LICENSE inspected](https://github.com/Hapfel1/er-save-manager/blob/main/LICENSE) is **custom Source-Available**, not MIT or copyleft open source. It restricts redistribution, bundling and use in another project without explicit written permission. **Do not vendor, port or package it** pending permission/license review. Game Assist’s MIT license does not resolve this restriction.
- Recent development establishes a maintained lead, not a tested read-only API or compatibility with this user's save. No executable was launched.

### 4. Reader-focused Rust lead: `laszloprekop/ER-save-Reader` / `er-reconstruct`

[Reader README](https://github.com/laszloprekop/ER-save-Reader) names its maintainer, supports PC and PlayStation Save Wizard exports, and says write-back is disabled by default; it still contains contradictory legacy editing instructions. [Extracted core README](https://github.com/laszloprekop/er-reconstruct) explicitly describes an **identity-only seed** (`name`, `level`, `class_id`), with inventory/world/event reconstruction future work. Its conformance tests skip without an external save corpus. README claims MIT/Apache-2.0 dual licensing, but direct license/code fetches failed here: verify files and pin a revision before adoption. Do not mistake the new core for a complete progress decoder.

## The Witcher 3

[Atvaark/W3SavegameEditor](https://github.com/Atvaark/W3SavegameEditor) is an unpacker/viewer requiring .NET Framework 4.7.1 and LZ4; archived **2020-06-22**. [LICENSE inspected](https://github.com/Atvaark/W3SavegameEditor/blob/master/LICENSE): MIT, copyright 2015 Atvaark.

[SavegameFile.cs inspected](https://github.com/Atvaark/W3SavegameEditor/blob/master/W3SavegameEditor.Core/Savegame/SavegameFile.cs) uses `File.OpenRead`, decompresses, and builds generic string/variable tables. Parsing exceptions may yield invalid-variable placeholders. This is a useful read-only format reference, **not evidence of correct quest/missability interpretation**. No maintained current-build semantic parser was verified. Windows legacy tooling does not establish next-gen/current patch, DLC, modded, Linux/Proton, console or cross-save compatibility. Keep these unsupported until fixtures prove otherwise.

## Belmont's Curse

The author's [ATMA completion-import documentation](https://atma.gg/castlevania-belmonts-curse/completion-checklist) demonstrates a claimed Steam `.sav` import feature, but also states its checklist omits some story/exploration/item information and differs from in-game completion. This supports **feasibility research only**: this review did not establish an open-source decoder, license, version matrix or tested import. No user save was uploaded. Do not copy the site's data/code, treat checklist percentage as achievement completeness, or direct a spoiler-sensitive user to its unfiltered database. Absence of a verified reusable parser here is not proof that none exists.

## Acceptance gate for any adapter

1. **Pin provenance:** exact source revision, dependency/data licenses and patch/platform/DLC allowlist. Product licensing decision: **MIT, with commercial use approved by the user at 15:07 UTC on 2026-10-31**. Audit each dependency and data source independently; this does not authorize relicensing third-party material or bypass restricted-source permissions. No outside code incorporated by this report.
2. **Private fixtures with consent:** copies from the exact user build, selected slot/playthrough, base/DLC variants, and paired before/after one known quest transition, pickup, boss event and missability boundary. Use opaque IDs in tests/reports. Include fresh/empty slot, NG+, multi-slot, modded/unsupported, truncated/corrupt and concurrent-write cases. Do not publish saves containing account identifiers.
3. **Read-only proof:** parse stable copies/bytes in an isolated worker with no game-directory write permission, no network and size/time limits. Never enable repair/write-back; hash original bytes before/after. Do not run the game's editor UI or inject code into the game.
4. **Semantic proof:** compare facts against independently recorded in-game ground truth; inventory possession is not acquisition history, and a cleared flag is not automatically a permanent miss. Preserve unsupported, unknown, invalid and false as different states.
5. **Spoiler boundary:** normalize opaque facts locally; enrich only after discovery is independently established. Hide undiscovered names, icons, map labels, ending counts and future rule text. A failed parser must produce “progress unknown,” never fabricated hints or a clean completion report.
6. **Release gate:** deterministic corpus tests, unchanged originals, reviewed version-specific rules and explicit coverage per fact category. Until then expose only metadata/achievements/manual observations with provenance—not decoded-save claims.

## Subsequent private-fixture evidence (2026-10-31)

With the owner’s explicit authorization, a current Belmont cloud save was downloaded through Steam’s signed-in official page and inspected read-only. Format is JSON with version `1.1.3`; playerSave exposes health/mana fragment counters and current health/mana. Those counters have NOT been proven to mean completed upgrades, and current resources are NOT maxima. Generic per-entity states exist but do not establish HP/mana pickup IDs or locations. A structural reader can be implemented for this observed schema; exact pickup mapping still requires controlled before/after evidence and independently reviewed community records. No player IDs, world/entity IDs, raw saves or personal progress values are published here.
