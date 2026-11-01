# Phone-only game context: bounded backend audit

Audited base: `2a9099de52839cf1a7e01e594130a69ef6c88920`.

## What already works

Steam OpenID binds identity. It does not supply saves. The account library opt-in
and explicit website refresh populate the bounded library cache; MCP `get_library`
also requires OAuth `library.read` (in addition to the service's required
`progress.read`). Library results do not select games or grant achievement/save
access. Empty, unavailable and expired caches are not proof of an empty library.

Selecting a game does not grant its data scopes. Explicit per-game
`achievements.read` creates a `not_requested` cache entry without Steam I/O.
`POST /account/achievements/refresh` is already implemented, validates session,
exact Origin and CSRF, uses the bounded AchievementReader, and rechecks selection,
grant and consent generation after I/O. Refresh cooldown is 15 minutes; cache TTL
is 24 hours. `get_progress` returns only permitted unlocked rows from that cache.
No new reader or fetch integration is missing. No automatic fetch follows consent.

## Gap closed by this patch

Previously diagnostics emphasized missing saves/import/companion even when
achievement context was available. `get_connection_status` now additionally
returns `phone_context`: conversation needs no companion; ask the player their
game and current goal. It distinguishes permission-only, received, received-empty,
expired, unavailable, invisible permission, absent operator source, and unknown.
Only games already in Store.projection appear. Only an `ok` cache yields a count
of visible unlocked rows; this is not a total achievement count or completion
percentage. Receipt age is retrieval age, not save age or current play position.
No achievement text, hidden game catalogue, library, identity or arbitrary URLs
are copied into the new field. Current game/position and interpretation remain
unknown. Received-empty does not prove there are no achievements.

## Integration for the parent/UI owner

No app.py wiring required: the existing get_connection_status tool already calls
this module. No tools, inputs, scopes or mutations change. Existing diagnostics
remain compatible; phone clients should use phone_context for the initial
conversation and treat old import/companion suggestions as optional save paths.

Suggested phone path: Steam login -> optional library opt-in and manual refresh
-> user chooses a game -> optional per-game achievements permission and manual
refresh -> AI OAuth consent -> get_connection_status, get_library only if granted,
get_progress -> ask current goal and what the player already discovered. If the
source is unavailable or permission is declined, start from the player's answers.
Do not force import or Deck setup. Do not infer current play from selection,
library membership or unlocked achievements. Do not infer lore, bosses, quests,
missed items or spoiler-safe walkthrough knowledge from the returned identifiers.

Website actions remain explicit human actions. This patch does not modify the
website, starter prompt, callback configuration, or implement in-chat selection.
The other UI worker can explain the two distinct buttons: permission and refresh.
A progress-only OAuth registration is not silently upgraded for library access;
the existing fresh-registration/explicit optional-consent flow still applies.

## Official source boundaries

Valve documents GetPlayerAchievements with user key, SteamID and AppID and optional
language: [ISteamUserStats](https://partner.steamgames.com/doc/webapi/ISteamUserStats).
Game Assist does not fetch GetSchemaForGame's full achievement catalogue. Tests
exercise the existing public endpoint through MockTransport, not Valve servers.

Valve describes Cloud through game integration and Steam-client synchronization:
[Steam Cloud](https://partner.steamgames.com/doc/features/cloud). This is not
evidence that OpenID or Game Assist's operator Web API key supplies arbitrary
Cloud-save downloads. The audited application has no Cloud reader. Its
source_not_connected capability remains unchanged; this does not claim Valve has
no Cloud APIs. No session-cookie bridge, scraping or desktop installation is
introduced.

## Evidence and limits

New tests use synthetic SQLite owners, synthetic OpenID, real local DCR/PKCE/MCP
handling and real AchievementReader with httpx.MockTransport. They cover permission
without fetch, manual refresh, locked-row exclusion, read-only cache diagnostics,
expiry, unknown/empty/unconfigured states, cross-owner isolation, revoke, and
negative CSRF/Origin checks. Existing library/achievement/diagnostic regressions
are also run. No production data, credentials or environment values are read.
PostgreSQL concurrency, actual Steam responses, browser phone UX and physical
Claude/ChatGPT connections are not validated by these tests. No deploy is made.
