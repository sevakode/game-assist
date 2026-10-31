# Остаток до готового продукта

**Порядок дальнейшей работы и критерии готовности:** [ROADMAP.md](ROADMAP.md).
После каждого проверенного релиза продолжаем следующий незаблокированный срез;
публикация не означает завершение продукта.

## Ближайшая очередь (2026-10-31)

1. **IMP-01/02/03 реализованы локально:** browser-local preview и отдельно
   подтверждаемая scope-checked projection-only отправка; security review и
   synthetic cancel/parity tests прошли. Итоговая локальная regression прошла; release freeze и публикация
   ещё впереди. Затем **IMP-04:** реальный manual flow на телефоне. Это fallback,
   не автоматический Steam Cloud.
2. **BEL-01…04:** controlled before/after HP/маны, точный build, независимое
   наблюдение и один проверенный knowledge mapping; не догадки по счётчикам.
3. **ER/W3:** permissive dependency review и версии/семантика; приватная ER
   fixture есть, W3 fixture отсутствует. Не исполнять community profiles как код.
4. **ACH/CLD:** mock-tested контракты сейчас; live достижения, Cloud source,
   scheduler и доставка — только после отдельных credential/consent gates.
5. **OPS/DECK/COM:** mobile acceptance, retention/security/cost, физический Deck
   и небольшие проверяемые community вклады.

Universal release `33badaca909f539f63d38114775ff40cf4a22152` опубликован на Render
2026-10-31 в 18:22:37 UTC; [CI](https://github.com/sevakode/game-assist/actions/runs/41228842316).
Подтверждён checkpoint **297 тестов, включая настоящий одноразовый PostgreSQL**.
Публичная game-focus/back navigation визуально проверена; phone/authenticated
acceptance остаётся открытой. Это не 297 PostgreSQL-тестов и не live Cloud acceptance.
Следующий manual-import релиз пока локальный: **314 тестов за 20.626 s, настоящий
PostgreSQL, 0 skips, PASS**; compile/JS syntax/parser/UI/catalog/profile checks
прошли. Его commit/CI/deploy фиксируются отдельно; публикации ещё не было. Универсальные AppID/права и generic
metadata не означают универсальные парсеры; Belmont остаётся четырьмя scalar-полями
формата 1.1.3. Детальные blockers и definition of done — в roadmap.

Требования подтверждены в REQUIREMENTS.md: MIT, ChatGPT+сайт, shared/self-host, без спойлеров, нейтральные напоминания. Первая практическая цель — HP/мана Belmont’s Curse; реальные флаги требуют сейвов и проверки.

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
