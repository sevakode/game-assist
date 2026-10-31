# Game Assist: проверяемый roadmap

Обновлено 2026-10-31, 22:48 UTC. Релиз — контрольная точка, не завершение
разработки. Сроки, проценты покрытия и одобрение Valve не обещаются.

## Текущее состояние

Опубликованный baseline — `3fc…`. Следующие три среза **объединены локально,
но ещё не опубликованы**:

| Срез | Реализовано | Граница доказанного |
|---|---|---|
| Read-only save inspector, 4 файла | Локальная проверка и категориальное before/after сравнение | Belmont остаётся четырьмя scalar-полями; ER — только распознавание сигнатуры, формат unsupported; W3 unsupported. Нет gameplay mapping |
| Deck doctor/recovery, 7 файлов | Диагностика и восстановительные сценарии необязательного компаньона | Не доказана работа на физическом Steam Deck/Game Mode |
| OAuth, 7 файлов | RFC 9207, сохранение identity и существующего callback allowlist | Не созданы ключи/grants, новый ChatGPT callback не настроен; live Steam/Claude acceptance не пройден |

Общий локальный прогон: **476 обнаруженных тестов за 10.151 s; 83 PostgreSQL
skips, 393 выполненных PASS**. Это **не** проверка на настоящем PostgreSQL.
Независимые проверки: save 15, OAuth 27, Deck 54 — PASS; они не суммируются с
общим прогоном. Перед публикацией нужны actual-PostgreSQL CI и exact revision.

Code-only Deck ZIP: **12 entries, 73 102 bytes**; SHA-256:
`7a47e5d9832d2ce7db83a5fca5a44be0f719e9e620881204574c72ba2e9345b2`.
Контрольная сумма подтверждает конкретный артефакт, не физическую установку.

**Исторический checkpoint:** предыдущий UI/catalog candidate прошёл 424 теста
за 28.394 s на actual PostgreSQL без skips; static browser preview проверен на
1165 px и effective 388 px без overflow. Это не результат нынешнего набора и не
настоящий Android authenticated flow. Матрица: [RELEASE_QA_MATRIX](RELEASE_QA_MATRIX.md).

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

1. **REL — проверить и выпустить три локальных среза.** Прогнать actual disposable
   PostgreSQL CI без подмены skips успехом; проверить ZIP, exact revision и review.
   После разрешённой публикации проверить CI/deploy revision, health, metadata,
   download checksum и безопасные auth gates. **Готово:** свидетельства относятся
   к одному артефакту, нет regression/security blocker. Сейчас actual-PG CI и выпуск
   pending; приватные данные в package не включать.
2. **IMP-04 / OAuth — настоящий пользовательский путь.** Steam sign-in → выбранная
   игра/scopes → browser file preview → отдельная projection-only отправка →
   разрешённый MCP клиент; cancel/retry/expiry/revoke. **Evidence:** реальный телефон
   и выбранный клиент, без секретов в отчёте. **Blocker:** live Steam/Claude/Android
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
   **Готово:** permitted unlocked achievements/owned identities с provenance;
   locked данные не раскрываются. **Blocker:** API key/live calls не подтверждены;
   ключ не обходит private-profile ограничения и не даёт Cloud save access.
7. **CLD/OPS — автоматизация без скрытой стоимости.** Разрешённый AppID source,
   partial-sync/rollback/error модель, scheduler с free-host sleep, отдельный канал
   доставки/recipient consent. Проверить latency, retry/retention/deletion,
   backup/restore и стоимость на явном масштабе. **Готово:** реальный source change
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
