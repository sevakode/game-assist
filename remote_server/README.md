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
2. Deck calls `POST /v1/devices/pair/start {}`. Browser enters the displayed code at
   the returned `/devices/approve`, explicitly chooses AppID 4231820 and permissions.
   Summary is the existing version-1.1.3 **four raw player fields**, not HP/mana maxima,
   pickup identification or established collectible semantics. Metadata grant is
   selectable but metadata ingestion is intentionally unavailable.
3. Deck polls `POST /v1/devices/pair/poll {"device_code":"…"}` at five-second intervals.
   Pending returns `status:pending`; approval returns `status:approved`, `device_token`,
   `token_type:Bearer`, `expires_in:2592000` **once**. Expiry/replay requires restarting
   pairing. Device credential expires after 30 days and requires re-pairing; automatic
   device credential refresh is not implemented. This is not yet indefinite seamless UX.
4. `POST /v1/device/observations` uses that device bearer and exactly
   `{event_id:<UUID>, appid:4231820, kind:"save_summary", payload:<safe_summary>}`.
   Owner comes only from the token; all extra fields are rejected. No upload endpoint
   for raw saves, filenames, paths, world/entity IDs, SteamIDs or achievements exists.
5. MCP client connects to `https://HOST/mcp`, discovers protected-resource and OAuth
   metadata, uses public-client DCR (`token_endpoint_auth_method:none`), authorization
   code + S256 PKCE + state + exact resource. Browser gives separate read-only consent.
   Website login continues to the pending consent screen. The official MCP SDK owns
   the OAuth protocol endpoints, authentication, PKCE verification and MCP transport;
   application provider hooks own persistent opaque credentials and consent.
6. `get_progress` / `suggest_next_step` accept no owner/game IDs, return only the
   caller's currently allowed four-field projection or unknown state, and do not expose
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

All sixteen tables (sessions, login states, Steam nonce reservations, grants,
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
