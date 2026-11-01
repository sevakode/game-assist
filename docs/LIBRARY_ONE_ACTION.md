# One-action library opt-in and fetch — local candidate

The initial library form posts `csrf`, `enabled=yes` and the explicit
`action=enable_and_refresh` to the existing `/account/library/permission` route.
The button says “Разрешить и загрузить игры”. There is no new endpoint, browser
script, background job, login-time fetch or OAuth grant change. Permission-only
requests with no `action` retain their no-network behavior. Disable still deletes
consent/cache; manual refresh still posts only `csrf` to the existing route.

## Shared safety and outcome contract

- Both explicit fetch paths reuse the existing fixed, bounded Steam library
  reader, per-owner/global limits, shared slots and 15-minute cooldown.
- Consent is committed first. The combined action captures that consent
  generation; the shared helper checks it before I/O and rechecks it plus the
  reserved nonce before writing the result. Revoke/regrant cannot inherit a
  late result. Repeated clicks cannot start a parallel fetch for that grant.
- **Additional existing-path hardening:** the exact original session hash,
  owner, CSRF and expiry are checked inside the reservation and final write
  transactions. This also applies to manual refresh, which previously checked
  session validity only when the request started. Expiry/logout/rotation during
  I/O now returns 401 without writing the newly received payload. The prior
  attempted-at cooldown remains; no automatic retry is launched.
- Exact Origin, CSRF, strict fields and session-derived owner/SteamID remain
  required. No client-supplied owner, SteamID or scope is accepted. Granting
  library consent does not change selection, saves, achievements or OAuth.
- If a configured source fails, permission remains enabled and the list is
  unavailable. Empty, hidden and invalid/error responses are tested separately
  but intentionally remain unknown: Steam provides no reliable private-vs-empty
  discriminator. Never claim zero owned games or successful loading.
- If consent was saved but a quota/slot/cooldown prevents a request, the browser
  error says so and links to `/games#steam-library`. Capacity/configuration
  failures before consent do not claim permission was saved.

## Local verification

`tests/test_library_one_action.py` uses a real `LibraryReader` with an injected
synthetic `httpx.MockTransport`, fake Steam login and disposable SQLite. It covers
the form, exact guards, no-I/O compatibility, both-path parity, limits, repeated
clicks, source failures, owner isolation, consent generations, revocation and
pre/post-I/O session invalidation. Native-form and UI regressions are updated.

Run without production configuration:

```sh
env -u GA_TEST_POSTGRES_URL -u DATABASE_URL SGC_STEAM_API_KEY='' \
  python -m unittest discover -s tests -p test_library_one_action.py -v
```

Managed-browser mobile/Back/Forward validation is a separate review. Synthetic
tests do not establish live Steam, mobile-device, assistant or PostgreSQL
acceptance. No production access, publication or deployment is part of this
local candidate; publication needs its own exact change approval.
