# Acceptance: phone + Steam Deck, no separate PC

## Definition of done
A real Steam Deck continues running a user-authorized read-only companion in Game Mode. The owner signs into Game Assist through Steam on a phone, explicitly pairs that Deck and grants one game's safe summary, connects the remote MCP to a supported mobile assistant, and observes updated allowed progress after a game save. No manual token copying or recurring file uploads is part of the final normal flow. This document is a test plan, NOT evidence these steps have passed.

## First client target
Claude remote connector: configure via supported web flow, then verify native mobile tool use. ChatGPT custom MCP currently documented web-only; do not mark native Android/iOS support passed from desktop/web success. Check current official documentation before acceptance:
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities
- https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Gates

1. **Local regression:** all Python tests, UI tests, compileall, synthetic real HTTP ingestion; record exact revision/artifact.
2. **Hosting approval:** owner selects HTTPS domain/provider and approves deployment and any cost, persistent credentials and permissions. Do not deploy the local single-token server. No secrets in source/archive/logs.
3. **Identity:** real Steam OpenID round-trip on phone, cancel/retry, wrong/expired/replayed state, CSRF. Browser diagnostic Steam login is not proof of application's OpenID integration.
4. **OAuth:** real Claude authorization-code+S256, exact callback validation, discovery, registration, consent, resource binding, token expiry/refresh rotation, replay rejection, revocation. Multi-user tests must demonstrate no cross-tenant disclosure.
5. **Device:** code pairing expires, pending/denied states handled, phone approval explicitly shows game/scope/device. Credential stored privately on Deck; no bearer token in command line, URL or logs. Revoked device cannot upload and does not keep retrying aggressively.
6. **Deck install:** actual SteamOS dependencies, user-home-only installation, no sudo/pacman/read-only disable, original saves unchanged. Verify uninstall stops service; no original save deletion. Do not enable lingering or broader permissions silently.
7. **Game Mode:** service remains active across Desktop→Game Mode, Steam launch/exit, suspend/resume, connectivity loss, reboot and account login. Note expected stale status while Deck offline.
8. **Save change:** one stable supported save produces only allowed sanitized fields; same bytes deduplicated, offline backlog bounded, corrupt/unknown-version files keep prior snapshot marked stale/unknown rather than clearing it.
9. **Phone result:** ask for progress in native supported assistant; compare fresh timestamp and known fixture fields. No secret achievement rows/IDs/counts, future locations or world-object identifiers reach the assistant.
10. **Privacy:** revoking one game's scope blocks API, MCP, export and ingestion promptly. Unlink does not mix old account data into new identity. Two users cannot claim the same device code or access one another's data.
11. **Game truth:** raw counters are NOT completed upgrades, current resources are NOT maxima. Exact HP/mana item mapping needs paired pickup evidence and reviewed world records. No all-achievement guarantee from raw account achievements.
12. **Cost:** record per-save/request bytes, idle request rate, DB size, rate limits, retries and monthly estimate at explicit user scale. 'Nearly free' is a target, not an unconditional promise.

## Current external blockers
Owner-approved Render Free + Neon beta is live at https://game-assist.onrender.com; public HTTPS/health/OAuth metadata/download checks passed. No actual Steam Deck hardware test, real phone Steam callback, Claude/ChatGPT connector OAuth acceptance, or controlled before/after HP/mana pickup mapping has passed yet. These gates remain open even when automated tests pass.
