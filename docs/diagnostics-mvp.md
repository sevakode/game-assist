# Diagnostics MVP — integrated candidate for review

Base: `987b9a7a4b3d0e6ea2cb5b1aab2f7c2bb3623575` (sevakode/game-assist).
This candidate integrates server events and a local browser report preview. It is not
published or deployed. Report submission/storage remains disabled: no new database
schema, retention configuration, external provider, account, key or MCP write scope.

## Working flow

1. Run the existing deployment entrypoint `python -m remote_server` with the existing
   approved configuration. `create_app` installs the allowlist stdout sink; the entrypoint
   passes `log_config=None` so Uvicorn cannot overwrite it, and keeps access logs disabled.
   Alternative ASGI launchers must not reconfigure logging after factory creation.
2. Every HTTP response gets a fresh random 128-bit `X-Request-ID`. A single safe event is
   emitted at request completion. Inbound IDs are ignored; no token/code/hash, owner ID,
   SteamID, URL/query, header/cookie, body, upstream exception text, save data, local path
   or account library appears in events. Normal responses and outer framework errors
   retain the existing security policy, including `Referrer-Policy: strict-origin`.
3. A signed-in user visits `/diagnostics`. Select known classified facts, leaving others
   `unknown`. Click “Подготовить и просмотреть”, inspect the JSON, then optionally click
   “Сохранить просмотренный JSON локально”. Edits invalidate the previous preview. No
   collection, fetch, localStorage, submission or automatic download occurs. The page
   has no form submission and CSP `connect-src 'none'`. Only the GET page and static
   script are served; POST submission routes do not exist.
4. An agent can prepare the same flat allowlisted report with `diagnostics.report`.
   This does not grant permission to submit it or any access to server logs. The browser
   preview requires the existing session; a progress.read bearer credential cannot use
   it as a session. MCP tool listings/scopes are unchanged.

```python
from diagnostics.report import build_report, serialize_report
report = build_report(component='deck', stage='install',
    reason='install_interrupted', installation='interrupted',
    python_version='3.12.0', platform='linux')
preview = serialize_report(report)  # Explicit local preparation only.
```

The page does not import whole doctor outputs or raw logs. Version fields are numeric
release triplets or `unknown`. Request ID/status are optional manually supplied facts.
Report data is user-asserted, not proof of identity, ownership or causation.

## Modules and integration

`remote_server/observability.py` implements a pure ASGI wrapper outside Starlette's
ServerErrorMiddleware, a strict event sink and context-local classification. Its state/
routes interface delegates to the underlying app. Route categories come only from an
exact static map; unknown routes emit `unknown`, never a path string. Pairing start,
approval and poll have distinct static categories. Pending/expired pairing, Origin and
CSRF errors have explicit reason annotations. Unclassified 403 remains `unknown`.

Context resets after success, failure, cancellation and sink failure. Child-task
classification cannot mutate its parent's state. Failed streams retain the status already
sent, with an error reason; no response body is read or replaced. Application exceptions
are rethrown; their text is never formatted by this sink. Sink failures are ignored.

`remote_server/app.py` preserves auth, body bounds, Origin and CSRF checks. Existing
response-header policy was moved to an outer ResponseSecurity wrapper so TrustedHost
and generated 500 responses receive it too. The only new routes are readonly GET
`/diagnostics` and `/assets/diagnostics.js`. Existing route bodies and OAuth scopes are
unchanged. `remote_server/__main__.py` prevents Uvicorn logging reconfiguration.

`diagnostics/report.py` and `report.schema.json` define the strict flat report contract:
2048 UTF-8 bytes maximum, required fields, no unknown fields, exact types, bounded versions,
closed enums and optional request ID/status. Python parsing rejects duplicate keys,
invalid UTF-8 and nonfinite numbers. Errors contain a fixed code, never submitted values.
`diagnostics/events.py` prepares explicit client events using the same report vocabulary.
`diagnostics/preview.py` and `preview.js` serve the readonly browser preparation flow;
the JavaScript validator uses the Python schema constants, not a separately maintained
schema. It displays values via textContent and never sends them to the server.

Known report reasons cover interrupted/partial installation, unit mismatch, unavailable
working directory/venv, failed service, pending/expired/denied pairing, consent, network
and upstream failures. Supply these only after an existing trusted check establishes the
classification. No new host inspection or Deck client behavior is added.

## Logging and correlation limits

