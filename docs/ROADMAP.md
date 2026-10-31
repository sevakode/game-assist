# Game Assist: проверяемый roadmap

Обновлено 2026-10-31, 23:48 UTC. Релиз — контрольная точка, не завершение
разработки. Сроки, проценты покрытия и одобрение Valve не обещаются.

## Текущее состояние

Публичный baseline — `ef1…`, LIVE после **runtime-only rebuild на Python 3.12.16**,
Render deploy `dep-dbj7p6mtlv9c73cf7tmg`. Этот rebuild не публиковал новые функции.
Wave 2 ниже — **локальный неопубликованный candidate**.

| Срез | Реализовано локально | Что остаётся непроверенным |
|---|---|---|
| Private capture/compare | Локальный read-only сбор и сравнение копий | Реальные контролируемые пары и игровая семантика; только прежние четыре Belmont raw fields |
| Deck recovery/compat | Атомарное восстановление и compatibility workflow | Физический Deck, Game Mode, suspend/offline/reboot |
| OAuth/MCP | Optional `library.read` default OFF; `get_library` читает только разрешённый cache; `connection_status` | Реальный client acceptance, live Steam API, согласие пользователя на ключ |
| Discovery/privacy | `/connect`, robots/sitemap/llms и private noindex | Это не готовая privacy policy и не доказательство client compatibility; noindex не access control |

Итоговый integration checkpoint: **600 тестов за 11.296 s, 499 PASS,
101 PostgreSQL skips, OK**. Включены `test_mcp_consent_acceptance.py` и
`test_deck_acceptance.py`; helper MODULES включает Deck acceptance. Отдельная
stdlib suite: **116 тестов за 1.574 s, 0 skips, PASS**. Fixture исправлена. Actual PostgreSQL не запускался; skips не
считаются пройденной PG-проверкой. Capture/compare: 22 теста независимо PASS
при umask 0022 и 0077.
Независимые native reviews: **26 MCP** и **113 stdlib Deck** — PASS/без findings;
их не складывают с общим числом. JS/manual-import/compile/catalog/profile checks
прошли. Guide records **0**, profiles **3**; semantic coverage не расширено.

**Исторические checkpoints:** предыдущая локальная suite 476 тестов включала
83 PG skips (393 executed PASS), а более ранний UI candidate — 424 actual-PG tests
без skips. Ни один не подтверждает нынешний candidate. Static UI/browser evidence
и его ограничения: [RELEASE_QA_MATRIX](RELEASE_QA_MATRIX.md).

## Продуктовая цель и неизменные границы

Базовая цель — **без установки**: разрешённый cloud source → подтверждённое
изменение → безопасная проекция → отдельно разрешённая доставка/помощник.
Источник, scheduler и native assistant turn ещё не подтверждены. Steam OpenID
не даёт Cloud-доступа. Ручной browser import — полезный fallback, не автоматический
Cloud. Более быстрый PC/Deck watcher — необязательный отдельный путь.

Регистрация AppID, разрешение источника, распознавание формата, игровая семантика
и доставка — разные gates. Каталог discovery содержит 17 игр, declarative profiles
3, реальных knowledge facts 0: это не 17 парсеров и не owned Steam library.
AppID до 2147483647, owner catalog до 100; all-current не включает будущие игры.
Добавление/выбор не выдаёт grants. Community profile не исполняет код.

Belmont JSON 1.1.3: current health/mana — не максимумы, fragment counters — не
доказанные улучшения. Ни metadata, ни отсутствие достижения не доказывают прогресс.
ER signature не подтверждает версию, слоты или inventory; пустая W3 Cloud-таблица
не доказывает отсутствие сейвов/прогресса. Unknown не превращается в false.

## Ближайшая очередь: результат, evidence, blockers

