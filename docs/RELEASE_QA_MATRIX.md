# Release QA: список игр, кнопки и границы готовности

Срез 2026-10-31, 19:41 UTC. Отдельный QA report staging; исходный main/package
не изменён. Это не утверждение «всё протестировано» и не разрешение на публикацию.
Пользовательский ориентир: проверять кнопки, ясно показывать список игр, приближать
приложение к готовности и расширять каталог популярных игр. Dark capability-card
reference фактически просмотрен UI-разработчиком; редизайн объединяется в отдельном integrated-release-staging, не опубликован.

## Что проверено и где

| Evidence | Реальный результат | Граница |
|---|---|---|
| LIVE-01, root, 19:24 UTC | На публичном сайте открыты Elden Ring, setup; раскрыты все три setup-details | Только unauthenticated browser; grants/import не выполнялись |
| QA-01, `qa-staging` | 22 новых synthetic flow tests; отдельная полная suite 381 tests / 26.734 s / real PostgreSQL / 0 skips PASS | HTTP/test-client, не настоящий телефон; прежние 4 missing-LICENSE ошибки исправлены в staging inputs, финальный прогон прошёл |
| SAVE-01, security worker | Реальный разрешённый private Belmont файл: local JS/Python safe_summary parity TRUE; bytes/inode/size/mtime неизменны | Только четыре scalar поля; без upload и доказательства pickup semantics; private данные не включены |
| SAVE-02 | 12 `test_belmont` + 5 `test_manual_import_ui` + Node `manual_import.test.js` PASS | Synthetic cases и локальный parser/UI contract |
| SAVE-03, `save-qa-staging/test_projection_matrix.py` | 4 tests / 58 cases PASS: типы/границы четырёх полей, opaque precision, структура/дубли | Browser намеренно консервативнее: отвергает 2**53 там, где Python принимает; это не точное равенство всех допустимых входов |
| CAT-01, `library-catalog-staging` | 5 discovery tests PASS, независимый security review без нового blocker | 17 identity-записей, не 17 декодеров; UI/combined regression ещё отдельно |
| UI-01 | Последний focused UI checkpoint: 42 tests PASS; dark console/original SVG art; реальные screenshots reference просмотрены | После onboarding/steam-library anchor fix идёт re-copy; требуется финальная integrated suite |
| UI-02, root managed internal preview | Desktop 1165 px и resized/zoom effective 388 px: scrollWidth 388, без overflow; synthetic metrics 2×2 и import читаемы; empty-account checkbox checked/unchecked; 17-game details раскрыты | Static preview, не backend POST и не реальный Android; synthetic file chooser прошёл: 4-field preview без autosend; static-server retry failure корректен, Clear удаляет значения/отключает send |
| OWN-01, owned-library staging | 10 focused tests + independent review; owned+catalog+UI full 395 tests / 27.316 s / real PG / 0 skips PASS | До полного QA merge; live provider/key отсутствуют |
| INT-01, root integrated-release-staging | Первый общий прогон 417 tests / 24.965 s / actual PG / 0 skips PASS | До последних onboarding/anchor исправлений и включения дополнительной 4-test/58-case матрицы; исторический checkpoint, superseded INT-03 |
| INT-02 | 424 tests / 30.951 s / real PostgreSQL / 0 skips PASS | Исторический промежуточный run; superseded финальным INT-03 |
| INT-03 FINAL, root `/tmp/ga-integrated-release.log` | **424 tests / 28.394 s / actual PostgreSQL / 0 skips PASS**; compile, JS syntax, Node, catalog/profiles PASS; latest onboarding/retry copy included | Candidate only; main copy/publication pending, live `648c271…` unchanged |

Checkpoint разных деревьев **не складывать** в общее число прошедших тестов.
INT-01 — промежуточная integrated suite; INT-02 также пройден; финальный INT-03 после последних текстовых правок также прошёл. Источник
инвентаризации маршрутов: прочитанные `remote_server/app.py` и `ui.py`; hashes
сохранены отдельно в `OBSERVED_SOURCE_HASHES.json`. Само наличие route не означает pass.

## Матрица видимых controls и routes

Класс: **N** navigation/read-only; **L** только локальное состояние/preview;
**M** изменение приватного состояния; **E** внешняя интеграция; **D** destructive
revoke/logout. «Synthetic» не означает физический click на Android.

