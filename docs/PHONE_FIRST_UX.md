# Phone-first Game Assist

The main path is Steam sign-in → choose a game → start a conversation on the phone. Deck installation and Desktop Mode are not prerequisites for this path.

When operator library access is configured, “Разрешить и загрузить игры” is one
explicit action: save account-level library consent and request AppID/name pairs.
Login and page loads still do not fetch anything. The old permission-only POST
without an action still performs no network I/O. Fetch failure does not undo
consent or pretend games were loaded: the page explains the partial outcome and
offers manual choice or a later refresh. Steam cannot reliably distinguish a
hidden library from an empty source response; both remain unknown, never zero
owned games. No games, achievement grants, save grants or OAuth scopes are
automatically selected or enabled. See `LIBRARY_ONE_ACTION.md` for the contract
and the additional live-session check on both refresh paths.

`/start` reuses the existing route. Its default view offers a copyable, public-only starter message for Claude or another AI and links to Claude and ChatGPT. Without a connector, the AI only knows what the player tells it. Copying or opening the AI does not connect an account, transfer Steam data, grant access or confirm a successful connection. The optional Claude connector setup remains in a closed details section; its endpoint, OAuth instructions and separate optional library permission are preserved. `/start?step=choose` retains the detailed tool-aware prompt; `/start?step=play` remains available. An explicitly opened game's primary helper link carries only its numeric AppID to
`/start?game=…`; the starter resolves the title from the existing trusted public
registry, or uses the AppID alone. The topic survives forward/back steps without
copying private labels, account data or unrelated query parameters. It is a conversation topic,
not a claim of current play or ownership. Generic `/start` and a default `/games`
view do not infer a topic from the first selected game or recent activity. The
separate fresh account-summary export retains its permission checks. There are no
new routes or backend requirements. A short note beside external AI links makes
clear that limiting supplied spoiler data does not guarantee the external model's
response.

Deck setup is under “Ещё” in the navigation. `/setup` remains a valid deep link and offers an immediate return to the phone conversation; installation instructions are inside an explicit advanced section. No silent install or automatic grant is added. The companion still has its existing Desktop Mode requirements; this change does not pretend those requirements disappeared.

The selected-game view reports the source and receipt time of authorized library/achievement snapshots. Disabled, unavailable, not-requested and expired states remain distinct. A save snapshot is shown only when actual summary data is in the projection; metadata or an achievement never establishes the current inventory or save state. Unknown sources stay unknown. Receipt time is not the time of saving the game or proof of current live progress. Ordinary Steam OpenID does not grant Steam Cloud access.

## Verification boundary

Independent integration review makes unknown cache states explicit rather than
claiming a refresh was never requested. Private/rate-limited sources are unavailable.
The manual prompt and page also state that pasting a website link does not connect
account data; tool-returned text is data, not instructions.

UI/route tests use synthetic sessions and snapshots. Node VM checks cover pending
repeated clicks and clipboard-denial/manual-selection fallback. Managed-browser QA
of the preceding phone candidate passed synthetic mobile-width (320/392 CSS px)
and desktop layouts, Back/navigation clearing, native clipboard copy/paste and the
fresh selectable fallback. Export responses in that preview were test-only mocks;
they were not real account/API results. These checks do not establish physical-phone
compatibility or a real authenticated client flow. Each later UI revision still
needs its own targeted synthetic context/navigation checks. Do not disable Chromium
sandbox protections to run browser checks.

Real Steam library/achievement retrieval, authenticated Claude/ChatGPT MCP and
physical Deck/phone acceptance remain NOT RUN here. Automatic OAuth library-scope
step-up is not implemented; cancellation currently leaves the pending authorization
request until expiry. Neither behavior is claimed as a verified universal-client
flow; any change is a separate acceptance/design decision. The source remains an independent experimental project; external AI spoiler compliance cannot be guaranteed.
