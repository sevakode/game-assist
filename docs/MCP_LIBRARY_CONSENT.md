# Explicit library access for an AI client

This incremental slice adds `library.read` as an **optional OAuth scope** and
`get_library()` as a read-only MCP tool. The endpoint still requires
`progress.read`; library use requires both scopes plus the account's existing
library-source opt-in. No per-game save/achievement permission is implied.

## User flow and current blockers

1. A new client registers either explicitly requesting `progress.read library.read`
   or omitting scope; both capabilities are then recorded for that new client.
   Authorization must explicitly request scopes. When both are requested, browser
   consent shows an optional library checkbox, **unchecked by default**. Only an
   explicit check grants `library.read`; otherwise the token has only progress.
   The account's independent source permission is still required for cached data.
2. On `/games#steam-library`, the user separately enables library reading and
   explicitly refreshes the list. This uses the existing bounded reader/cache,
   consent generation, cooldown, expiry and revoke guards. MCP never fetches Steam.
3. `get_library` returns cached AppIDs/names and asks which game the user wants.
   It never auto-registers/selects games or enables save/achievement scopes. The
   user can select and permit a game on `/games` independently.
4. The AI can discuss the user's stated goal, then use the existing progress and
   connection tools. Library membership does not prove progress, supported save
   decoding, current activity, or possession of an accessible Cloud save.

The operator Steam Web API key is currently absent. Thus live library retrieval
remains unavailable; use manual game selection. OpenID is identity only. A live
Claude client requesting the new optional scope is also unverified. Existing
Claude connections may keep their old registration/scopes: reconnecting must
actually request the new scope and show new consent; a plain refresh cannot do it.
No client registration/update is performed automatically by this application.

## Scope compatibility

- New DCR with omitted scope records both client capabilities. Explicit
  `progress.read` stays progress-only. No existing registration/code/token/refresh
  family is migrated or broadened. Discovery advertises the optional library scope,
  but transport continues to require only progress so old clients keep working.
- Authorization requires progress plus a subset of the registered supported
  scopes. An old progress-only client cannot request library by changing its
  authorization query. A new registration is needed; no update endpoint is added.
- A client registered for both may request only progress: its consent page and
  token contain only progress, without a library checkbox. Requesting both also
  defaults to progress-only consent; the form must explicitly submit
  `library_read=yes` for library access. Unknown fields/values and unrequested
  scope additions are rejected. Approval validates the granted subset atomically
  with consuming the pending request. Missing `library.read` returns a fixed
  `oauth_library_scope_required` result before reading any account library state.
- Refresh can retain or narrow token scopes. It cannot add library to an old token
  or to a narrowed refresh family. It must retain `progress.read`; library-only
  narrowing is rejected without consuming a valid credential. Missing authorization
  scope returns controlled `invalid_scope`. Rotation/replay revocation persist.
- Turning off account library reading deletes the cache and immediately stops
  disclosure. Re-enabling creates a new empty consent generation; a site refresh
  is required again. In-flight old-generation results cannot repopulate it.
- Full account revoke also revokes OAuth credentials. New OAuth consent does not
  restore deleted library source consent/cache.

## Output and safe agent interpretation

No arguments or owner/game IDs are accepted by the tool signature. Token subject
binds the account. Each game has exactly `appid` and `name`; no icons, playtime,
Steam IDs, saves, achievements, device IDs, or account registration data are copied.
Names are untrusted data, never agent instructions. The existing source limits
(1000 games, 256 KiB accepted projection) remain; no second source pipeline exists.

| Reason | Next action |
|---|---|
| `oauth_library_scope_required` | `review_fresh_connection_and_library_consent`; connection help URL. An old registration needs fresh DCR; a capable client still needs a new explicit library consent. Neither is an automatic upgrade. |
| `operator_source_not_configured` | `choose_game_manually`; `/games`, not a request for the player's key |
| `account_library_permission_required` | `review_library_permission`; library panel |
| `cache_not_requested` | `refresh_library_on_site`; explicit user action |
| `cache_expired` | `refresh_library_on_site`; old list is not returned |
| `source_unavailable` | `review_source_and_refresh`; unknown/private/empty is not zero games |
| `cached_library_available` | `ask_user_which_game`; only here is status `available` |