| Route / controls | Класс | Подтверждено | Что остаётся |
|---|---|---|---|
| `/`, logo, skip link, Игры/Помощник/Устройство, game tiles, разделы Сводка/Доступ/Помощник, back links | N | QA-01: три публичные игры и внутренние GET targets; LIVE-01: ER/setup | UI-02 подтвердил узкий viewport без overflow; keyboard/full backend clicks/реальный mobile ещё открыты |
| `/login`, «Войти через Steam»; `/steam/callback` | E | QA-01: stale-session local recovery без автоматической мутации | Реальный Android Steam OpenID callback/account link/cancel/retry, не просто Steam website login |
| `/account/games`, checkboxes, review / all-current / confirm / cancel | M/N | QA-01: review/cancel/confirm, без неявных grants; stale catalog 409 | Все controls в интегрированном браузере; real consent |
| `/account/games/add`, AppID/label/submit; discovery add | M | QA-01: custom AppID не создаёт прогресс; CAT-01: discovery не добавляет/выбирает автоматически | UI-02: 17-game details раскрыты; backend add/repeat в final integration ещё проверить |
| `/account/library/permission`, library opt-in/out; `/account/library/refresh`, manual refresh; owned-game add | M/E | OWN-01: реальные routes в test client, disabled-key, consent, empty/private unknown, не вызывает API до явного refresh | Настоящий Steam owned-library запрос с ключом/visibility; не даёт save/achievement grants автоматически |
| `/account/games/permissions`, summary/metadata on/off | M | QA-01: current-game focus, другие игры сохранены; CSRF no mutation | Реальный authenticated browser и UI после редизайна |
| `/account/games/revoke`, details + confirm; `/account/revoke`, global details + confirm | D | QA-01: scoped flow/OAuth-MCP revoke; security boundaries проверены тестами | Полный реальный browser destructive flow на тестовом аккаунте; cancellation/details accessibility |
| `/account/achievements/refresh`, разрешить/отключить achievements | M/E | QA-01: disabled-source 503 и recovery; synthetic refresh/cooldown scenario включён | Server key отсутствует; live Steam availability/privacy не проверены; без ключа не нулевой прогресс |
| `/import`, permission link, file picker, clear, send, back | L/M | SAVE-01/02/03; QA-01: observation API shape не меняется от HTML Accept | Реальный Android file picker, preview→explicit send→MCP, cancellation/offline/expiry/revoke в браузере |
| `/v1/browser/observations` | M | Synthetic API boundaries; сырой save не является допустимым payload | Проверка integrated браузерного wire payload без private утечки |
| `/account/notifications`, opt-in/out; `/account/notifications/read`, read/repeat | M | QA-01: enable/read повтор, возврат в Belmont | Реальные browser controls; это inbox, не push/assistant turn |
| `/logout`, повторный click | D | QA-01: повтор не оставляет сломанную HTML-страницу | Реальный browser session expiry/reload/back |
| `/devices/approve`, code, game, scopes, submit/cancel, success back | M/E | QA-01: invalid retry; cancel→no approval→approve→repeat 400→poll once | Физический Deck pairing; empty-selection UI после исправления |
| `/setup`, back, три details, ZIP/checksum, pair link | N/E | LIVE-01: все три details раскрыты; internal GET targets synthetic | Загрузка/проверка/установка именно на физическом SteamOS; клики не означают установку |
| `/oauth/consent`, allow / deny(back), client callback | M/E | QA-01: ingest→revoke; consent cancel→0 codes/tokens→approve→repeat 400→exactly 1 code/0 tokens | Реальный выбранный мобильный assistant: PKCE/refresh/revoke/native tool use |
| MCP connection address, contribution/external links | N/E | Наличие в UI инвентаризировано | Не все внешние destinations открыты; перед native acceptance проверить актуальную поддержку |

## API / asset inventory — не кнопки, но release gates

| Endpoints | Проверка / статус |
|---|---|
| `/v1/devices/pair/start`, `/poll`, `/v1/device/observations` | Synthetic ingest/revoke coverage; физический watcher/save-change неизвестен |
| `/mcp`, SDK OAuth/discovery endpoints, `/.well-known/oauth-authorization-server` | Synthetic OAuth/MCP flow; это не live client acceptance |
| `/healthz`, `/assets/console.css`, `/assets/import.js`, `/assets/belmont-parser.js` | Перед релизом проверить exact deployed asset/revision; текущий UI staging не опубликован |
| `/downloads/deck-companion.zip`, `.sha256` | GET targets/страница доступны в проверяемых сценариях; ZIP reproducibility/checksum надо привязать к итоговому artifact |

## Найденное и исправленное пока только в staging

