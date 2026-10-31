# Read-only save parser coverage — research gate

Checked **2026-10-31, updated 18:07 UTC**. This separates source research from the narrow Belmont implementation described below; **it does not establish full three-game support**. No third-party executables/packages were downloaded or run during this research pass. Later authorized private-fixture findings are recorded below; no raw player saves are included in this repository. Sources below are project authors' repositories/docs. They may contain spoilers: do not open them automatically in the player UI.

## Decision summary

| Steam game | Current defensible position | Quest / inventory / boss / missable coverage |
|---|---|---|
| Castlevania: Belmont's Curse — `4231820` | Narrow local JSON `1.1.3` reader: four allowlisted health/mana scalar fields; see private-fixture evidence below | Pickup IDs/locations, quests, inventory, bosses and missables remain unknown; counters are not proven completed upgrades |
| Elden Ring — `1245620` | Authorized private fixture present; bounded BND4 header sanity checks passed; gameplay decoder not validated | Some event facts feasible; inventory depends on candidate; missability requires separate tested rules |
| The Witcher 3 — `292030` | No fixture available from the checked official Cloud listing; legacy decoder/current-build support unproven | Generic variables are not verified quest/inventory/boss facts; all four remain gated |

Steam achievements are account evidence, not a complete per-character, current-playthrough inventory or quest state. A locked achievement is not proof of a missed opportunity. No candidate establishes a spoiler-free “all achievements guaranteed” planner.

## Implementation priority

The user's first priority is **Belmont's Curse HP/mana pickup mapping**, not Elden Ring. Start with consented paired saves immediately before and after **one** known pickup on the exact game version, plus independently recorded in-game ground truth. Increased maximum HP/mana alone does **not** identify which pickup was collected or establish an item/location ID. Distinguish a verified pickup ID from an aggregate stat change; unresolved mappings stay unknown. A community world/location database is a separate enrichment source with its own provenance, license and spoiler controls—not proof that a particular save contains that pickup.

## Elden Ring candidates

### 1. Small read-only TypeScript spike: `zebbedaja/er-save-parser`

