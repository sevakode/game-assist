# Remote companion: experimental single-instance beta

This is a separate service, not a switch to expose the old local API. A beta deployment at https://game-assist.onrender.com has passed public HTTPS, health, metadata and download checks. PostgreSQL behavior is covered by real disposable database tests; Steam behavior in the automated suite is mocked. Phone OAuth and real Steam Deck acceptance are still required. No Steam Web API key or third-party AI connector has been configured by this deployment.

## Run after an operator supplies infrastructure

Install the repository requirements plus `remote_server/requirements.txt` (official
`mcp==1.29.0`). Configure **an exact HTTPS origin without trailing slash**, a private
persistent SQLite path, and exact OAuth callback URLs confirmed by the intended client:

```
GA_PUBLIC_ORIGIN=https://YOUR-REAL-HOST
GA_REMOTE_DB=/PRIVATE-PERSISTENT-DIRECTORY/remote.sqlite
GA_OAUTH_REDIRECT_URIS=https://EXACT-CLIENT-CALLBACK
python -m remote_server
```

These uppercase strings are documentation placeholders, not usable configuration.
Bind is loopback `127.0.0.1:8788`; place a TLS reverse proxy in front, preserve the
configured Host, bound request rates/sizes/timeouts, and disable/redact logs containing
URLs, cookies or authorization headers. Do not trust forwarded headers or run multiple
workers. Firewall the backend and protect the database directory/backups. SQLite is
not encrypted by this application; use encrypted storage and an appropriate backup,
retention and deletion policy before real users. Operational monitoring, abuse limits,
security review and restoration drills remain deployment gates.

## Flow

1. Mobile browser visits `/`; Steam OpenID verifies identity with Steam directly.
   No Steam password/API key is entered here. Server-side random session, Secure,
   HttpOnly, SameSite=Lax host cookie; one-time browser-bound login state.
2. Deck calls `POST /v1/devices/pair/start {appid,scopes}` with the selected AppID and
   `saves.metadata` or supported `saves.summary`. Legacy `{}` requests only Belmont
   summary. Browser approval must match the requested game/scopes exactly. Register
   unknown AppIDs in your account first. Generic metadata is only file size and
   modification time. Belmont summary remains four raw fields for save format 1.1.3;
   it does not establish exact game-build coverage, maxima or pickup semantics.
3. Deck polls `POST /v1/devices/pair/poll {"device_code":"…"}` at five-second intervals.
   Pending returns `status:pending`; approval returns `status:approved`, `device_token`,
   `token_type:Bearer`, `expires_in:2592000`, `appid` and `scopes` **once**. Expiry/replay requires restarting
   pairing. Device credential expires after 30 days and requires re-pairing; automatic
   device credential refresh is not implemented. This is not yet indefinite seamless UX.
4. `POST /v1/device/observations` uses that device bearer and exactly
   `{event_id:<UUID>, appid:<boundAppID>, kind, payload}`. Generic `save_metadata`
   payload is exactly `{size_bytes:0..1073741824,modified_ns:0..2**63-1}` with strict
   integers. `save_summary` remains the existing validated Belmont-only safe summary.
   Owner comes only from the token; all extra fields are rejected. No upload endpoint
   for raw saves, filenames, paths, world/entity IDs, SteamIDs or achievements exists.
5. MCP client connects to `https://HOST/mcp`, discovers protected-resource and OAuth
   metadata, uses public-client DCR (`token_endpoint_auth_method:none`), authorization
   code + S256 PKCE + state + exact resource. Browser gives separate read-only consent.
   Website login continues to the pending consent screen. The official MCP SDK owns
   the OAuth protocol endpoints, authentication, PKCE verification and MCP transport;
   application provider hooks own persistent opaque credentials and consent.
6. `get_progress` / `suggest_next_step` accept no owner/game IDs, return only the
   caller's currently allowed metadata/summary projection or unknown state, and do not expose
   Steam identity. Revoking all access on the account page deletes grants, devices,
   pending device approvals and observations/events; it revokes OAuth credentials.

