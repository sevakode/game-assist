# Остаток до готового продукта

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


**Порядок дальнейшей работы и критерии готовности:** [ROADMAP.md](ROADMAP.md).
После каждого проверенного релиза продолжаем следующий незаблокированный срез;
публикация не означает завершение продукта.

## Ближайшая очередь (2026-10-31)

1. **IMP-01/02/03 опубликованы:** browser-local preview и отдельно подтверждаемая
   projection-only отправка; 314-test checkpoint, security review, synthetic и
   локальное private-file JS/Python parity проверены. **IMP-04 открыт:** реальный
   authenticated manual flow на телефоне. Это fallback, не автоматический Cloud.
2. **BEL-01 protocol/review и 19 тестов готовы локально** (5 файлов), ещё не
   опубликованы. Общая suite: **333 теста, 20.977 s, real PostgreSQL, 0 skips, PASS**.
   Controlled before/after и точный build/in-game ground truth для BEL-02…04
   остаются нужны; pickup mapping неизвестен.
3. **ER/W3:** permissive dependency review и версии/семантика; приватная ER
   fixture есть, W3 fixture отсутствует. Не исполнять community profiles как код.
4. **ACH-01:** 12 файлов reviewed с cost guards и объединены локально по baseline
   SHA. Staging: 359 тестов, 23.500 s, real PostgreSQL, 0 skips, PASS; integrated
   suite: **359 тестов, 24.510 s, actual PostgreSQL, 0 skips, PASS**; compile,
   JS syntax, Node parity/UI, catalog/profiles прошли. Не опубликовано; ключа и live API нет. **CLD:** источник,
   scheduler и доставка — только после отдельных access/consent gates.
5. **OPS/DECK/COM:** mobile acceptance, retention/security/cost, физический Deck
   и небольшие проверяемые community вклады.

Universal release `33badaca909f539f63d38114775ff40cf4a22152` опубликован на Render
2026-10-31 в 18:22:37 UTC; [CI](https://github.com/sevakode/game-assist/actions/runs/41228842316).
Подтверждён checkpoint **297 тестов, включая настоящий одноразовый PostgreSQL**.
Публичная game-focus/back navigation визуально проверена; phone/authenticated
acceptance остаётся открытой. Это не 297 PostgreSQL-тестов и не live Cloud acceptance.
Manual-import release `648c2719368c57da23566497e1a2358f2d05462f` LIVE на Render
в 18:34:13 UTC, deploy `dep-dbj38t5g1s2s73elkt7g`;
[CI](https://github.com/sevakode/game-assist/actions/runs/41229868518).
Public assets/health/auth gate проверены. 314-test release checkpoint и локальное
JS/Python parity реального приватного файла не закрывают IMP-04. Последующие
BEL-01/333-test checkpoint, объединённый ACH-01 и эта roadmap-правка пока локальные;
не считать их опубликованными до следующего проверенного выпуска. Локальный
GET /import login-return исправлен; API POST без сессии остаётся 401. Универсальные AppID/права и generic
metadata не означают универсальные парсеры; Belmont остаётся четырьмя scalar-полями
формата 1.1.3. Детальные blockers и definition of done — в roadmap.

Требования подтверждены в REQUIREMENTS.md: MIT, ChatGPT+сайт, shared/self-host, без спойлеров, нейтральные напоминания. Первая практическая цель — HP/мана Belmont’s Curse; реальные флаги требуют сейвов и проверки.

ACH-01 локально: per-game default-off consent, ручной refresh с 15-минутным
ограничением, только unlocked cache с expiry 24 h; 20 игр/owner, 512 entries globally,
128 KiB/entry, до 64 MiB payload. Revoke/in-flight consent epochs учтены. Дальше —
привязка прошедшей integrated regression к revision и combined release; live gate требует безопасной настройки
операторского ключа пользователем и consented проверки доступного профиля. Ключ
не гарантирует доступ к private Steam profile; credentials не создавались.

## Приоритет продукта
- **Базовый целевой режим — без установки:** разрешённый облачный источник, автоматическое обнаружение изменений и отдельное согласие на уведомления. Пока недоступен: нет подтверждённого Steam Cloud доступа, работающего Cloud ingestion и проверенного исходящего канала.
- **Необязательный компаньон PC/Steam Deck:** более быстрое обнаружение локальных изменений с передачей минимальной разрешённой проекции. Не является обязательным условием базового режима и не гарантирует real-time.
- Ручная загрузка каждого сейва не заменяет автоматический базовый режим. Steam OpenID не даёт Cloud-доступа. Ограничения и план: [CLOUD_SYNC_NOTIFICATIONS.md](CLOUD_SYNC_NOTIFICATIONS.md).

## Beta уже опубликована — не полная продуктовая приёмка
- Сайт: https://game-assist.onrender.com; исходники: https://github.com/sevakode/game-assist.
- Согласованный Render Free + Neon PostgreSQL размещён; проверены HTTPS, health, OAuth metadata и ZIP компаньона.
- Зафиксированная проверенная runtime-ревизия: `6ff1b5cc05b84f75ca1cb07c855a31ce512d570a`; документация main на момент этой записи: `2b752021c8c7ddcb887ac5d12986b085a1215687`.
- Предыдущая регрессия: 197 тестов с настоящим одноразовым PostgreSQL. Это не результат текущей параллельной реализации backend/UI и не доказательство внешних интеграций.
- Реализованы разрешения по играм, безопасные проекции, экспорт/удаление, Steam OpenID, hosted OAuth/MCP, привязка устройства и Linux watcher. Наличие кода и автоматических тестов не закрывает live acceptance.
- Скриншот с телефона указывает на успешный вход на сайте Steam; полный callback/привязка личности и OAuth-поток приложения ещё не подтверждены.

## Не закрыто
- Реальный пользовательский Steam OpenID round-trip и API acceptance с разрешённым операторским доступом. Single/multiple/all-current выбор зарегистрированных игр и review scopes опубликованы в universal release; это не импорт принадлежащей пользователю Steam-библиотеки и не live acceptance.
- Официально разрешённый Cloud-источник для конкретной игры, обнаружение версий, расписание с учётом сна free host и подтверждённый канал доставки на телефон.
- Opt-in inbox сайта и ограниченные device-изменения опубликованы в universal release; реальные интеграции и live acceptance фиксируются отдельно. Inbox сайта сам по себе не означает push, Cloud ingestion или самостоятельное сообщение ChatGPT/Claude.
- Реальная OAuth/PKCE приёмка Claude/ChatGPT, отзыв, refresh/replay, изоляция пользователей и поддержка выбранного мобильного клиента.
- Необязательный путь устройства: реальные тесты SteamOS/Game Mode, suspend/resume/offline/reboot, Windows watcher, установщики/автозапуск/подпись.
- Фоновые обновления достижений и эксплуатационная проверка миграций/retention/audit в production.
- Проверенные декодеры конкретных игр, тестовые сейвы с согласием владельца и контролируемое before/after сопоставление HP/маны. Сырые счётчики не доказывают число собранных улучшений.
- Источники карт/гайдов, spoiler control и доказуемые рекомендации.
- Визуальные, прерываемые и повторные UI-сценарии, независимый security review, юридические тексты, release acceptance и измерение стоимости.

Не считать создание кода, опубликованный URL или прошлую регрессию подтверждением работоспособности новых функций и внешних интеграций.
