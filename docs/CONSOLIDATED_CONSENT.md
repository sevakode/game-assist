# Consolidated consent backend candidate

Base 88c3fa439e55d8908cd503fc9822a16d0a521388. Local candidate, not production permission approval.
No schema/table migration, new credential, OAuth scope, callback, Cloud integration or fetch.

## Renderer contract (task E)

`consent_body(csrf, req, client_label, scopes, *, review_plan=None)` opts the renderer
into the new flow. Backend passes only this additional keyword; existing optional
`access_context` may keep its default. Legacy renderer signatures remain unchanged
and do not create expanding plans. The backend uses signature detection rather
than silently changing the old form's meaning. UI/CSS are not in this patch.

`review_plan` contains exactly:
- `plan_id`: opaque random 43-character token, bound in server pending state.
- `games`: currently selected games only, sorted by AppID, each with `appid`,
  `trusted_name_or_null` from the public registry, and `categories` from the fixed
  enums `metadata`, `summary`, `achievements`. Summary is Belmont-only; achievements
  require configured capability. Unknown names use AppID, never untrusted labels.
- `oauth_scopes`: original validated requested scopes; no additions.
- `library_source_change`: whether confirming will create account source opt-in.
- `zero_games`: no selected games, no invented selection or progress.

Render games/categories, OAuth scope meaning and library source change BEFORE
submission. Required short disclosure: «Данные будут доступны этому и другим уже
подключённым помощникам в пределах их разрешений». These are account-wide grants,
not a client-isolated data partition. Existing progress clients may subsequently
see newly permitted games. OAuth library.read and account source opt-in remain
separate checks even when one explicit confirmation approves both.

Form POST /oauth/consent must contain exactly csrf, request, plan_id, approve=yes.
No game/scope list or library_read checkbox in this new form. Missing/invalid
approve is never yes. Cancel is navigation away without POST; no grant change.
Old POST csrf/request/[library_read] remains OAuth-only, even if a plan exists.

A grant enables reading permitted existing/incoming data; it does not fetch Steam,
install a companion or supply a save. No future/unselected games are granted.
With zero games, OAuth can still complete for conversation; progress remains empty.
A requested library scope can be approved independently of selected-game count.
If source is not configured, account opt-in is not created; no fake source readiness.

## Storage and atomicity

Plan stored as `_review_plan` and `_review_owner` in existing oauth_pending JSON;
original pending expiry and global 2000-row bound remain. Each render replaces that
request's previous plan_id; an old tab must review again. Owner, exact original
session hash, selected rows, current grants, library consent epoch and capability
flags are captured server-side. Server compares the current snapshot at approval;
clients cannot submit the snapshot. No grant/cache writes or external calls on GET.

New POST rate limit is 10 owner attempts per 600 seconds (10 minutes) via existing Store.limit. In one
Store transaction: recheck exact unexpired session+owner+CSRF, validate pending TTL
and bound plan, compare state/capabilities, reserve bounded cache rows, insert only
shown grants, issue one code with provider.approve(connection=db), invalidate other
plans of this owner. Any quota/code-cap failure rolls all of this back. No nested
Store transaction or lock around network; there is no network in this operation.
Internal review fields are removed before creating authorization code/token data.

## Writer inventory and invalidation

Every listed permission writer invalidates owner plans in its mutation transaction:

| Writer | Covered change |
| --- | --- |
| approve_device | Selection and requested save grants |
| choose_games | Selection changes and metadata/summary permissions |
| game_permission | Scope grant/revoke and achievement consent epoch |
| library_permission | Source enable/disable/epoch, including enable_and_refresh |
| Store.revoke_scope | Central per-scope revocation; covers callers |
| Store.revoke_game / revoke_selected_game | Through revoke_scope before deselection |
| account revoke | All source/game grants before global deletion |
| approve_plan | Invalidates other plans while consuming own pending once |

Invalidation removes review fields, not the original OAuth request; stale new POST
returns 409. It is conservative on repeated identical writer requests. Thus
revoke→regrant ABA cannot revive an old review. SQL filtering is owner-bound; a
narrow PostgreSQL dialect conversion covers the new JSON field predicate.

add_game changes registrations/user labels only: it cannot select/grant, and the
review deliberately uses public registry identity rather than those labels, so
it does not invalidate this plan. Snapshot reads only produce selected public
rows. Cache refresh/expiry/ingest changes payloads, not permission, and do not
invalidate. Migration initialization is outside request permission writes; newly
changed selections are caught by snapshot comparison. Logout/Steam session rotation
is caught by final exact-session recheck; a newer login cannot rescue the plan.
Changing public names/capability configuration is caught by public snapshot comparison.

## Tests and integration boundary

Synthetic renderer fixture exercises the full GET/POST/DCR/PKCE path but is not a
replacement for E's disclosure/UI test. Before integration, E must test the exact
rendered games/categories, explicit approve field, optional absent plan, cancellation,
and the required account-wide visibility disclosure. No UI field contract is
silently inferred from the old renderer.

Backend tests cover legacy no expansion, zero games, scope/source separation,
old-client account-grant visibility, no GET grants, cancellation/replay, ABA,
writer invalidation including pairing, cross-owner/session denial, capability
change, expired pending, quota and code-cap rollback, original session recheck,
concurrent approval and concurrent revoke. PostgreSQL subclass uses only the
existing explicitly supplied disposable loopback DSN factory, never production.
No new service was created; disclose its skipped status if DSN is unavailable.
