# Native POST forms: Referrer-Policy candidate

Base: `5a1acb79bad44555da5270411aa328ea19285f6a`.
This is a local candidate, not a deployment or a confirmed diagnosis of the user's request.

## Problem and narrow change

The document boundary previously emitted `Referrer-Policy: no-referrer`.
[Fetch: append a request Origin header](https://fetch.spec.whatwg.org/#append-a-request-origin-header)
sets the serialized Origin to `null` for non-GET/HEAD, non-CORS requests under that
policy. Ordinary HTML form navigations fall into this category. The unchanged
server correctly rejects `Origin: null`. Manually supplying a valid Origin in
ASGI tests does not exercise browser generation of that header.

The candidate emits `strict-origin` from Boundary. For same-origin HTTPS form
submissions this preserves the exact Origin. According to
[Referrer Policy §3.5](https://w3c.github.io/webappsec-referrer-policy/#referrer-policy-strict-origin),
Referer contains only the origin, including on cross-origin HTTPS navigation,
and is omitted on an HTTPS downgrade to a non-trustworthy destination.
Paths, query parameters and OAuth request identifiers are not included in Referer.
This intentionally permits origin-only attribution where no-referrer omitted
Referer entirely. Existing `rel=noreferrer` links may remain more restrictive.

Boundary removes upstream Referrer-Policy headers case-insensitively before
writing one authoritative policy. This also handles the standalone
data-handling response, whose own no-referrer is retained when used outside
Boundary. The integrated document receives exactly one strict-origin header.
No data_handling renderer edit is necessary. Its integrated-header test and
description are updated to reflect the actual boundary behavior.

No change to session validation, Origin comparisons, CSRF validation, OAuth,
scope checks, cookies, CSP, allowlists or source readers. Missing, null and
other Origin values and stale CSRF still produce 403 on protected forms.

## Validation

`tests/test_remote_native_forms.py` uses actual local app routes, temporary SQLite,
synthetic Steam identity, a fake library reader, and an explicitly disabled
achievement reader. It never creates production registrations or grants.

Five always-on application contracts cover:

- Native HTML form fields parsed from /games; opt-in and manual refresh; rejected
  Origin/CSRF inputs do not fetch Steam or enable the source.
- Device approval fields from /devices/approve; rejected submissions do not bind
  the pairing or grant scopes; exact game/scopes still required; valid approval
  can be polled for a synthetic device token.
- OAuth consent fields from the real authorization page; rejected submissions
  retain the pending request; accepted consent preserves state/iss and can be
  exchanged with the original S256 verifier and resource.
- A form from before a second login remains invalid; a freshly rendered form works.
- Single effective Referrer-Policy on normal, static and error responses;
  no-store, HSTS and CSP protections remain.

Three optional Chromium tests intercept **all** requests and bridge only
assist.example to the local ASGI app. Other destinations are fulfilled locally.
They cover original no-referrer failure, strict-origin library forms, and
pairing/OAuth form navigation including callback Referer minimization.
They require an already-installed browser, explicitly enable Chromium sandbox,
do not install binaries and do not disable protections.

### Results in this environment

Focused suite: 8 tests = 5 passed, 3 skipped (Chromium executable not installed).

Broader synthetic regression: 65 tests = 62 passed, 3 skipped, no failures.
Modules: test_remote_native_forms, test_remote_library, test_remote_service,
test_remote_oauth, test_remote_browser_flows, test_data_handling_integration.

The broader run explicitly replaced default reader constructors with instances
having `api_key=''`, avoiding reads of the operator key from environment.
No real PostgreSQL was used; no PostgreSQL tests were run. Steam/AI responses
were synthetic. Existing Starlette/httpx and Pydantic warnings are unrelated
and dependencies were not changed.

Reproduce the focused application contracts:

```sh
python -m unittest discover -s tests -p test_remote_native_forms.py -v
```

Reproduce the broader run without reading a configured Steam API key:

```python
import sys, unittest, logging
from unittest.mock import patch
sys.path.insert(0, 'tests')
logging.disable(logging.CRITICAL)
from remote_server.achievements import AchievementReader
from remote_server.library_reader import LibraryReader
names = ['test_remote_native_forms', 'test_remote_library', 'test_remote_service',
         'test_remote_oauth', 'test_remote_browser_flows',
         'test_data_handling_integration']
with patch('remote_server.app.AchievementReader',
           side_effect=lambda: AchievementReader(api_key='')), \
     patch('remote_server.app.LibraryReader',
           side_effect=lambda: LibraryReader(api_key='')):
    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromNames(names))
raise SystemExit(not result.wasSuccessful())
```

## Remaining acceptance

Actual Chromium validation **has not run successfully** here. A parallel
browser probe was also reported blocked before launch by sandbox ownership;
its protections were not bypassed. Neither probe is reported as passed.

The Fetch Standard and application contracts support this fix candidate, but
the actual Origin header of the user's failed POST is unknown. Review and a
permitted browser check are still needed. After any approved deployment, the
owner must open a fresh page: an already-open document can retain the old policy
and old CSRF. Do not weaken checks to make stale forms succeed.
No production POST, real source refresh, credential read, push or deploy was performed.
