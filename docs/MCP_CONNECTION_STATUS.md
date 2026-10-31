# Agent connection diagnostics (contract version 1)

`get_connection_status()` is an additional read-only MCP tool. Existing
`get_progress` and `suggest_next_step` responses are unchanged. All three require
the existing `progress.read` bearer and bind to its subject; the new tool has no
arguments. It returns availability and user actions, not a second progress payload.

Its only account-data input is `Store.projection(subject, cleanup_expired=False)`.
That option computes cache expiry without performing the usual lazy cache cleanup.
The diagnostic does not query library/device/client records, fetch Steam data,
grant permissions, upload, refresh a source, or mutate account data. Standard
authentication and request boundary checks still apply.

Only games already visible in the permitted projection appear. An empty `games`
list cannot distinguish no game selection from no permission: tell the user to
review **both** in `/games`. Do not infer their owned or selected games. Revocation
immediately removes the same data from diagnostics as from `get_progress`.

## Returned information

- `connection: authenticated` establishes only this successful MCP request.
- `links` contains only configured-origin `/games`, `/import`, `/setup`, and
  `/connect/claude`. Links never come from headers, labels or account input.
- `capabilities` is public service configuration: Steam Cloud is
  `source_not_connected`, achievements are `operator_source_not_configured` or
  `available_requires_permission`, background push is `not_supported`, and device
  connection is always `unknown`. Available achievements do not establish account
  permission, visibility, or a successful Steam API request. Do not ask the player
  for an API key. Summary coverage is four raw fields; gameplay semantics unknown.
- Each visible game's `snapshots` separately reports permitted summary/metadata
  source, server receipt timestamp and age in whole seconds. It never reports
  private paths, payload values, achievement names/IDs or Steam/device/client IDs.
- `observation_time: unknown` is the game observation/save time, not server receipt
  time. A receipt at least `receipt_review_after_seconds` (86400) old triggers a
  review suggestion, **not** an expiry, stale-game-state conclusion, or offline
  diagnosis. A missing, invalid or future receipt has unknown timestamp/age.
- `achievements` exists only if the projection already permits it. It reports the
  cached status and receipt, never cached items; `expired` remains unknown progress.
  Allowed statuses are `ok`, `expired`, `not_requested`, `not_configured`,
  `unavailable`, `private`, `rate_limited`, or fallback `unknown`.

## Fixed reason and action vocabulary

| Reason | Meaning / action |
|---|---|
| `no_authorized_games_visible` | Selection or permission is missing; which is unknown. Review both. |
| `no_visible_save_snapshot` | No permitted save snapshot is visible; missing permission, missing import and device connection cannot be distinguished. |
| `summary_snapshot_available` | A permitted reported summary exists; call `get_progress`. It is not independently verified gameplay. |
| `summary_fields_unknown` | At least one scalar is missing/unknown. Never replace it with zero. |
| `summary_decoder_unavailable` | This visible game's summary decoder is unsupported. Companion metadata cannot establish gameplay. |
| `metadata_is_not_game_progress` | A metadata snapshot exists, but no summary is visible. |
| `receipt_age_known` | Receipt age is calculable; no claim about the game's current state. |
| `receipt_older_than_review_threshold` | Receipt age meets the disclosed 24-hour review threshold. |
| `receipt_time_unknown` | Receipt age cannot safely be calculated. |

| Action | Agent explanation / destination |
|---|---|
| `review_game_selection_and_permissions` | Ask user to review selected games and explicit data consent at `links.games`. |
| `review_manual_import` | Ask user to review scope and compatible Belmont 1.1.3 import at `links.import`; they choose, preview and confirm. This action does not establish an existing summary grant. |
| `review_optional_companion` | Optional device setup at `links.setup`; metadata-only games remain metadata-only. Do not infer pairing or online status. |
| `read_permitted_progress` | Call `get_progress` under the same authorization. |
| `review_snapshot_receipt` | Explain the receipt time/unknown age; ask whether the user wants to supply a newer permitted snapshot. Never automatically send one. |
| `review_achievement_source` | Explain source status; user reviews permission/source at `links.games`. No automatic API refresh or new credential. |

`links.claude` is connection help, not an instruction to register another client.
If authentication itself fails, this tool cannot run; use the ordinary client
authorization UI. These diagnostics do not prove a real Claude/Steam connection.

## Proposed starter-prompt addition (not applied to UI)

> Сначала вызови get_connection_status, затем get_progress, если виден разрешённый
> снимок. Объясни коротко причину отсутствия данных и один следующий шаг по
> возвращённым reason/action и доверенной ссылке. Если игры не видны, предложи
> проверить и выбор игры, и разрешения — не угадывай, что именно отсутствует.
> Давность получения сервером не называй временем сейва или offline-статусом.
> Неизвестные поля не заменяй нулём. Не обещай Steam Cloud, фоновые push или полный
> разбор игры. Не давай согласие и не отправляй данные вместо пользователя.

## Verification

`python -m unittest discover -s tests -p 'test_remote_connection_status.py' -v`
uses synthetic identities, local SQLite, mocked Steam OpenID and the actual MCP
HTTP transport. Coverage: before data; selected but unpermitted; explicit import;
scoped/full revoke; subject isolation; existing scope enforcement; unsupported
decoder/metadata; absent operator capability; unknown/older receipt; unknown
scalar; no source/library access; expired-cache read without mutation.

`PostgresConnectionStatusTests` inherits the six service contracts when an explicit
disposable loopback `GA_TEST_POSTGRES_URL` is supplied. Without it they are skipped,
not evidence of real PostgreSQL. No external client/Steam/production calls occur.

## Synthetic optional-library consent acceptance

Run `python -m unittest discover -s tests -p 'test_mcp_consent_acceptance.py' -v`.
This separate scenario follows local HTTP endpoints from a new DCR registration,
through the browser's Steam identity handoff (mocked), into optional consent:

1. New registration without scope permits both client capabilities, but unchecked
   library consent issues only `progress.read`. The acceptance parser follows
   browser form behavior: unchecked checkboxes are omitted from submission.
2. `get_progress` works with no permitted games; `get_library` stays closed.
   Refresh cannot add library, and ordinary rotation preserves progress-only scope.
3. A new authorization for the same capable client explicitly checks library.
   The resulting dual-scope token still cannot read the source without independent
   account opt-in. Opt-in alone does not fetch data; explicit website refresh does.
4. Only cached AppID/name pairs become visible. The old progress-only family stays
   restricted; no game registration, selection or per-game grant is created.
   Progress and connection diagnostics still show no permitted game snapshots.
5. Narrowing the dual-scope refresh family to progress works, and re-expansion is
   refused. Callback state/issuer and the S256 code exchange are checked throughout.

The same acceptance is inherited by a PostgreSQL test in that file. Without
`GA_TEST_POSTGRES_URL`, it is explicitly skipped. SQLite is real; Steam/library
responses and all identities are synthetic. No real Claude DCR behavior, live
Steam source access, or production setup is established by these tests. A capable
existing client can repeat human consent; an old progress-only registration still
needs fresh DCR. Client UI behavior after optional-scope refusal remains a live gate.
