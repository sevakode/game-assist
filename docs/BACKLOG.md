# Остаток до готового продукта

Обновлено 2026-10-31, 22:48 UTC. Порядок и критерии: [ROADMAP.md](ROADMAP.md).
Публикация не завершает разработку; следующий шаг — первый незаблокированный срез.

## Текущий candidate — локальный, не опубликован

Live baseline: `3fc…`. Объединены:
- **Save inspector (4 файла):** локальный read-only осмотр и категориальное
  before/after. Belmont — прежние четыре scalar-поля; ER signature-only,
  unsupported; W3 unsupported. Игровая семантика не добавлена.
- **Deck doctor/recovery (7 файлов):** диагностические/recovery сценарии;
  физический SteamOS/Game Mode ещё не проверен.
- **OAuth (7 файлов):** RFC 9207 и сохранение identity/существующего allowlist;
  новые ключи/grants не созданы, ChatGPT callback не настроен.

Локально: **476 discovered, 10.151 s, 83 PostgreSQL skips, 393 executed PASS**.
Это не real-PG acceptance. Независимые reviews: save 15 / OAuth 27 / Deck 54 PASS.
Code-only ZIP: 12 entries, 73 102 bytes,
SHA-256 `7a47e5d9832d2ce7db83a5fca5a44be0f719e9e620881204574c72ba2e9345b2`.
**Открыто перед выпуском:** actual-PostgreSQL CI, exact revision/artifact, публикация
и безопасный deployed smoke. Предыдущие 424 real-PG теста / 28.394 s / 0 skips —
исторический checkpoint другого candidate, не доказательство текущего.

## Следующие проверяемые задачи

- [ ] **REL:** actual disposable-PG CI → review → разрешённый выпуск → проверить
  deployed revision/health/OAuth metadata/ZIP checksum; затем продолжать roadmap.
- [ ] **IMP-04/OAuth:** настоящий phone Steam callback, consent, manual import и
  выбранный MCP клиент с cancel/retry/revoke. Static preview/test client не замена.
- [ ] **BEL:** controlled private before/after + точный build + независимый
  in-game ground truth; один reviewed mapping. Пока unknown, не число улучшений.
- [ ] **DECK:** физическая установка, doctor/recovery, Game Mode, suspend/offline,
  expiry/revoke/uninstall с неизменными оригиналами.
- [ ] **ER/W3:** licenses/dependencies/build/fixtures до gameplay adapter;
  signature/container recognition не означает поддержку прогресса.
- [ ] **ACH/LIB:** безопасная операторская настройка ключа и consented live check;
  private profile не становится доступным по одному ключу. Никакого auto-grant.
- [ ] **CLD/OPS:** разрешённый Cloud source, scheduler, отдельно разрешённая
  доставка, реальные latency/cost/retention/restore evidence.

## Что по-прежнему нельзя обещать

17 discovery игр ≠ 17 декодеров; profiles 3, real knowledge facts 0. Универсальные
AppID/permissions ≠ универсальный parsing. Только Belmont JSON 1.1.3 имеет четыре
raw scalar поля, без pickup mapping/максимумов HP/маны. Manual import не Cloud;
Deck optional, inbox не push. Реальные Steam/Claude/Deck/controlled-fixture gates
остаются открыты. Новые credentials/cost/access и публикация private данных требуют
отдельной границы разрешения; работа над безопасными независимыми тестами продолжается.