1. **REL — проверить Wave 2 на PostgreSQL и выпустить.** Fixture fix и полная
   локальная regression пройдены; далее actual disposable PostgreSQL CI без
   подмены skips успехом. Проверить
   текущий ZIP, exact revision и review; старый ZIP hash не относится к новому пакету.
   После разрешённой публикации проверить CI/deploy revision, health, metadata,
   download checksum и безопасные auth gates. **Готово:** свидетельства относятся
   к одному артефакту, нет regression/security blocker. Сейчас actual-PG CI и выпуск
   pending; приватные данные в package не включать.
2. **IMP-04 / OAuth — настоящий пользовательский путь.** Steam sign-in → выбранная
   игра/scopes → browser file preview → отдельная projection-only отправка →
   разрешённый MCP клиент; cancel/retry/expiry/revoke. **Evidence:** реальный телефон
   и выбранный клиент, без секретов в отчёте. Compatibility docs содержат 7 client
   recipes; ChatGPT web — следующий кандидат, не уже проверенное подключение. **Blocker:** live Steam/Claude/Android
   acceptance не выполнен; callback allowlist не расширять наугад. Static preview,
   synthetic HTTP и RFC 9207 тесты сами по себе этот gate не закрывают.
3. **BEL — один доказанный mapping.** Применить inspector/protocol к разрешённой
   controlled before/after паре одного действия на точной сборке, с независимым
   in-game ground truth. **Готово:** неизменные оригиналы, обезличенный отчёт,
   reviewer и synthetic negative cases; агрегат не переименован в per-item fact.
   **Blocker:** контролируемые private fixtures/семантика ещё не проверены.
   До них можно улучшать bounded parsing/error tests без выдуманных игровых фактов.
4. **DECK — аппаратная приёмка doctor/recovery.** Реальный SteamOS, user-home-only
   установка, Game Mode, suspend/resume/offline/reboot, credential expiry/revoke,
   uninstall без изменения сейвов. **Готово:** наблюдаемые результаты и сохранность
   оригиналов. **Blocker:** физический Deck не проверен; ZIP/tests не заменяют его.
5. **ER/W3 — отдельное исследование.** Pin лицензий/зависимостей, build/platform/DLC
   и fixtures, bounded read-only worker, затем семантические before/after tests.
   **Готово:** точная матрица доказанных фактов/версий. ER остаётся signature-only
   unsupported, W3 unsupported; не включать repair/write-back или community code.
6. **ACH/LIB — live Steam источники.** При безопасно настроенном оператором ключе
   проверить отдельные opt-in и реальную доступность профиля. Default-off,
   request-driven refresh, bounded cache, revoke/in-flight checks сохраняются.
   Optional OAuth `library.read` не включается автоматически; `get_library` не
   запускает скрытый Steam fetch и требует текущего разрешения.
   **Готово:** permitted unlocked achievements/owned identities с provenance;
   locked данные не раскрываются. **Blocker:** API key/live calls не подтверждены;
   ключ не обходит private-profile ограничения и не даёт Cloud save access.
7. **CLD/OPS — автоматизация без скрытой стоимости.** Разрешённый AppID source,
   partial-sync/rollback/error модель, scheduler с free-host sleep, отдельный канал
   доставки/recipient consent. Проверить latency, retry/retention/deletion,
   backup/restore, готовую privacy policy и стоимость на явном масштабе. **Готово:** реальный source change
   → разрешённая доставка; inbox/device/manual import не заменяют эту проверку.

## Продолжение после релиза и stop flags

После подтверждённого выпуска брать первый незаблокированный срез, а не ждать
всех внешних интеграций. Не создавать ключи, grants, платные ресурсы или новые
callbacks ради закрытия checklist. Не публиковать private saves, IDs, paths или
секреты; не запускать write/repair над оригиналами. При неизвестной лицензии,
новой стоимости/доступе или отсутствии semantic evidence остановить только
зависимую часть и явно записать необходимое действие/разрешение.

[Backlog](BACKLOG.md) · [Продукт](PRODUCT.md) · [Требования](REQUIREMENTS.md) ·
[Покрытие парсеров](PARSER_COVERAGE.md) · [Community data](COMMUNITY_DATA.md) ·
[Приёмка](END_TO_END_ACCEPTANCE.md) · [Remote server](../remote_server/README.md).