Scopes: OAuth `progress.read`; game/device `saves.summary`, `saves.metadata`.
Access tokens expire in ten minutes, OAuth refresh tokens in 30 days and rotate on
use. Refresh replay revokes the family. All bearer tokens and device/user pairing
codes are hashed at rest. OAuth code/state and device pairing are one-use. HTTPS,
exact allowed hosts/redirects, CSRF, 16 KiB bodies, bounded query size and rate limits
fail closed. SDK wildcard CORS response headers are stripped; browser origins other
than the configured site are denied. Native/server clients do not need CORS.

## Explicit limitations / remaining gates

- DCR public `none` clients only; CIMD and confidential client secrets are not supported.
  Confirm the selected ChatGPT/Claude account's actual OAuth flow before publishing.
- Host/proxy rate limiting is deliberately coarse: no forwarded-IP trust. Shared proxy
  IP can hit the cap. Tune deployment limits only after measuring a controlled trial.
- No live Steam calls in tests. OpenID links identity only, not private cloud saves.
  Steam achievements are not synchronized by this service yet. No server-side LLM.
- Accounts, Steam links and consumed-token replay records persist. The revoke button
  is not full account deletion. A published retention/account-deletion flow is required
  before offering this publicly; no background cleanup policy is falsely promised.
- Pairing loss after one-time token delivery requires new pairing. No recovery of raw
  credentials from hashes. No auto-update/install on the user's Deck is performed.
- No claim of multi-instance production readiness or proven mobile compatibility.

Tests: `python -m unittest discover -s tests -p 'test_remote*.py' -v`.

## AI-client acceptance and issuer identification

Claude's supported path is DCR: use **Register automatically**, then **Sign in
now**, with `https://game-assist.onrender.com/mcp`. Its exact approved callback
is `https://claude.ai/api/mcp/auth_callback`. CIMD is not implemented. A local
synthetic registration using that callback never contacts or registers anything
at Claude; it is a protocol contract, not evidence of a real client connection.

The local RFC 9207 adapter targets pinned `mcp==1.29.0`. Discovery advertises
`authorization_response_iss_parameter_supported: true`; successful consent and
SDK-generated authorization error redirects carry one `iss`, exactly matching
the authorization metadata issuer and protected-resource `authorization_servers`.
Pydantic serializes the origin issuer with `/`, so the production-shaped value
is `https://game-assist.onrender.com/`. Origin checks and the `/mcp` resource keep
their existing values. The adapter decorates existing SDK error redirects only;
it does not choose callbacks, redirect local errors, or alter Steam/consent hops.
Re-run these contracts when upgrading the SDK.