The configured root sink drops arbitrary logs; it does not redact unknown log text.
Existing HTTPX/HTTPCore/Uvicorn handlers are redirected to it. Actual HTTPX URL logging
at DEBUG/INFO and SDK OAuth synthetic requests are covered by integration tests.
Other named handlers, later logging reconfiguration, direct stderr/print and provider/
reverse-proxy logging are outside this guarantee. Review these before release; do not
claim total redaction. Generic third-party warnings/tracebacks reaching this sink are
intentionally discarded, so diagnostics use only fixed fields/reasons.

Request IDs never authorize access to events, reports or another account. There is no
public or owner-facing event lookup endpoint. A request ID alone cannot establish report
ownership. Existing stdout retention/access and account-deletion limitations are operator
settings; this candidate cannot delete provider log history by owner.

## Review and release sequence

Apply the immutable patch to the exact base, review app/entrypoint middleware ordering,
verify final logging configuration and packaging includes `diagnostics/preview.js` and
schema modules, then run synthetic tests. No deployment is part of this task. Root owns
publishing approval. Keep report POST routes/storage absent until the explicit gate below
is resolved. Deck package/client updates and pairing-flow correlation remain separate.

## Submission gate and future first-party web flow (disabled)

Keep this disabled until operator decisions below and a separate integration review.
Use the existing authenticated browser session, `Store.session(require_owner=True)`,
exact `config.issuer` Origin and existing CSRF semantics for **both** mutations. Reject
absent/null/other Origin on these POST routes; the event classifier never replaces the
guard. No bearer/device token or `progress.read` scope can submit a report.

1. A signed-in user opens an authenticated report form. They paste/import only the
   bounded JSON report; no file attachments or free text. Render fields escaped, with
   an explicit list of what will be sent and the approved expiry information. Avoid
   storing this preview in localStorage or URL/query. Return `Cache-Control: no-store`.
2. `POST /account/diagnostics/preview`: verify session, CSRF, exact Origin; enforce a
   bounded envelope while reading the body (before parser), then strict `parse_report`.
   Propose a maximum envelope of 4096 bytes for the 2048-byte report plus CSRF. Parse
   duplicate fields strictly. Do not log payloads or tokens even on validation failure.
   Store a short-lived pending draft bound to the session and owner from the session,
   plus a server-generated nonce hash and canonical report hash. Never accept owner,
   expiry or nonce selection from the submitted report. Apply draft quotas too.
3. Show a preview of the canonical saved draft. The human clicks a clearly labelled
   “Send diagnostic report” confirmation. No auto-submit, hidden MCP write or agent
   confirmation. `POST /account/diagnostics/confirm` repeats session+CSRF+exact Origin
   checks, consumes the one-use session-bound draft nonce, and atomically persists that
   exact draft. Expired/replayed/other-session nonces fail. Use transactional quotas and
   idempotency so retries neither duplicate reports nor change the previewed content.
4. Only private operators with separately approved operator authorization can list/read
   the queue. Session login alone must not grant operator access. No public issues,
   public report links, search by arbitrary owner, raw-log endpoint or client log export.
   Owner-visible receipts use session-scoped queries and contain no other owner's data.

### Minimal schema delta for later integration

Design only; do not apply migrations or deletes now. Use the existing database abstraction
and serialized transactions for SQLite/Postgres, with migrations reviewed for both.

- `diagnostic_drafts`: random id, owner (session-derived), session-binding hash,
  nonce hash (unique), canonical report JSON, canonical hash, created_at, expires_at.
- `diagnostic_reports`: random id, owner (session-derived), canonical report JSON,
  created_at, expires_at, closed-enum queue status, unique consumed draft id.
- Index owner+created_at and expires_at on both tables. Bound rows AND payload bytes.
  Keep owner as private relational metadata; never include it in report JSON or events.
- Atomic per-owner, per-session and global draft/report quotas; separate submission
  rate limits with bounded bucket cardinality. Fail closed at capacity. Do not evict
  another owner's report to satisfy a new submission. TTL cleanup must cover pending
  drafts, reports, idempotency rows and quota metadata; enforce expiry on reads too.
- Account deletion's future transaction must delete **both** tables and associated
  receipts/quota/idempotency rows by owner, including pending drafts. No orphaned blobs,
  attachments or external provider records exist. Coordinate with the unwired account
  deletion module. Do not assume a foreign key exists: current schema uses textual
  owner fields, so explicit ownership cleanup and cross-owner tests are needed.

### Decisions required from the operator

