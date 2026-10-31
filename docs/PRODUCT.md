# Steam Game Companion — product specification v0.3

## North star
An opt-in AI gaming copilot that knows which game the user is playing, what the user has completed, and recommends a verified next step with a map, source and confidence level. Never assert game state from achievement absence alone.

## Delivery modes and current status
- **Target baseline: no installation.** A permitted cloud source supplies changes, and a separately authorized, verified channel delivers neutral notifications. This is not yet available: Steam Cloud authorization, automatic cloud ingestion and native chat push have not been established.
- **Optional PC/Steam Deck companion.** A local read-only watcher can provide nearer-to-real-time observations from explicitly allowed files. It is not a prerequisite for the target cloud baseline, and neither instantaneous delivery nor complete game-state understanding is guaranteed.
- Repeated manual save uploads are not the automatic baseline. Steam sign-in alone does not grant cloud-save access. See [cloud sync and notification constraints](CLOUD_SYNC_NOTIFICATIONS.md).

The owner-approved Render Free + Neon beta is live at https://game-assist.onrender.com; source is published at https://github.com/sevakode/game-assist. HTTPS, health, OAuth metadata and companion ZIP checks passed for runtime `6ff1b5cc05b84f75ca1cb07c855a31ce512d570a`; the documentation baseline on main was `2b752021c8c7ddcb887ac5d12986b085a1215687`. The prior regression passed 197 tests using disposable real PostgreSQL. These are historical checkpoints, not a pass for backend/UI work now in progress or real-device acceptance. A phone screenshot suggests Steam website sign-in succeeded; application identity linking and end-to-end OAuth remain unverified.

## Identity architecture — separate authorization boundaries
1. **ChatGPT ↔ Companion MCP**: OAuth 2.1 authorization code + PKCE, resource indicators, issuer metadata, protected resource metadata, audience-bound short-lived access tokens, refresh rotation, revocation. ChatGPT authenticates to *our* service, not directly to Steam.
2. **User ↔ Steam**: Steam OpenID 2.0 for sign-in and SteamID. Steam partner OAuth is a separate Valve-approval path for cloud scopes, not available to an arbitrary consumer app by default. No request for Steam passwords, Steam session cookies, or user-supplied API keys.
3. **Optional desktop agent ↔ Companion**: device authorization/pairing with short-lived code and scoped device credential. File access is local and read-only.

## Consent model
A Steam identity link is not consent to scrape the user's entire library. After login, user selects individual games, a collection, or all currently available games. 'All games' never silently expands to future games without a separate opt-in. Default one game. Per-game scopes:
- library.read: names, AppIDs, cover art, playtime if Steam exposes it under applicable privacy/access rules
- achievements.read: unlocked achievements and timestamps when available
- stats.read: in-game statistics when exposed
- saves.metadata: path, size, hash, modification time (never file contents)
- saves.read: explicitly selected save contents, locally decoded by trusted parsers; upload only when separately approved
- activity.read: currently/recently played, where permitted
- recommendations: AI interpretation of already-granted data; choose whether progress is shared with ChatGPT
- notifications: optional push/check-ins; off by default

Show a permissions matrix and data preview before consent. Save access off by default. Bulk selection has a review screen listing game count, scopes and data sources. Allow per-game pause, revoke, delete, export, retention controls, audit history. Steam API limitations may make some scopes unavailable; disabled permissions are labeled clearly. No write/delete save permissions in v1.

## Progress engine
Evidence = Steam achievements + game stats + decoded saves + map/profile + user confirmation. Distinguish verified, inferred and unknown. Each suggestion includes provenance, spoiler setting, prerequisites and route. Conflicts remain unresolved until verified. Target background jobs poll permitted achievement sources subject to limits; the optional local watcher uses stable-write debounce. Cloud-source polling requires independently verified authorization and scheduling. Never upload raw files by default; do not label achievement activity as a new save or a metadata change as completed cloud sync.

## Platform
Current beta uses Python/FastAPI, PostgreSQL on Neon (SQLite for local development), Render HTTPS, hosted OAuth/MCP and a web UI, with an optional Python companion. Do not infer deployed Redis workers, React, signed installers or reliable background scheduling from the roadmap. Windows/Linux/SteamOS packaging, auto-update, system tray, explicit path allowlists and real Steam Deck permissions remain platform acceptance work. Free-host sleep must be included in latency and scheduler design.

## Game profile: Castlevania Belmont's Curse (AppID 4231820)
The current optional device path accepts a restricted four-field structural projection for observed JSON save format `1.1.3`, not a validated completion model. Health/mana fragment counters are not proven completed upgrades, and current health/mana are not maxima. Exact pickup IDs, locations, boss/item/map completion and broader version support require consented fixtures, controlled before/after evidence and independently reviewed source records. Never conflate save metadata with progress; unsupported interpretations remain unknown.

## MVP acceptance — gates, not completed claims
- Steam OpenID callback verified server-side; account linking and unlinking work
- ChatGPT OAuth PKCE + token audience, scope, rotation and revocation tested
- Games chooser: one/all/custom; per-game permissions persist and enforce on every MCP tool
- Achievement retrieval works for permitted public/accessible profiles; privacy errors explained
- Baseline cloud mode: authorized game-specific source, version detection, reliable allowed scheduling, separate notification consent and verified delivery; no-install does not mean OpenID grants save access
- Optional companion mode: agent detects stable save changes without touching originals; real Windows/Linux/SteamOS and Game Mode tests
- MCP tools list_games, get_achievements, get_save_status, get_progress, suggest_next_step; no out-of-scope disclosure
- Security review, CI, onboarding, privacy policy, landing, operational monitoring

## Blockers
Steam partner OAuth for read_cloud is subject to Valve approval and AppID scope. Standard OpenID cannot grant it. Arbitrary private Steam libraries/achievements cannot be guaranteed via public APIs. The default Render HTTPS hostname, Neon database and public GitHub repository are provisioned; a custom domain is not required for beta. Remaining gates include official cloud access, real identity/OAuth acceptance, native assistant notification support, legal review, validated real saves and HP/mana mappings, real Deck tests and a signed release pipeline. An internal event or website inbox does not establish a native chat push channel.
