# Game Assist: проверяемый roadmap

## Текущая интеграция UI / каталог / QA — 19:41 UTC

Этот раздел находится только в qa-report-staging; основной package не изменён и
новый набор не опубликован. Нижележащие release checkpoints исторические.

- Первый root integrated run: **417 tests / 24.965 s / actual PostgreSQL / 0 skips,
  PASS**. После последних onboarding/steam-library anchor правок (42 focused UI
  tests PASS) и включения отдельной 4-test/58-case матрицы combined checkpoint **424 tests / 30.951 s / real PG / 0 skips PASS**. Финальный run после
  copy-clarity/import-retry wording правок: **424 tests / 28.394 s / actual PostgreSQL /
  0 skips PASS**; compile, JS syntax, Node, catalog/profiles checks прошли.
- 17-game curated discovery + отдельный account-owned library источник объединены
  в release staging. Декодеров не прибавилось; список игр не означает владение.
  `library.read` explicit opt-in, manual refresh; ключ live отсутствует. Empty/private
  — unknown. Нет auto-registration/selection/save/achievement consent или MCP owned list.
- Managed static browser preview проверен: desktop 1165 px, effective 388 px без
  overflow, metrics 2×2/import читаемы, checkbox toggle и 17-game details работают.
  Это не backend POST, реальный Android OAuth или authenticated import. Synthetic
  file chooser в Chrome выполнен: четыре поля preview без autosend, ожидаемая
  retry-ошибка на static preview без backend, Clear очистил поля/disabled send.
  Private file не выбирался, production не менялся; успешный ingest — TestClient only.
- Первый визит получает более явный onboarding: выбрать игру, отдельно разрешить
  источник, затем использовать доступную функцию; inactive capability не выдаётся
  за готовую. Latest integrated regression и полный backend/browser click-through
  не заменены static preview; итоговая regression уже прошла, release ещё впереди. Полная матрица: [RELEASE_QA_MATRIX.md](RELEASE_QA_MATRIX.md).
- Далее: review exact artifact по прошедшей final regression → разрешённый выпуск/CI/deploy →
  smoke. Реальные phone OAuth/Deck/Cloud/API key/семантика fixtures остаются отдельными
  blockers. Hosted export отсутствует; local `/v1/export` не его замена.


Обновлено 2026-10-31, 18:43 UTC. Roadmap продолжается после публикаций: релиз — контрольная
точка, не завершение разработки. Здесь нет календарных обещаний, процентов
покрытия или обещания одобрения Valve. Статусы меняются только по свидетельствам.

## Цель и границы

**Целевой базовый режим — без установки:** разрешённый источник облачного сейва
→ подтверждённое изменение после синхронизации → безопасная проекция → отдельно
разрешённая доставка/запуск облачного помощника. Источник, расписание и способность
канала инициировать новый диалог пока не подтверждены. Steam OpenID — только
идентификация, не доступ к сейвам. Более быстрый PC/Steam Deck watcher — отдельная
необязательная возможность, а не подмена базового режима.

Ближайший полезный промежуточный результат — **ручной импорт без установки**:
пользователь выбирает уже имеющийся файл в браузере, локально видит разрешённые
поля и отдельно разрешает отправку только проекции. Это не автоматический Steam
Cloud, не постоянный доступ к диску и не финальный бесшовный UX.

Разрешение игры, доступ к источнику, поддержка формата, игровая семантика и
доставка уведомления — пять разных проверок. Ни одна не заменяет остальные.

## Отправная точка: что можно утверждать

