# Public AI discovery foundation

Base: `ef1cc6e2cb58711997256c9df36698822cfc54d9`. This slice adds only
`remote_server/discovery.py`, `tests/test_discovery_public.py`, and this document.
It is deliberately **not wired into production**. No push, deployment, search
submission, account creation, hosting change, or real client authorization occurred.

## Contract

`public_routes(issuer=config.issuer)` returns four GET/HEAD routes: `/connect`,
`/robots.txt`, `/sitemap.xml`, `/llms.txt`. Mount them directly on the existing app,
not as a separate unsecured service. The hub uses the existing CSS and a compact,
script-free layout (except inert JSON-LD). Existing OAuth `.well-known` endpoints
are untouched. No plugin manifest is generated.

`public_metadata(issuer, path)` supplies title, description, canonical and WebPage /
WebSite schema.org data. `public_head(issuer, path)` renders description, canonical,
OpenGraph and JSON-LD; it deliberately does not render another title. `connect_body`
and `connect_page` provide the hub independently of `ui.py`. All canonical/endpoint
URLs use the explicit trusted HTTPS origin, including self-host ports and IPv6.
Request Host, forwarded headers, queries, cookies and user-agent do not enter output.
Issuer must match the existing origin-only config contract, with no trailing slash.

The closed sitemap/metadata allowlist is `/`, `/connect`, `/connect/claude`, `/setup`.
There are no invented modification dates, ratings, reviews, endorsements or game
support counts. Accounts, callbacks, API/token routes, import, personalized games,
raw saves and query strings never enter the sitemap. Rendering performs no network
requests and does not access session, database, Steam or OAuth provider state.

Robots uses one wildcard group, allowing public documents and CSS while discouraging
crawling of private/operational prefixes. This also allows OAI-SearchBot on public
pages without giving bots different content. It does not add a distinct training
policy: GPTBot inherits the wildcard group. Search and model-training controls are
separate policy decisions. Robots/noindex are not access control; blocked URLs can
still be known to a search engine, and a disallowed crawler may not see noindex.

## Minimal integration plan (parent-owned changes)

1. In `remote_server/app.py`, import `discovery`. Inside `create_app`, after the
   existing route list, call `app.routes.extend(discovery.public_routes(issuer=config.issuer))`.
   Keep `SecurityMiddleware`, TrustedHost, session, CSRF, CORS and MCP/OAuth gates
   intact. Do not replace the app or mount a catch-all before OAuth routes.
2. Add a keyword-only `head` argument to `ui.page` and its `app.page` wrapper.
   Insert its trusted HTML immediately before `</head>`. Default it to
   `discovery.NOINDEX_HEAD` (or an equivalent literal) so existing private/error/
   consent views do not acquire public metadata. Only call `public_head` with
   hardcoded allowlisted paths, never `request.url` or a parameter supplied by users.
   Do not accept arbitrary unescaped head text from request data.
3. The `home` 200 response gets `head=discovery.public_head(config.issuer, '/')`;
   its legacy `?game=` redirect remains unchanged. `connect_claude` gets the
   `/connect/claude` head; both `setup_page` branches get `/setup`. Existing page
   titles may remain, or use `PUBLIC_PAGES[path][0]` while avoiding the UI helper's
   duplicate `Game Assist` suffix. Do not append descriptions or catalogues to
   the minimal homepage. The new `/connect` handler already supplies its own head.
4. Change the home connection CTA from `Подключить Claude` / `/connect/claude` to
   `Подключить AI` / `/connect`, and the general assistant navigation destination to
   `/connect`. Keep the hub's Claude-specific CTA and actual Claude guide unchanged.
   Do not alter consent UI. Update minimal-home navigation assertions to expect
   `/connect`; keep existing guide coverage.
5. Keep default noindex on `/games`, `/import`, account/consent/error pages. For
   non-HTML private responses add `X-Robots-Tag: noindex, nofollow` only as a
   supplementary measure in existing middleware if desired. Never remove auth to
   let crawlers read noindex. Do not apply a blanket noindex header to public routes.
6. Preserve CSP unchanged. JSON-LD is a non-executable data block; this change
   does not justify `unsafe-inline` or a broader `script-src`. Syntax is tested;
   actual search-engine parsing and rendered-page extraction require later live
   acceptance. No rich result or index inclusion is promised.

The helper exports no middleware and does not automatically add noindex elsewhere;
steps 2 and 5 are integration work, not a claim of current production behavior.

## Public claims and drift

Claude has a guide and a configured callback according to the task evidence, but
real user OAuth remains unproved. ChatGPT's RFC9207 code is not a configured client.
Other clients need Streamable HTTP, DCR/S256 and an exact approved callback. No
callback IDs or credentials appear in public copy. AI without connectors may read
public text when browsing is available, but gains no private tool access.

Steam login establishes identity, not Cloud access. Belmont 1.1.3 has four raw
fields; Elden Ring/Witcher 3 gameplay parsers are absent. Catalogue entries do not
count as parser support. Library and achievements require operator API configuration
and player permission; last-activity game detection is absent. Copy describes
requirements rather than asserting every self-host has a missing key. Refresh hub
and llms copy together when verified capabilities change; do not infer live success
from synthetic tests. MIT applies to project code, not third-party game content.

## Sources checked 2026-10-31

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features):
  ordinary SEO practices remain relevant; no special AI text file or schema is
  required. Indexing/serving is not guaranteed. Structured data must match visible
  content. This is why llms.txt is only an experimental public reference.
- [Google: robots.txt](https://developers.google.com/search/docs/crawling-indexing/robots/intro):
  crawl control is not protection of private content.
- [Google: sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview):
  sitemaps aid discovery; they do not guarantee crawling or indexing.
- [OpenAI: crawlers](https://developers.openai.com/api/docs/bots): OAI-SearchBot
  serves search; GPTBot controls a different use case. ChatGPT-User is user-driven
  and is not the crawler deciding search inclusion. None is an OAuth connector.
- [Claude: custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp):
  a remote MCP connector is configured in the client. Linking to a page alone does
  not prove Game Assist authorization or compatibility in a particular account.
- [OpenAI: build an MCP server](https://developers.openai.com/plugins/build/mcp-server):
  Streamable HTTP, authorization boundaries and real integration tests are required
  considerations. Protocol support alone does not establish a configured app.

Sources were consulted for this review, not fetched at request time. Provider
products and plan limitations can change; public copy avoids a frozen plan matrix.
No Search Console/Bing indexing observation or real Claude/ChatGPT/Deck acceptance
was performed. No search ranking or universal connection claim is made.

## Validation

Run `python -m unittest discover -s tests -p test_discovery_public.py -v`.
Tests cover exact public route ownership, methods, XML parsing, robots decisions,
allowlisted canonicals, self-host output, hostile text escaping, JSON-LD parsing,
query/header/cookie/UA independence, no outbound socket connection during rendering,
and mounting under existing security middleware with unauthorized MCP/account
requests still denied and existing OAuth metadata preserved.

The first local run identified that the existing MCP SDK serializes issuer metadata
with a trailing slash; the regression assertion follows that existing contract.
The discovery module deliberately keeps configured origin plus path for canonicals.