This prepares one ChatGPT compatibility requirement; it does not establish live
ChatGPT support. Copy the exact callback from the client's management page and
obtain separate operator approval before changing the production allowlist.
Stable callbacks apply only to eligible clients. See the official
[issuer identification guidance](https://developers.openai.com/plugins/build/auth#protect-callbacks-with-issuer-identification).

Owner's live Claude checklist (still open):

1. Connect the MCP endpoint with automatic registration; complete real Steam
   OpenID and the separate `progress.read` consent. Confirm the return to Claude.
2. Call the actual `get_progress` tool before granting data access. Expect unknown
   or empty data, never invented progress. Record tool success, not model prose.
3. Select Belmont, explicitly permit its summary, preview a compatible local save
   in `/import`, then confirm sending the four-field projection. Call `get_progress`
   again; verify those fields and `browser_manual` provenance only.
4. Revoke the game's access and call again: the summary must disappear. After
   normal token refresh it must remain absent. Test full account revoke separately:
   the existing connection must fail; refresh cannot restore it. A fresh consent
   may reconnect but cannot restore deleted observations.
5. Confirm a normal refresh after the ten-minute access lifetime in the real
   client. Keep tokens, callback codes, Steam identity and saves out of evidence.

Steam OpenID supplies identity, not Cloud saves. The Deck companion is optional;
Steam Web API achievements/library remain unavailable without the separately
configured key and permission. None of the local tests closes the real-client gate.

## Prototype storage bounds

Only the latest summary per owner/game is retained. `received_at` is server receipt
time, not the time the save was played; observation time remains unknown. Event UUID
retries are idempotent; reuse with different normalized content returns HTTP 409.
Deduplication rows expire after 31 days (longer than device credentials) and are capped
at 10,000 per device. Active devices are capped at 100 per account. Expired devices
are pruned on pairing. Rate buckets expire after an hour and are capped at 10,000;
sessions and pending pairs have a 2,000-entry global cap. This is conservative
single-instance admission control, not a promised production throughput tier.

With `proxy_headers=False`, per-IP limits aggregate all traffic through the reverse
proxy. Before increasing capacity, design explicit trusted-proxy IP allowlists; never
accept arbitrary client-supplied forwarding headers or wildcard proxy trust. A host
with ephemeral disks is **not compatible** with this SQLite deployment: obtain
persistent storage or implement and test a persistent database adapter first.

## Render + Neon beta deployment

`render.yaml` is a source-only free-plan blueprint. Render mode binds the supplied
`PORT` on `0.0.0.0`, but only after `GA_DEPLOYMENT_MODE=render` is explicitly set.
It refuses to start without `DATABASE_URL`; it never falls back to ephemeral SQLite.
`GA_PUBLIC_ORIGIN` must be an exact HTTPS origin. In explicit Render mode only,
when that variable is absent, the trusted platform-provided `RENDER_EXTERNAL_URL`
is used instead. Request Host/forwarding headers never supply the issuer. For a
custom domain set `GA_PUBLIC_ORIGIN` explicitly. Redirect URLs remain operator-supplied
exact client callbacks. `/healthz` reports process readiness, not
an independently verified live connection to Steam or a mobile assistant.

The PostgreSQL DSN must explicitly select `sslmode=verify-full`; the driver uses
the pinned certifi Mozilla CA bundle as an explicit trusted CA file when no root
file is specified or `sslrootcert=system` is selected. This avoids bundled OpenSSL
default-path ambiguity without disabling chain or hostname verification. An
explicit operator-configured root file remains honored. A default Neon DSN
with `sslmode=require` must be strengthened and tested, not silently accepted.
Do not paste connection strings in chats/logs or commit them. Enter a reviewed DSN
only in the hosting provider's secret settings after account/setup authorization.

All twenty tables (sessions, login states, Steam nonce reservations, grants,
pairings, device credentials, observations, events, rate buckets, and OAuth data)
share one durable database. A transaction-scoped advisory lock preserves the
single-instance serialized behavior across independent connections, including
refresh replay and pairing races. Epoch timestamps use DOUBLE PRECISION. Connections
are limited to eight concurrently; each transaction closes its connection rather
than keeping an application pool warm. This favors a small prototype over throughput.

The adapter was tested against an actual disposable **PostgreSQL 17.11** cluster
bound only to loopback TCP, with UTF8 encoding and temporary SCRAM credentials.
All 57 remote tests passed, including 29 actual-PostgreSQL tests: persisted restart,
nonce replay, two-connection code/refresh races, pairing single-issue, duplicate
submission, revoke/ingest serialization, tenant separation and rollback. No hosted
Neon account or production credentials were used. PostgreSQL databases must use
UTF8 encoding; an SQL_ASCII test cluster was detected as incompatible and the
adapter now rejects it explicitly.

`tests/test_remote_postgres.py` intentionally skips without an explicit local
disposable test DSN. It does not count skipped tests as PostgreSQL validation.
`remote_server/test_postgres.sh` reproducibly initializes, runs the complete suite,
and removes a temporary loopback-only cluster. Set `PG_BINDIR`, `PG_SHAREDIR` and
any required library search path to an installed official PostgreSQL distribution;
run the script from the repository root with the pinned driver installed. The suite
truncates all application tables in its disposable database. Its insecure local TLS
override is restricted to loopback and is not available through service settings.

Hosted Neon TLS connectivity and Render startup have now been verified for the beta.
Long-running pooled-endpoint behavior and repeated cold starts still need acceptance.
Real phone Steam callbacks, AI-client OAuth and Steam Deck hardware remain unverified;
automated tests and public endpoint checks do not establish those integrations.

No existing SQLite-to-PostgreSQL data migration has been run. The first hosted
installation should use a fresh database; migration of existing real accounts
requires a separately tested, authorized migration/backup procedure. A schema is
created automatically only in the configured database on service startup.

The selected free hosting can sleep: the first request after inactivity can take
about a minute. This is not an always-warm or seamless-latency promise. Database and
hosting quotas, account availability, external OAuth compatibility and real-device
acceptance still require operator review and testing.

## Code-only Deck download

Deployment builds `remote_server/downloads/deck-companion.zip` once with
`python tools/package_deck.py`; requests never build an archive. The allowlist is
exact: the six Deck Python modules, `agent/watch.py`, both decoder Python modules,
MIT LICENSE and a short generated README. No recursive source-tree packaging,
server database/configuration, tokens, private fixtures, saves, binaries or pycache.
Stable file order, timestamps and permissions make builds byte-for-byte reproducible.
A SHA256 sidecar is verified at application startup; mismatch fails closed.

The public-code routes are fixed `/downloads/deck-companion.zip` and
`/downloads/deck-companion.zip.sha256`; there is no user-selected path. `/setup`
shows the configured HTTPS origin, checksum and inspectable manual commands. On
Deck, the user can open that URL in Desktop Mode without signing into ChatGPT,
download the ZIP, verify it, inspect source, and explicitly run setup. The command
chain stops on checksum failure. Pairing approval and background-service activation
remain explicit. No page executes scripts or installs software automatically.

The beta setup and download routes are public and verified, including the ZIP checksum.
Publishing these files does not install anything on the user's Deck. Actual
Desktop/Gaming Mode UX remains an external acceptance gate.

## Opt-in website inbox (implemented, device source only)

Authenticated users with a current `saves.summary` game grant can explicitly enable
inbox updates. Default is off. Only a known-to-known change in either raw fragment
counter produces a neutral deterministic notice; current health/mana fluctuations
do not. No item acquisition, completed upgrade or story progress is inferred.
All four permitted values continue updating the strict projection.

The first sample establishes a baseline, duplicate events/unchanged values do not
notify, and notices within five minutes coalesce into one latest item. Coalescing
rotates the item ID so stale forms cannot mark unseen newer updates read. Only the
owner can mark an item read. Opt-out deletes notices and re-enabling takes a fresh
baseline; global revoke removes settings/notices atomically with grants and tokens.

Retention is 30 days, cleaned on inbox access or new qualifying notice, with at most
50 items per owner. This is an on-site inbox, not outbound delivery: no background
scheduler, LLM run, push notification, unsolicited assistant message or Steam Cloud
source was added. The console-inspired server-rendered UI uses local CSS only and
retains exact session/CSRF/origin boundaries. Database changes are additive tables.

## Game selection, universal registration and real scoped access

The account homepage now offers Belmont (4231820), Elden Ring (1245620), and
The Witcher 3 (292030) as priority presets, not an imported owned Steam library.
Users can register any canonical positive AppID up to 2147483647, with an optional
plain-text label up to 120 characters, marked user-entered/unverified. Catalogs are
private and bounded at 100 entries including presets. Registration/selection alone
grants no file or sharing permissions. Community profile files remain declarative;
no community entry automatically enables parser code or grants access.

Single/multiple/all-current selection goes through a review page containing exact
AppIDs and separate permission checkboxes. A per-owner revision digest includes the
exact current catalog IDs/names; adding/renaming a game invalidates an old review.
No wildcard or future-game permission is stored. `saves.metadata` now actually works
for any selected AppID with a paired device, while `saves.summary` is available only
for the reviewed Belmont 1.1.3 format. Elden Ring/Witcher 3/unknown formats have no
verified interpretation. Neither scope grants Steam Cloud or achievements access.

Device credentials, pairing intents, events, observations and revocation are bound
to owner + AppID + allowed kind. A metadata credential cannot send a summary or
write another game's observations. Per-game/per-kind revocation deletes scoped
data and invalidates corresponding device credentials; re-grant does not reactivate
old credentials. Other games remain intact. MCP filters each kind by current scope.

Migration adds registrations, per-kind observations, fixed event/pairing columns and
a one-time marker. Existing rows remain Belmont-only. Historical no-op metadata
consent is removed once, not silently converted into working sharing permission;
subsequent explicit real metadata grants survive restarts. No hosted database is
modified by preparing these source files; the reviewed deployment runs migrations.

Projection freshness is tracked separately as `summary_received_at` and
`metadata_received_at`; a newer metadata receipt cannot make an older summary
appear freshly observed. Combined `received_at` is only the latest server receipt.

### Manual browser import (no companion installation)

`/import` is a deliberate, manual fallback, **not Steam Cloud sync**. The browser
reads a user-chosen Belmont format 1.1.3 file locally, displays the four supported
raw scalar fields and limitations, and sends only the validated projection after
an explicit confirmation. It does not send or store file bytes, names, paths or
hashes. A file must already be accessible on that device; the site cannot fetch
private Steam Cloud files. Unsupported formats/games are not interpreted.

`POST /v1/browser/observations` requires the existing secure site session, exact
Origin and CSRF token, selected Belmont and a current `saves.summary` grant.
The exact JSON envelope is `{csrf,event_id,appid:4231820,kind:"save_summary",payload}`;
the same typed safe-summary allowlist as device ingestion and 16 KiB body cap apply.
No permission, OAuth token or device credential is created by importing.

The latest confirmed import replaces the displayed summary, tagged by the server
as `browser_manual`; the next accepted device summary replaces it with `device`.
Each kind retains its own receipt timestamp; neither receipt proves when the game
was saved. Event retries are idempotent in an owner-bound manual channel, and a
changed payload with the same event ID is rejected. Existing opt-in site inbox
rules apply to the two known raw fragment counters only; identical projections do
not alert. Revocation deletes scoped manual/device data and blocks both sources.

### ACH-01: optional operator-configured achievements

`SGC_STEAM_API_KEY` is an optional operator secret, never requested from players or
stored in application tables. Without it the capability is unavailable and no
achievement HTTP requests occur. Configuration alone grants nobody access.
A selected game's `achievements.read` permission is a separate explicit opt-in;
changing save permissions does not enable it. Any registered AppID can be requested,
but Steam may expose no usable data. This is not proof of ownership or Cloud access.

`POST /account/achievements/refresh` accepts exactly `csrf,appid` with authenticated
session and exact Origin. Refresh is manual/request-driven: there is no scheduled
worker, automatic refresh on MCP reads, or push. At most two calls run concurrently;
minimum refresh interval is fifteen minutes/game, with twelve attempts/hour/account
and 120/hour globally. Responses are bounded to 1 MiB, 10,000 input rows, 500 unlocked
rows and 128 KiB retained data per game. Cache expires after 24 hours and expired
payload is removed on access; unavailable/private responses clear earlier payload.
There is at most one cache row per permitted game, capped at20 per account and512
globally (at most64MiB payload capacity). Granting beyond capacity fails before any
Steam call; revoke unused achievement permissions to free slots. Expired payloads
are also cleared in batches of100 during grants/refreshes. No automatic paid scale.

Only exact `achieved=1` rows survive response validation. Locked names/identifiers,
descriptions, totals, percentages and raw response bytes are never retained. Public
projections contain unlocked fields only, fixed `steam_web_api` provenance and server
receipt time. An empty successful list is not proof of game completion or missing
progress; unavailable/expired is explicitly unknown, not zero achievements.
Returned SteamID must exactly match the signed-in account's stored identity. If the
response includes numeric AppID it must match; when absent, game binding is the
fixed request AppID, not an invented response identity inferred from gameName.
Live provider compatibility is not established by synthetic tests.

Requests use the fixed HTTPS public Steam API endpoint, `x-webapi-key` header,
no redirects or environment proxy, bounded timeout/body, and narrowly scoped
httpx/httpcore log redaction. Unrelated security logs remain intact. Provider keys,
SteamID queries and raw provider errors are never sent to UI/MCP or transport logs.
No GetSchemaForGame catalog is downloaded or bundled. Game text is runtime provider
data, not licensed as part of this repository's MIT source.

The additive `achievement_cache` table has a server-generated consent generation
and refresh nonce. External I/O runs outside the DB transaction; the result is
committed only if both still match current selection and grant. Revoke/regrant
therefore cannot resurrect an older in-flight result. Scope/game/all-access revoke
removes the cache immediately. Device pairing never accepts achievement scope.

### Curated game discovery (identity only)

The static discovery list is a small editorial selection, not a live popularity
ranking or the user’s owned Steam library. AppIDs and titles were checked on the
official Steam store on 2026-10-31 (some titles are shown with normalized typography
and without trademark symbols/edition marketing suffixes). No store descriptions,
artwork, screenshots, reviews, achievement catalogues or save data are bundled.
No HTTP lookup is performed while rendering.

Discovery does not add games to an account: the player explicitly adds one, then
reviews selection and separate permissions. “All current” still means only that
account’s current presets/registered games; a future discovery entry never expands
selection or consent. Only Belmont currently has the reviewed four-scalar parser.
Other entries offer optional local-file metadata, not interpreted progression.
Steam Cloud is unavailable; achievements remain operator-configured and opt-in.

Verified identity sources:

- [Castlevania: Belmont’s Curse](https://store.steampowered.com/app/4231820/) — `4231820`.
- [Elden Ring](https://store.steampowered.com/app/1245620/) — `1245620`.
- [The Witcher 3: Wild Hunt](https://store.steampowered.com/app/292030/) — `292030`.
- [Baldur's Gate 3](https://store.steampowered.com/app/1086940/) — `1086940`.
- [Cyberpunk 2077](https://store.steampowered.com/app/1091500/) — `1091500`.
- [Red Dead Redemption 2](https://store.steampowered.com/app/1174180/) — `1174180`.
- [The Elder Scrolls V: Skyrim Special Edition](https://store.steampowered.com/app/489830/) — `489830`.
- [Fallout 4](https://store.steampowered.com/app/377160/) — `377160`.
- [Stardew Valley](https://store.steampowered.com/app/413150/) — `413150`.
- [Terraria](https://store.steampowered.com/app/105600/) — `105600`.
- [Hollow Knight](https://store.steampowered.com/app/367520/) — `367520`.
- [Hades](https://store.steampowered.com/app/1145360/) — `1145360`.
- [Subnautica](https://store.steampowered.com/app/264710/) — `264710`.
- [Kingdom Come: Deliverance II](https://store.steampowered.com/app/1771300/) — `1771300`.
- [Monster Hunter Wilds](https://store.steampowered.com/app/2246340/) — `2246340`.
- [Sekiro: Shadows Die Twice - GOTY Edition](https://store.steampowered.com/app/814380/) — `814380`.
- [DARK SOULS III](https://store.steampowered.com/app/374320/) — `374320`.

### Optional owned-Steam-library discovery

This separate **account-level `library.read` opt-in** is represented by an enabled
`library_cache` consent row; it is not a per-game data grant. Operator API access
must be configured first; players never provide keys. Exact POST forms:
`/account/library/permission` takes `csrf,enabled=yes|no`, and
`/account/library/refresh` takes only `csrf`. Both require the existing site session
and exact Origin. Nothing is fetched on login, page load, MCP reads or consent alone.
The owner/SteamID is derived exclusively from the authenticated session.

The fixed public HTTPS `IPlayerService/GetOwnedGames/v1/` request uses the operator
key header and `input_json` with SteamID, `include_appinfo=true` and
`include_played_free_games=true`. Only bounded AppID/name pairs survive; playtime,
icons and other profile fields are discarded. The provider response may omit
identity, so provenance is request-bound; any returned SteamID must match. This
is not an independently verified current license entitlement. Empty/missing/private
responses—including an empty reported list—are conservatively **unavailable/unknown**,
never a claim that the account owns zero games. Games must be visible to the API.
[Official method documentation](https://partner.steamgames.com/doc/webapi/IPlayerService#GetOwnedGames).

No library result is automatically registered, selected or granted save/achievement
access. The user explicitly adds individual games and then uses the existing
selection/review flow. The cached personal library is shown on the account website,
not added to MCP progress responses. Curated discovery is a separate public list.

Storage is capped at128 consent/cache rows globally, one per account, with at most
256KiB retained AppID/name JSON per row (32MiB total payload ceiling, excluding DB
metadata/overhead). Responses are limited to1MiB,1000 games and120-character names;
exceeding limits produces unavailable, not a misleading truncated library. Cache
expires after24h; expired payload is cleared on access and bounded100-row batches
when consent is enabled. Refresh cooldown is15minutes, limited to4 attempts/hour
per account and60/hour globally. Achievement/library calls share two in-flight slots.
No scheduler, paid scaling or new infrastructure is required.

External I/O runs outside database transactions. Consent generation and refresh
nonce must still match before storing results; disable/re-enable cannot resurrect
an older response. Disabling library access or revoking all account access deletes
this cache immediately. Live access still requires separately authorized secure
operator-key configuration; all implementation tests use synthetic transports.