| Область | Свидетельство / состояние | Чего это не доказывает |
|---|---|---|
| Публичная beta | Manual-import release `648c2719368c57da23566497e1a2358f2d05462f` LIVE на Render в 18:34:13 UTC; public assets/health/auth gate проверены | Реальный phone/authenticated import, OAuth или Deck acceptance пройден |
| Universal regression | Подтверждён checkpoint 297 тестов, включая настоящий одноразовый PostgreSQL; CI выпуска указан ниже | Все 297 тестов — PostgreSQL-тесты; реальные Steam/Cloud/мобильные интеграции проверены |
| Ручной browser import | IMP-01/02/03 опубликованы; 314-test checkpoint, security review, synthetic cancel/parity и локальное JS/Python parity на реальном разрешённом приватном файле проверены | Реальный authenticated browser/phone acceptance IMP-04 пройден; scalar parity доказывает pickup mapping |
| BEL-01 / текущий local workspace | Protocol/review и 19 тестов объединены локально (5 файлов); общая regression 333 теста, 20.977 s, real PostgreSQL, 0 skips, PASS | BEL-01 опубликован или семантика pickup установлена |
| ACH-01 | 12 файлов после review/cost guards объединены локально с проверкой baseline SHA; staging regression 359 тестов, 23.500 s, real PostgreSQL, 0 skips, PASS; integrated suite 359 тестов, 24.510 s, actual PostgreSQL, 0 skips, PASS | Код опубликован или live Steam API acceptance пройден; ключ создан |
| Универсальный каталог и права | Канонический AppID 1…2147483647, до 100 игр; priority presets 4231820 / 1245620 / 292030; review точного списка и scopes, all-current без будущих игр | Импорт всей библиотеки Steam или парсер любой игры |
| Generic device metadata | Для выбранного AppID: только размер и время изменения с текущим разрешением | Содержимое, прогресс, завершённая Cloud-синхронизация |
| Belmont 4231820 | JSON save-format 1.1.3, четыре разрешённых scalar-поля; контролируемая структурная проекция | Точная сборка игры, максимум HP/маны, число улучшений, pickup IDs или полное прохождение |
| Elden Ring 1245620 | Приватная разрешённая fixture; ограниченная read-only проверка заголовка BND4 | Полная валидность контейнера, версия игры, слоты, inventory/events или семантика |
| Witcher 3 292030 | Проверенная Cloud-страница в тот момент не содержала доступного файла | Нет игры/локальных сейвов/прогресса; разрешение искать другие аккаунты/AppID |
| Community profiles | Декларативные схемы/реестр/review; код не исполняется из профиля | Автоматическая установка парсеров или verified gameplay по одному флагу approved |
| Уведомления | Opt-in inbox сайта на ограниченных device-изменениях | Push, новый ход ChatGPT/Claude, Cloud-source или надёжный scheduler |
| Достижения / мир | Live API ключ не настроен; реальный каталог предметов пуст | Полный item mapping, все достижения или гарантия ничего не пропустить |