- QA: изменение разрешения теряло выбранную игру; inbox действие теряло Belmont
  focus; обычные англоязычные browser errors не давали понятного возврата.
  Исправления покрыты 22 synthetic flow tests, объединяются в release staging, не main.
- UI staging: no-op «Выбрать» заменён clickable checkbox labels с unique ID;
  аккаунт без выбранных игр получает onboarding, не ложный Belmont progress;
  пустая device form имеет disabled submit и ссылку к играм. Последний focused UI
  checkpoint 42 PASS; UI-02 подтвердил внешний вид/узкий viewport/checkbox/details.
  Вопрос первого визита «что делать дальше?» отражён onboarding-подсказками и
  явным разделением списка игр, доступа и доступных источников. Последние правки
  требуют финальной integrated regression, не считают пользовательский путь готовым.
- Browser/Python safe integer различие задокументировано как консервативный отказ,
  а не скрыто под утверждением полной parser parity.

## Каталог популярных игр: данные ≠ поддержка прогресса

CAT-01: 17 identity-записей с официальными Steam references; 3 priority + 14 новых
AppID: `1086940`, `1091500`, `1174180`, `489830`, `377160`, `413150`, `105600`,
`367520`, `1145360`, `264710`, `1771300`, `2246340`, `814380`, `374320`.
Каталог gameplay facts остаётся **0**, declarative profiles **3**, discovery **17**;
это не 17 декодеров. Это curated discovery, не рейтинг популярности и не импорт принадлежащей игроку
библиотеки. Owner catalog остаётся priority 3 + явно добавленные игры; all-current
не включает недобавленные discovery entries. Добавление не выдаёт grants.

Нет новых parser capabilities, schema migration или сетевого запроса при каждом
render. Только Belmont 1.1.3 имеет four-scalar decoder; generic metadata требует
opt-in; achievements — отдельного ключа/consent. Official URLs находятся в staging
`remote_server/README.md`; независимый review подтвердил границу no-auto-grant.

## Своя Steam-библиотека — отдельный согласованный источник

Локально реализованы explicit account `library.read` opt-in и ручной refresh с
необязательным операторским ключом. Retained только AppID/name; request-bound
SteamID и echo при наличии проверяются. Empty/private — unknown, не «ноль игр».
Нет auto-registration/selection/save/achievement consent и выдачи owned list в MCP.
Cache: до 128 rows globally × 256 KiB = до 32 MiB payload, TTL 24 h; до 1000 игр
в bounded response; без artwork/playtimes. Ключ live отсутствует; UI disabled-key
не должен выглядеть как импортированная библиотека. Нет гарантии private-profile
доступа. Каталог 17 игр не заменяет настоящий owned-library ответ.

## Что нельзя закрыть этим отчётом

- Реальный Android Steam OAuth, authenticated import, native assistant flow.
- Steam Deck install/Game Mode/suspend/resume/offline/save-change/uninstall.
- Automatic Steam Cloud API/source/scheduler/delivery: не настроены; OpenID не grant.
- Operator API key/live achievements: отсутствуют; ключ не обходит private profile.
- Elden Ring gameplay decoding, Witcher fixture/build, Belmont pickup mappings:
  unknown; нельзя обещать карту, все предметы/достижения или полноту прохождения.
- Финальный integrated UI/catalog/owned-library/QA regression пройден: INT-03.
  Main copy и публикация ещё впереди; live остаётся `648c271…`.
- Hosted export не реализован и не проверен: `/v1/export` относится к local server,
  не выдавать его за удалённую функцию.
- Synthetic `manual-import.sav` выбран в настоящем Chrome при 388 px: четыре
  значения показаны без autosend. Send на static preview без backend дал корректную
  retry-ошибку; Clear очистил значения и disabled send. Private file не выбирался,
  production не менялся; успешный server ingest проверен только TestClient.
- Новый onboarding screenshot при 388 px просмотрен: CTA, prerequisites/limits
  понятны, overflow отсутствует. После copy-clarity/import-retry wording fix
  итоговая повторная suite прошла: INT-03.

## Условие передачи следующему release review

Собрать конкретные paths/hashes из workers → объединить в разрешённом дереве →
полная реальная disposable-PostgreSQL regression и UI/parser checks → браузерные
screenshots/click-through для всех controls выше на desktop/mobile viewport →
record exact artifact/revision. Внешние gates оставить открытыми, если нет реального
evidence. Не создавать ключи, не менять grants и не публиковать private fixtures
ради заполнения checklist.