All returned URLs use configured `issuer`. `received_at` is receipt time, not
activity time. `current_game` is always unknown. No source/credential fetch occurs
from this tool; cache expiry is projected without mutating stored data.

## Integration surface

Only `remote_server/ui.py::consent_body` changes in UI. It accepts
`scopes=('progress.read',)` and renders a fixed description for each
requested scope. The app supplies server-stored pending scopes. When library is
requested, its unchecked checkbox is inside the POST form; the explanatory list
is now inside that form too. Only `library_read=yes` adds library to the granted
subset, and the provider verifies it was requested. The library text
says AppID/names only, separate website consent, no playtime/icons, no automatic
game selection or save/achievement grants. The client label stays escaped.
No CSS, home page, Claude starter prompt or onboarding diagnostics are changed.

This contract is synthetic, not a claim of live Claude compatibility. The
documented metadata scope selection motivates the new-registration default; a
fresh real client must still demonstrate DCR, explicit authorization scopes,
unchecked/checked consent behavior, and token-scope handling. A client may respond
to a declined optional scope differently from the synthetic test client.

## Recent-activity research, 2026-10-31 — not implemented

Valve's [IPlayerService reference](https://partner.steamgames.com/doc/webapi/IPlayerService)
documents `GetRecentlyPlayedGames` inputs `key`, `steamid`, `count` (zero/unset:
all); `GetOwnedGames` additionally offers `include_appinfo` (name/icon),
`include_played_free_games` and `appids_filter`. Owned games require visible
game details. It describes recent games, not a currently running game. The
accessible reference does **not** specify response schemas, sorting, last-played
timestamps or a two-week-window guarantee. Therefore `playtime_2weeks`,
`playtime_forever` and last-played fields are not newly certified by this review.
The [Valve developer wiki](https://developer.valvesoftware.com/wiki/Steam_Web_API)
was unavailable (HTTP 403); no third-party schema was substituted.

Valve's [Web API authentication documentation](https://partner.steamgames.com/doc/webapi_overview/auth)
distinguishes user and publisher keys, documents `x-webapi-key`, and requires HTTPS
for keyed requests. No key was created or used in this work; the existing reader's
operator configuration remains unchanged.

Inference for product behavior: even a confirmed two-week activity list would
only supply candidates, never proof of the current game. Ask the player to confirm.
The existing library reader intentionally discards all playtime/icon data.

Proposed next slice, separate from library consent:

1. Add an account opt-in explicitly for recent-activity suggestions and a distinct
   OAuth `activity.read`, both off by default. Neither `library.read` nor progress
   permission implicitly grants activity. Disclose the time window once verified.
2. Verify an authoritative response contract and an explicitly permitted live
   response after operator key setup; keep private/unavailable/empty distinct from
   proof of no activity. Do not infer ordering or current-game status.
3. Build a bounded manual refresh/cache with expiry and consent-generation guards.
   Expose only candidate AppIDs/names; do not expose minute counts or timestamps
   unless a further explicit product requirement and consent justify them.
4. Suggest candidates and ask the user which one; selection and per-game source
   permissions remain separate. No automatic fetch/poll/push or blanket grant.

## Evidence

`tests/test_remote_mcp_library.py` uses fake Steam identity/library responses and
real local MCP HTTP + OAuth endpoints. It covers DCR defaults, old-client refusal,
exact consent, dual gates, non-expanding/narrowing refresh, tenant isolation,
revocation, private/empty/expired/unconfigured states, no MCP fetch, exact output,
and no implicit game selection. Real PostgreSQL inherits these contracts only when
an explicit disposable test DSN is supplied; skipped tests are not PostgreSQL
evidence. Live Claude, Steam source retrieval and recent activity remain open.