Approve report/draft retention periods, cleanup cadence, global/per-owner quotas and
rate windows, who may operate the private queue and how that access is audited, existing
Render log retention/access settings, and the actual user-facing data-handling notice.
These are **not configured** by this patch. No retention duration, privacy policy or
new provider is implied. Request IDs/diagnostics can be correlatable even without a
stable user ID. Existing stdout log retention and account-deletion implications must
be disclosed accurately; this module cannot delete provider stdout history by owner.

### Integration acceptance gates

Use synthetic local sessions only: missing/wrong/duplicate CSRF and Origin, expired and
cross-user sessions, changed draft after preview, nonce replay, concurrent quotas, oversized
streamed body, no free text/unknown fields, TTL expiry and owner deletion including drafts,
operator access separation, no MCP write through read scopes, no automatic submission,
and all existing auth/device guards unchanged. None of the new web flow is claimed tested
or active here. Actual create_app integration tests verify rejected responses, browser preview authorization, and absent submission routes.

## Reproducible local checks

```
python -m unittest discover -s tests -p 'test_diagnostics_reports.py' -v
python -m unittest discover -s tests -p 'test_remote_observability.py' -v
python -m unittest discover -s tests -p 'test_diagnostics_integration.py' -v
python -m unittest discover -s tests -p 'test_remote_*.py' -v
```

New tests use synthetic ASGI calls, the actual create_app factory, a Node DOM harness and HTTPX MockTransport: sentinels in URL/query,
headers/cookies, bodies, exception messages and report fields; strict types/size/extra
fields; duplicate JSON keys; concurrent request IDs; no inherited child classification;
context cleanup; cancellation/stream errors; failing sinks; known failure codes; Origin
classes; DEBUG HTTPX logs. No real service or production data is accessed.

## Future pending-pairing correlation protocol (design only)

The current ASGI request ID identifies one HTTP request. It does **not** link a pairing
begin/start request to later approval and poll requests. A future pairing-flow
correlation ID must be a fresh, independent cryptographically random non-credential
identifier per pairing attempt. Never reuse user_code, device_code, pairing/device
credentials, OAuth tokens, owner identifiers, or any hash of those values. A hash of
a credential is not an acceptable diagnostic correlation identifier.

Generating such an ID alone is insufficient: future protocol/schema work must explicitly
persist the non-secret association and emit allowlisted metadata (flow ID, per-request ID,
static pairing stage and fixed result/reason) at begin, approval and poll transitions.
Do not log raw request/response payloads, secrets or identifiers to reconstruct the link.
Treat that flow ID as correlatable metadata with bounded lifetime and private access,
never as authorization to approve, poll, fetch diagnostics or access another account.
Pending, expired, denied and successful attempts need distinct, known transition codes.
The association and metadata must follow approved expiry and ownership/deletion rules.

Backward compatibility is required. This patch does not change the live pairing API,
existing client contract, report schema or event schema. Future integration needs an
explicit protocol/schema review: old clients must continue working without new required
request fields, changed token semantics, or response changes rejected by strict parsers.
Prefer server-internal correlation initially; any client-visible optional extension needs
compatibility tests against the old Deck client before rollout. No new ID is active here.

## Preview presentation follow-up

The preview reuses `remote_server.ui.page` and its verified `/assets/console.css`
asset route, without changing global UI files. It inherits the dark console navigation,
focus styles, 48px controls and phone-width action layout. All visible choices have
Russian labels while option values remain the exact schema enums. Only the three
problem fields are expanded initially; device and technical details are optional
collapsed sections. Empty version inputs map to `unknown` locally. Ordinary Back and
Cancel links return to `/games`; saving still requires preview and an explicit click.
Transmission remains disabled. No endpoints, permissions, report fields or persistence
were added. Rendered mobile/Deck appearance should be checked by the root's browser QA.

The explicit reset button clears inputs, preview and validation state without navigation or
network activity. Validation marks and focuses the relevant field, opens its optional
section if needed, and shows a fixed Russian hint via aria-describedby; values are never
echoed into errors. Controls inherit the existing console 48px minimum target height.

The preview uses the existing console pre rule (max-width:100%, overflow:auto,
white-space:pre-wrap, overflow-wrap:anywhere) within the min-width:0 main column.
This wraps long allowed IDs and pairing values instead of widening the page; the
preview is keyboard focusable. Wrapping is presentation only and does not alter the
serialized string used by the explicit download. Verify page scrollWidth at 320/392px
in the root managed browser against the merged global CSS.
