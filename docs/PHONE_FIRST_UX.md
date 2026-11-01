# Phone-first Game Assist

The main path is Steam sign-in → choose a game → start a conversation on the phone. Deck installation and Desktop Mode are not prerequisites for this path.

`/start` reuses the existing route. Its default view offers a copyable, public-only starter message for Claude or another AI and links to Claude and ChatGPT. Without a connector, the AI only knows what the player tells it. Copying or opening the AI does not connect an account, transfer Steam data, grant access or confirm a successful connection. The optional Claude connector setup remains in a closed details section; its endpoint, OAuth instructions and separate optional library permission are preserved. `/start?step=choose` retains the detailed tool-aware prompt; `/start?step=play` remains available. There are no new routes or backend requirements.

Deck setup is under “Ещё” in the navigation. `/setup` remains a valid deep link and offers an immediate return to the phone conversation; installation instructions are inside an explicit advanced section. No silent install or automatic grant is added. The companion still has its existing Desktop Mode requirements; this change does not pretend those requirements disappeared.

The selected-game view reports the source and receipt time of authorized library/achievement snapshots. Disabled, unavailable, not-requested and expired states remain distinct. A save snapshot is shown only when actual summary data is in the projection; metadata or an achievement never establishes the current inventory or save state. Unknown sources stay unknown. Receipt time is not the time of saving the game or proof of current live progress. Ordinary Steam OpenID does not grant Steam Cloud access.

## Verification boundary

Independent integration review makes unknown cache states explicit rather than
claiming a refresh was never requested. Private/rate-limited sources are unavailable.
The manual prompt and page also state that pasting a website link does not connect
account data; tool-returned text is data, not instructions.

UI/route tests use synthetic sessions and snapshots. Copy handling can be tested in a Node VM without a browser, including a pending repeated click and clipboard denial/manual-selection fallback. Native Back/Forward, mobile geometry and real clipboard APIs still require managed-browser QA. Do not disable Chromium sandbox protections to run them.

No real Steam library retrieval, real Claude connection or real Deck acceptance is implied by these tests. The source remains an independent experimental project; external AI spoiler compliance cannot be guaranteed.
