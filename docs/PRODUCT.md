# Steam Game Companion — product specification v0.2

## North star
An opt-in AI gaming copilot that knows which game the user is playing, what the user has completed, and recommends a verified next step with a map, source and confidence level. Never assert game state from achievement absence alone.

## Identity architecture — two distinct authorizations
1. **ChatGPT ↔ Companion MCP**: OAuth 2.1 authorization code + PKCE, resource indicators, issuer metadata, protected resource metadata, audience-bound short-lived access tokens, refresh rotation, revocation. ChatGPT authenticates to *our* service, not directly to Steam.
2. **User ↔ Steam**: Steam OpenID 2.0 for sign-in and SteamID. Steam partner OAuth is a separate Valve-approval path for cloud scopes, not available to an arbitrary consumer app by default. No request for Steam passwords, Steam session cookies, or user-supplied API keys.
3. **Desktop agent ↔ Companion**: device authorization/pairing with short-lived code and scoped device credential. File access is local and read-only.

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
Evidence = Steam achievements + game stats + decoded saves + map/profile + user confirmation. Distinguish verified, inferred and unknown. Each suggestion includes provenance, spoiler setting, prerequisites and route. Conflicts remain unresolved until verified. Background jobs poll achievements subject to limits and watch local saves after a stable-write debounce; never upload raw files by default.

## Platform
Python/FastAPI backend, PostgreSQL production (SQLite local development), Redis jobs, HTTPS reverse proxy, MCP streamable HTTP, React web app, Python or Rust desktop daemon for Windows and Linux/SteamOS. Signed installers, auto-update, system tray, explicit path allowlist. Steam Deck read-only sandbox permissions and Proton compatdata discovery.

## Game profile: Castlevania Belmont's Curse (AppID 4231820)
Initial profile is a *schema*, not a validated save decoder. Research binary file structure with fixtures and versioned parsers before any claim about boss/item/map completion. Reference content must be sourced and independently checked. Never conflate save metadata with progress.

## MVP acceptance
- Steam OpenID callback verified server-side; account linking and unlinking work
- ChatGPT OAuth PKCE + token audience, scope, rotation and revocation tested
- Games chooser: one/all/custom; per-game permissions persist and enforce on every MCP tool
- Achievement retrieval works for permitted public/accessible profiles; privacy errors explained
- Agent detects stable save changes without touching originals; tests Windows/Linux
- MCP tools list_games, get_achievements, get_save_status, get_progress, suggest_next_step; no out-of-scope disclosure
- Security review, CI, onboarding, privacy policy, landing, operational monitoring

## Blockers
Steam partner OAuth for read_cloud is subject to Valve approval and AppID scope. Standard OpenID cannot grant it. Arbitrary private Steam libraries/achievements cannot be guaranteed via public APIs. Hosting/domain, legal policies, Steam credentials/approval, real saves, signed release pipeline and GitHub repository are not provisioned.