[CI manual-import release](https://github.com/sevakode/game-assist/actions/runs/41229868518)
относится к `648c2719368c57da23566497e1a2358f2d05462f`, Render deploy
`dep-dbj38t5g1s2s73elkt7g`, LIVE 18:34:13 UTC. Предыдущий
[CI universal release](https://github.com/sevakode/game-assist/actions/runs/41228842316)
и 297-test checkpoint относятся к `33badaca909f539f63d38114775ff40cf4a22152`.
333-test checkpoint относится к последующей локальной работе BEL-01, не к этому
публичному релизу. ACH-01 теперь объединён локально; его итоговая integrated regression:
**359 тестов, 24.510 s, actual PostgreSQL, 0 skips, PASS**. Compile, JS syntax,
Node parity/UI, catalog/profiles также прошли. Staging checkpoint сохранён отдельно. Эти правки roadmap также
локальные до следующего commit/release. Старые 197-test записи исторические.

## P0 — ручной безопасный импорт без локальной установки

**Статус 18:43 UTC:** IMP-01/02/03 опубликованы в `648c271…`. Подтверждены
314-test checkpoint, security review, synthetic cancel/parity tests и локальное
JS/Python parity на реальном разрешённом приватном файле без публикации его данных.
Public assets/health/auth gate проверены. Реальный authenticated browser/phone
acceptance IMP-04 остаётся открытым. Чекбоксы ниже означают всю приёмку, не только
наличие кода; структурное parity не устанавливает игровой смысл счётчиков.

**Результат:** получить разрешённую сводку выбранного сейва без установки Python
или компаньона; сырые байты остаются в браузере.

- [ ] **IMP-01 — локальный preview.** Явный file picker, только Belmont JSON 1.1.3;
  ограничение размера до чтения, строгая схема/типы/диапазоны, unknown при ошибке
  или неизвестной версии. Отображать только четыре поля и точность их смысла.
  Никаких имён файлов, путей, raw JSON, entity/account IDs в DOM, логах или URL.
- [ ] **IMP-02 — отдельная отправка.** До реализации утвердить контракт browser
  source и точное применение `saves.summary`: существующий device bearer не
  переиспользовать как browser credential. Показывать игру, поля, назначение,
  источник «ручной импорт» и отдельное подтверждение отправки. Не выдавать право
  по одному выбору файла и не отправлять автоматически после выбора.
- [ ] **IMP-03 — серверная граница.** Session+CSRF+same-origin, текущий per-game
  grant, strict allowlist payload, tenant isolation, rate/body limits, дедупликация,
  отзыв между preview и send. Проверить миграцию/удаление/export/MCP для нового
  source. Запретить raw/multipart/base64 file upload и лишние поля.
- [ ] **IMP-04 — реальные UX-проверки.** Cancel, повторный выбор, ошибка формата,
  offline/retry, истёкшая сессия, отозванное право, неизвестная версия, мобильный
  file picker. Показать server receipt отдельно от неизвестного времени игры.

**Приёмка/свидетельство:** synthetic parity corpus browser/Python для четырёх
полей; network assertion «до подтверждения ничего не отправлено», после — только
разрешённая проекция; негативные API/CSRF/tenant/revoke тесты; браузерная проверка
доступности и preview. Оригинал не меняется; private save не попадает в тестовые
артефакты. Клиентские поля — данные пользователя, не доказательство честного
парсинга и не разрешение на verified pickup evidence.

**Зависимости:** реализация, regression, security review и выпуск IMP-01/02/03
выполнены; остаётся реальный authenticated пользовательский flow IMP-04.
Локальное parity реального файла не заменяет его отправку через разрешённый UI.
**Готово:** preview + подтверждённая проекция доступны и протестированы; UI явно
называет режим ручным. Автоматический Cloud gate остаётся открытым.

## P1 — реальные факты Belmont и минимальная база знаний

**Локальный checkpoint:** BEL-01 protocol/review и 19 тестов объединены (5 файлов);
полная suite — **333 теста за 20.977 s, real PostgreSQL, 0 skips, PASS**. Ещё не
опубликовано. Подготовленный протокол не является полученной controlled pair или
доказанной семантикой: pickup mapping остаётся unknown.

- [ ] **BEL-01 — протокол наблюдения.** Зафиксировать точную сборку/platform,
  save-format, слот и независимое игровое наблюдение. Получить с согласием пару
  копий до/после одного HP или mana pickup; отдельно отличить расход ресурса,
  fragment counter и изменение максимума. Без подмены агрегата per-item ID.
- [ ] **BEL-02 — один проверенный mapping.** Ограниченный read-only diff,
  неизменные оригиналы, воспроизводимый обезличенный evidence report,
  независимый review. Не публиковать приватную fixture или entity IDs игрока.
- [ ] **BEL-03 — одна правомерная запись knowledge.** Собственное/разрешённое
  описание, provenance, отдельно согласованная лицензия данных и проверенные
  game-build/parser mapping. Раздельно проверить место и условие safe hint.
- [ ] **BEL-04 — осторожная выдача.** Trusted adapter → три состояния
  collected/not_collected/unknown; отсутствие флага не false. Сначала один
  подтверждённый факт, затем расширение корпуса, не обещание «все улучшения».

**Приёмка/свидетельство:** контролируемая пара + in-game ground truth + reviewer;
negative cases для другого build/слота/отсутствующего флага; spoiler tests до MCP.
«Не забудь осмотреться» допустимо только при доказанном trigger, не при unknown.
**Заблокировано:** точный build, контролируемые пары/семантика и права на реальные
записи пока не установлены. **Сделано локально:** протокол, synthetic tests и
review; **дальше:** выпуск и применение только к разрешённым controlled fixtures. **Готово:** ровно заявленный mapping
подтверждён; остальные категории всё ещё unknown.

## P2 — расширение парсеров без расширения доверия

- [ ] **ER-01 — решение о зависимости.** Проверить exact revision, лицензии кода
  и данных, зависимости, отсутствие write/repair пути. Restricted-source manager
  не vendor/port/package без письменного разрешения. До установки/исполнения
  стороннего кода — review зависимости и требуемого разрешения.
- [ ] **ER-02 — отключённый read-only spike.** После review: bounded bytes-only
  worker без сети/записи в каталог игры; начать с структуры, не gameplay claims.
  Приватная fixture уже есть, но не публикуется и не включается в CI.
- [ ] **ER-03 — версия и семантика.** Получить game build/platform/DLC/mod context
  и согласованные before/after ground-truth пары. Ошибка/пустой slot не означает
  «не получено». Включать только отдельно доказанные факты.
- [ ] **W3-01 — получить fixture.** Запросить выбранную владельцем локальную копию
  и build/platform контекст; пустой Cloud listing не позволяет заключать прогресс.
- [ ] **W3-02 — отдельный review формата.** Legacy unpacker/decompression не
  доказывает поддержку текущей сборки или quest/inventory semantics. Затем те же
  private-fixture, read-only, resource-limit и spoiler gates, что для ER.

**Приёмка/свидетельство:** критерии [PARSER_COVERAGE](PARSER_COVERAGE.md), pinned
provenance, unchanged originals, invalid/unsupported/unknown/false раздельно,
synthetic public corpus и точная матрица поддерживаемых фактов/версий.
**Заблокировано:** ER — dependency review и build/semantic evidence; W3 — fixture
и build. **Готово:** ограниченный adapter с доказанным coverage, а не «игра целиком».
Community profiles остаются только декларативными; ни PR, ни `approved` не
разрешает автоматически исполнять код или расширять права пользователя.

## P3 — достижения как отдельный источник

**ACH-01 реализован и объединён локально:** 12 файлов после review/cost guards,
с проверкой всех baseline SHA. Staging suite: **359 тестов за 23.500 s, real
PostgreSQL, 0 skips, PASS**; итоговая integrated suite 359 тестов, 24.510 s, actual PostgreSQL, 0 skips, PASS. Ещё не
опубликовано: live остаётся `648c271…`. `SGC_STEAM_API_KEY` необязателен и на live
отсутствует; никаких credentials не создано, реальных API запросов не проверено.

Локальный контракт: `achievements.read` default-off отдельно по каждой игре;
явный ручной request-driven refresh не чаще 15 минут, только unlocked cache с
24-часовым expiry. Лимиты: 20 игр на owner, 512 cache entries глобально, 128 KiB
на entry, суммарно до 64 MiB cache payload (не обещание общего RSS/DB footprint).
Revoke и in-flight consent epochs защищают от восстановления отозванного доступа.
Locked имена/описания/иконки/ID и скрытые знаменатели не выдаются. Это не scheduler.

В том же локальном наборе HTML `GET /import` безопасно возвращает после Steam
login; API POST без сессии по-прежнему отвечает 401. Phone flow ещё не принят.

- [ ] **ACH-01:** bounded client/schema cache и mock tests: privacy/403, timeout,
  rate limit, неполный ответ, отсутствующая игра, locale и запрет секретов в логах.
- [ ] **ACH-02:** после операторской настройки server-side ключа и отдельного
  per-game `achievements.read` consent проверить разрешённый live запрос.
- [ ] **ACH-03:** выдать только допустимые unlocked facts с provenance/временем;
  locked имена/описания/иконки/ID/скрытые знаменатели не передавать модели.

**Приёмка:** live evidence с разрешённым профилем плюс revoke/privacy/tenant tests;
ошибка даёт unavailable/unknown, не ноль достижений. Ключ не вводит игрок и не
передаёт в чат. **Заблокировано:** оператор должен безопасно настроить server-side ключ, затем
нужны согласие и реальная проверка доступности разрешённого профиля. Ключ не
гарантирует доступ к private profile и не обходит Steam privacy.
**Готово:** проверенный узкий источник account facts; не per-slot completion.

## P4 — настоящий no-install Cloud и помощник после синхронизации

Эта линия — конечная продуктовая цель, а не обещанная возможность ручного импорта.
Проверку допустимости источника вести параллельно независимым локальным задачам.

- [ ] **CLD-01 — источник:** документировать разрешённый механизм и AppID scope;
  Valve access не гарантирован. Ни cookie extraction, ни чужая сессия, ни OpenID
  не заменяют его. Не строить неразрешённый scraping workaround.
- [ ] **CLD-02 — versioned observations:** baseline/change/duplicate/partial sync/
  rollback/lost permission/error; не считать изменение metadata доказательством
  завершённой синхронизации всех файлов игры. Сначала synthetic контракт.
- [ ] **CLD-03 — расписание:** разрешённый scheduler с backoff/quotas, bounded
  retries, free-host sleep и измеренной задержкой. Не прятать платный worker.
- [ ] **CLD-04 — доставка:** отдельный opt-in, проверенный recipient/channel,
  quiet hours, neutral templates, дедупликация и revoke-before-send. Отдельно
  доказать доставку на телефон и отдельно — возможность запустить assistant turn.

**Приёмка:** реальные source version → job → safe projection → разрешённая
доставка, включая отзыв/ошибки; запись задержек и стоимости без private payload.
**Заблокировано:** разрешённый источник, scheduler и delivery/assistant capability
не подтверждены. **Готово:** пункты 13–15 END_TO_END_ACCEPTANCE пройдены; inbox,
моки, device source или ручная загрузка не закрывают эту проверку.

## P5 — надёжность, экономика и optional Deck

- [ ] **OPS-01:** end-to-end phone Steam callback и выбранный MCP клиент:
  OAuth/refresh/revoke, tenant isolation, реальные мобильные ограничения.
- [ ] **OPS-02:** retention/account deletion, backup/restore/migration rehearsal,
  cold starts, bounded resource use, независимый security review. Измерять bytes,
  DB growth, idle requests/retries и стоимость при явно заданном числе пользователей.
- [ ] **DECK-01:** физический SteamOS/Game Mode, suspend/resume/offline/reboot,
  stable-copy/debounce, uninstall и credential lifecycle; не обещать realtime.
- [ ] **COM-01:** маленькие declarative profile PR, provenance/license/evidence
  review; отдельные schema, spoiler и parser gates. Автоисполнение вклада запрещено.

**Приёмка:** воспроизводимые результаты, реальные устройства/внешние системы там,
где этого требует сценарий; измеренные квоты/задержки, не «бесплатно навсегда».
**Заблокировано:** реальные device/client проверки и дополнительные доступы — по
их необходимости; synthetic и локальные эксплуатационные тесты доступны сейчас.

## Цикл каждого релиза и правила остановки

1. Выбрать первый незаблокированный маленький пункт; записать критерий готовности.
2. Реализовать с synthetic fixtures, прогнать regression, UI checks и настоящий
   одноразовый PostgreSQL. Никогда не направлять destructive tests в production.
3. Проверить diff/артефакт на секреты, сейвы, личные пути и лишние данные; привязать
   результаты к точному revision. Отдельно записать skipped и непроверенные gates.
4. В рамках актуальной авторизации выпуска проверить commit → CI → deploy revision
   → health/metadata/ZIP и нужный безопасный smoke test. При сбое диагностировать,
   исправить/откатить в разрешённом объёме; не объявлять выпуск завершённым раньше.
5. Обновить evidence/status, затем брать следующий незаблокированный пункт.
   Публикация не закрывает весь roadmap; зависимость от private evidence не мешает
   работать над preview, контрактами, тестами и документацией.

**Stop flags:** новый credential/account/расширение прав; новая стоимость/provider;
публикация private saves/идентификаторов; неизвестная лицензия; неподтверждённая
семантика; побочный write/repair оригинала. Остановить только зависимую часть,
записать точное действие/цель/причину/нужное разрешение и продолжить независимую.
Общее разрешение выпускать код не разрешает публиковать личные данные, получать
секреты или покупать инфраструктуру. Эта roadmap-задача сама ничего не публикует.

## Следующий исполнимый срез

**Публичный manual import уже выпущен. IMP-04 остаётся следующим внешним gate:**
реальный flow на телефоне с явным выбором файла, preview, подтверждением отправки,
проверкой только разрешённых полей и отзыва доступа. Не выдавать private-file
локальное parity или public auth-gate smoke за authenticated приёмку.

**Независимая работа без ключей/новой авторизации — завершить combined release:**
привязать прошедшую integrated regression ACH-01/BEL-01 и login-return fix
к revision/artifact, проверить CI/deploy и безопасные disabled-key,
auth-gate/public-assets smoke tests. Не заменять итоговую suite staging результатом.
Definition of done: точная deployed revision и checks записаны; без ключа источник
явно unavailable, не нулевой прогресс; private данные/секреты не опубликованы.
Live ACH-02 останется открытым до безопасной операторской настройки ключа и
реального consented запроса к доступному профилю; key не обходит privacy.

BEL-01 protocol/review уже готовы локально; включить их в следующий проверенный
релиз отдельно от неизвестной игровой семантики. Далее controlled before/after
и независимый in-game ground truth, когда они доступны с разрешением владельца.

## Связанные документы

[Продукт](PRODUCT.md) · [Требования](REQUIREMENTS.md) · [Backlog](BACKLOG.md) ·
[Покрытие парсеров](PARSER_COVERAGE.md) · [Community data](COMMUNITY_DATA.md) ·
[Cloud и уведомления](CLOUD_SYNC_NOTIFICATIONS.md) ·
[Приёмка](END_TO_END_ACCEPTANCE.md) · [Remote server](../remote_server/README.md).
Исторические permission/deployment формулировки в этих документах не заменяют
последнюю явную авторизацию; новые возможности не считаются deployed по наличию кода.
