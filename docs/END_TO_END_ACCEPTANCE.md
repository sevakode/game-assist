# Acceptance: no-install phone baseline + optional Steam Deck companion

## Definition of done
Two distinct paths must be evaluated without substituting one for the other:

- **Target baseline — no installation:** the owner signs in on a phone, authorizes a supported cloud source for one game, and separately opts into a verified notification channel. The service detects an actual permitted source change automatically and delivers a neutral, spoiler-safe notification. This path is currently blocked; Steam OpenID does not grant Steam Cloud access.
- **Optional nearer-to-real-time companion:** a real Steam Deck runs a user-authorized read-only companion in Game Mode. The owner explicitly pairs it on a phone, grants one game's safe summary, connects remote MCP to a supported mobile assistant, and observes updated allowed progress after a stable save. Deck installation is required only for this optional path, not for the target baseline.

No manual token copying or recurring file uploads is part of either final normal flow. A website inbox or MCP response is not proof of native chat push or an autonomous assistant turn. This document is a test plan, NOT evidence these steps have passed. See [CLOUD_SYNC_NOTIFICATIONS.md](CLOUD_SYNC_NOTIFICATIONS.md) for cloud-source and delivery constraints.

## First client target
Claude remote connector: configure via supported web flow, then verify native mobile tool use. Do not infer native Android/iOS connector support from desktop/web success or historical documentation; verify the actual client and account at acceptance time. Inbound MCP tool use and proactive notification delivery are separate gates. Check current official documentation before acceptance:
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities
- https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Gates

1. **Local regression:** all Python tests, UI tests, compileall, synthetic real HTTP ingestion; record exact revision/artifact.
2. **Hosting approval:** Render Free + Neon beta and its default HTTPS hostname are owner-approved and provisioned. Record approval for any new provider, cost, persistent credential or permission beyond that scope. Do not deploy the local single-token server. No secrets in source/archive/logs.
3. **Identity:** real Steam OpenID round-trip on phone, cancel/retry, wrong/expired/replayed state, CSRF. Browser diagnostic Steam login is not proof of application's OpenID integration.
4. **OAuth:** real Claude authorization-code+S256, exact callback validation, discovery, registration, consent, resource binding, token expiry/refresh rotation, replay rejection, revocation. Multi-user tests must demonstrate no cross-tenant disclosure.
5. **Optional companion — device:** code pairing expires, pending/denied states handled, phone approval explicitly shows game/scope/device. Credential stored privately on Deck; no bearer token in command line, URL or logs. Revoked device cannot upload and does not keep retrying aggressively.
6. **Optional companion — Deck install:** actual SteamOS dependencies, user-home-only installation, no sudo/pacman/read-only disable, original saves unchanged. Verify uninstall stops service; no original save deletion. Do not enable lingering or broader permissions silently.
7. **Optional companion — Game Mode:** service remains active across Desktop→Game Mode, Steam launch/exit, suspend/resume, connectivity loss, reboot and account login. Note expected stale status while Deck offline.
8. **Optional companion — save change:** one stable supported save produces only allowed sanitized fields; same bytes deduplicated, offline backlog bounded, corrupt/unknown-version files keep prior snapshot marked stale/unknown rather than clearing it.
9. **Phone result:** ask for progress in native supported assistant; compare fresh timestamp and known fixture fields. No secret achievement rows/IDs/counts, future locations or world-object identifiers reach the assistant.
10. **Privacy:** revoking one game's scope blocks API, MCP, export and ingestion promptly. Unlink does not mix old account data into new identity. Two users cannot claim the same device code or access one another's data.
11. **Game truth:** raw counters are NOT completed upgrades, current resources are NOT maxima. Exact HP/mana item mapping needs paired pickup evidence and reviewed world records. No all-achievement guarantee from raw account achievements.
12. **Cost:** record per-save/request bytes, idle request rate, DB size, rate limits, retries and monthly estimate at explicit user scale. 'Nearly free' is a target, not an unconditional promise.
13. **No-install cloud source:** document authorized access for the specific AppID; verify baseline, changed version, duplicate poll, lost permission, partial sync, rollback and source errors on a real source. Metadata changes are not proof of a completed whole-game sync. No cookies, credential extraction, scraping workaround or replacement with manual uploads.
14. **Notifications:** separately verified opt-in, recipient/channel, neutral template, deduplication, bounded retries, quiet hours and revoke-before-send behavior. Confirm actual phone delivery; independently establish whether it can trigger a new assistant turn. A synthetic source, optional device ingestion or website inbox alone cannot pass this gate.
15. **Scheduling and latency:** verify an authorized scheduler, free-host sleep behavior and actual detection/delivery latency; no hidden paid worker or real-time promise.

## Recorded beta checkpoint
As of 31 October 2026, runtime `6ff1b5cc05b84f75ca1cb07c855a31ce512d570a` was verified; documentation main was `2b752021c8c7ddcb887ac5d12986b085a1215687`. Source: https://github.com/sevakode/game-assist. The prior 197-test regression used real disposable PostgreSQL. It does not cover the parallel backend/UI changes now in progress; those need their own final regression and deployment checks.

## Current external blockers
Owner-approved Render Free + Neon beta is live at https://game-assist.onrender.com; public HTTPS/health/OAuth metadata/download checks passed. A phone screenshot suggests Steam website sign-in succeeded, but the full application identity callback/link and OAuth acceptance have not been verified. No actual Steam Deck hardware acceptance, Claude/ChatGPT connector OAuth acceptance, authorized automatic Steam Cloud ingestion, native chat push, or controlled before/after HP/mana pickup mapping has passed yet. These gates remain open even when automated tests pass.