- [README](https://github.com/zebbedaja/er-save-parser) targets PC saves, exposes character slots and selected event flags, and explicitly leaves equipment/inventory on its TODO list.
- [Actual parser](https://github.com/zebbedaja/er-save-parser/blob/main/src/parser.ts) **skips inventory, storage and equipment**; decodes a bundled event-flag list. [Types](https://github.com/zebbedaja/er-save-parser/blob/main/src/types.ts) expose raw version fields, not a compatibility guarantee. Do not advertise inventory or comprehensive quest coverage.
- [LICENSE inspected](https://github.com/zebbedaja/er-save-parser/blob/main/LICENSE): MIT, copyright 2026 Daniel Zsebedits. Preserve notices if reused; separately audit dependency/data provenance.
- [Package manifest](https://github.com/zebbedaja/er-save-parser/blob/main/package.json) identifies parser version **0.1.14**, not a supported game-patch version. Input-buffer parsing suits an isolated read-only adapter. Latest commit date/release support matrix was not established (commit-history fetch failed); repository availability is not proof of maintenance. No patch/DLC/Proton compatibility validated here.

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

### 5. Established Rust codebase: `ClayAmore/ER-Save-Editor`

[Repository](https://github.com/ClayAmore/ER-Save-Editor) contains separate PC/common/PlayStation save modules. The inspected [PCSave implementation](https://github.com/ClayAmore/ER-Save-Editor/blob/master/src/save/pc/pc_save.rs) reads a binary-reader header, ten slots and common sections; a separate write implementation must remain inaccessible. [MIT license inspected](https://github.com/ClayAmore/ER-Save-Editor/blob/master/LICENSE-MIT), copyright 2024 ClayAmore: preserve notices and audit dependencies/data separately. [Releases](https://github.com/ClayAmore/ER-Save-Editor/releases) list `v0.0.21-alpha`; this is a tool release, **not proof of compatibility with any current game patch**. Extracting a no-write module is feasible development work, not an already validated adapter. Do not launch the editor UI, apply fixes or modify game files.

## The Witcher 3

[Atvaark/W3SavegameEditor](https://github.com/Atvaark/W3SavegameEditor) is an unpacker/viewer requiring .NET Framework 4.7.1 and LZ4; archived **2020-06-22**. [LICENSE inspected](https://github.com/Atvaark/W3SavegameEditor/blob/master/LICENSE): MIT, copyright 2015 Atvaark.

[SavegameFile.cs inspected](https://github.com/Atvaark/W3SavegameEditor/blob/master/W3SavegameEditor.Core/Savegame/SavegameFile.cs) uses `File.OpenRead`, decompresses, and builds generic string/variable tables. Parsing exceptions may yield invalid-variable placeholders. This is a useful read-only format reference, **not evidence of correct quest/missability interpretation**. No maintained current-build semantic parser was verified. Windows legacy tooling does not establish next-gen/current patch, DLC, modded, Linux/Proton, console or cross-save compatibility. Keep these unsupported until fixtures prove otherwise.

## Belmont's Curse

The author's [ATMA completion-import documentation](https://atma.gg/castlevania-belmonts-curse/completion-checklist) demonstrates a claimed Steam `.sav` import feature, but also states its checklist omits some story/exploration/item information and differs from in-game completion. This supports **feasibility research only**: this review did not establish an open-source decoder, license, version matrix or tested import. No user save was uploaded. Do not copy the site's data/code, treat checklist percentage as achievement completeness, or direct a spoiler-sensitive user to its unfiltered database. Absence of a verified reusable parser here is not proof that none exists.

## Steam achievement/schema integration

Official [ISteamUserStats documentation](https://partner.steamgames.com/doc/webapi/ISteamUserStats) specifies `GetPlayerAchievements/v1` with a user Web API key, SteamID and appid; `GetSchemaForGame/v2` requires the key and appid, with optional language. Schema retrieval does not require a personal save. Implement and mock-test this separately from save decoding; real achievements remain gated by configured API access and data availability, not guessed as zero on failure.

Use HTTPS on the public `api.steampowered.com` host: the [Web API overview](https://partner.steamgames.com/doc/webapi_overview) says the partner host requires a publisher key even for ordinarily public methods. [Authentication documentation](https://partner.steamgames.com/doc/webapi_overview/auth) permits `x-webapi-key`; user-key registration requires a Steam account, associated domain and terms acceptance. Keep keys server-side/out of URLs and logs. No key was created and no private-account API call was made in this research. OpenID identity is not a save decoder or a grant to bypass privacy settings.

## What can proceed without more private inputs

- Build consent, stable-copy handling, version gates, parser interfaces, unknown/error states and synthetic tests for all three games now.
- Retain Belmont's narrow `1.1.3` scalar reader. Do not enable pickup mapping until a controlled single-pickup before/after pair and independent in-game ground truth exist. A private baseline alone cannot establish the mapping.
- Elden Ring: an authorized private fixture is now available for local validation. An experimental disabled-by-default adapter is implementable from permissive sources, but enabling verified gameplay facts still requires exact game build/platform/DLC/mod status and semantic fixture validation. No exact supported game-patch range was established here.
- Witcher 3: legacy decoding scaffolding is implementable, but current-build semantic support requires the same version/fixture gate and verified variable mappings. A successfully decompressed file is not verified quest progress.
- Steam schema/achievement clients can be completed against mocks now; live results need operator-configured credentials and successful authorized requests. These gates prevent a false “all features complete” claim, not work on independent product features.

## Acceptance gate for any adapter

1. **Pin provenance:** exact source revision, dependency/data licenses and patch/platform/DLC allowlist. Product licensing decision: **MIT, with commercial use approved by the user at 15:07 UTC on 2026-10-31**. Audit each dependency and data source independently; this does not authorize relicensing third-party material or bypass restricted-source permissions. No outside code incorporated by this report.
2. **Private fixtures with consent:** copies from the exact user build, selected slot/playthrough, base/DLC variants, and paired before/after one known quest transition, pickup, boss event and missability boundary. Use opaque IDs in tests/reports. Include fresh/empty slot, NG+, multi-slot, modded/unsupported, truncated/corrupt and concurrent-write cases. Do not publish saves containing account identifiers.
3. **Read-only proof:** parse stable copies/bytes in an isolated worker with no game-directory write permission, no network and size/time limits. Never enable repair/write-back; hash original bytes before/after. Do not run the game's editor UI or inject code into the game.
4. **Semantic proof:** compare facts against independently recorded in-game ground truth; inventory possession is not acquisition history, and a cleared flag is not automatically a permanent miss. Preserve unsupported, unknown, invalid and false as different states.
5. **Spoiler boundary:** normalize opaque facts locally; enrich only after discovery is independently established. Hide undiscovered names, icons, map labels, ending counts and future rule text. A failed parser must produce “progress unknown,” never fabricated hints or a clean completion report.
6. **Release gate:** deterministic corpus tests, unchanged originals, reviewed version-specific rules and explicit coverage per fact category. Until a category passes, expose only its supported metadata/achievements/manual observations with provenance—not decoded-save claims. The narrow Belmont scalar allowance does not waive gates for other facts.

## Subsequent private-fixture evidence (2026-10-31)

With the owner’s explicit authorization, a current Belmont cloud save was downloaded through Steam’s signed-in official page and inspected read-only. Format is JSON with version `1.1.3`; playerSave exposes health/mana fragment counters and current health/mana. Those counters have NOT been proven to mean completed upgrades, and current resources are NOT maxima. Generic per-entity states exist but do not establish HP/mana pickup IDs or locations. A narrow local structural reader now allowlists four scalar fields for this observed schema; exact pickup mapping still requires controlled before/after evidence and independently reviewed community records. No player IDs, world/entity IDs, raw saves or personal progress values are published here.


### Elden Ring and Witcher Cloud evidence (18:07 UTC)

An Elden Ring fixture was obtained through the authorized, signed-in **official Steam Cloud browser flow**, not through a completed API integration. A bounded local Python-standard-library probe opened it read-only and inspected only the 64-byte container header. The BND4 signature, reserved bytes, little-endian flag, 64-byte main header and declared directory/header-end bounds were consistent with the [primary BND4 implementation](https://github.com/JKAnderson/SoulsFormats/blob/master/SoulsFormats/Binder/BND4/BND4.cs). File size and modification time were unchanged. This is **header sanity only**, not full container-entry, checksum, payload or gameplay validation. No names, account IDs, entity IDs or progress were extracted.

The container contains a printable version/timestamp field, but that field does **not** establish the installed game patch/build; no exact game version was identified. Actual slot/event/inventory semantics, supported-version mapping and independently checked in-game ground truth remain required before exposing progress. The fixture's path, digest, raw header and contents are intentionally omitted from this public document.

For The Witcher 3 app `292030`, the authorized official Cloud page showed an empty file table at the time checked. This establishes only that no downloadable fixture appeared in that listing—not that the user never played, lacks local saves, uses another edition or has zero progress. A selected local save and its version/platform context are still needed; do not change app IDs or broaden account searches by inference.
