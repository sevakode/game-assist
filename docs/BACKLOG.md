# Остаток до готового продукта

Обновлено 2026-10-31, 23:48 UTC. Порядок и критерии: [ROADMAP.md](ROADMAP.md).
Публикация не завершает разработку; следующий шаг — первый незаблокированный срез.

## Текущий candidate — локальный, не опубликован

Live baseline: `ef1…`, runtime-only rebuild **Python 3.12.16**,
deploy `dep-dbj7p6mtlv9c73cf7tmg`; новых функций этим rebuild не опубликовано.
Wave 2 локально включает:
- **Private capture/compare:** read-only копии/сравнение; настоящие controlled
  пары и semantic mapping ещё не проверены.
- **Deck:** atomic recovery + compatibility workflow; без аппаратной приёмки.
- **OAuth/MCP:** optional `library.read` default OFF, cached/permission-gated
  `get_library`, `connection_status`; без новых ключей и live-client claims.
- **Discovery:** `/connect`, robots/sitemap/llms и private noindex. Noindex не
  заменяет авторизацию и полноценную privacy policy.

Fixture fix и MCP consent/Deck acceptance tests включены; helper MODULES
содержит Deck acceptance. Итоговая suite **600 за 11.296 s: 499 PASS +
101 PG skips, OK**. Отдельная stdlib suite **116 за 1.574 s, 0 skips, PASS**. Это не real-PG проверка. Capture/compare: 22 теста независимо PASS при
umask 0022 и 0077.
Native reviews: MCP 26 / stdlib Deck 113 PASS, без новых findings. JS/manual-import,
compile/catalog/profiles PASS. Guide records 0, profiles 3; Belmont по-прежнему
только четыре raw поля. Исторические 476/83 skips и 424 actual-PG checkpoints
не относятся к текущему candidate. Публикация Wave 2 не выполнена.

## Следующие проверяемые задачи

- [ ] **REL:** fixture fix/локальная regression пройдены; actual disposable-PG CI →
  review → разрешённый выпуск → проверить
  deployed revision/health/OAuth metadata/ZIP checksum; затем продолжать roadmap.
- [ ] **IMP-04/OAuth:** настоящий phone Steam callback, consent, manual import и
  выбранный MCP клиент с cancel/retry/revoke. В docs 7 client recipes; следующий
  кандидат — ChatGPT web. Реальные подключения не проверены; static preview/test
  client не замена.
- [ ] **BEL:** controlled private before/after + точный build + независимый
  in-game ground truth; один reviewed mapping. Пока unknown, не число улучшений.
- [ ] **DECK:** физическая установка, doctor/recovery, Game Mode, suspend/offline,
  expiry/revoke/uninstall с неизменными оригиналами.
- [ ] **ER/W3:** licenses/dependencies/build/fixtures до gameplay adapter;
  signature/container recognition не означает поддержку прогресса.
- [ ] **ACH/LIB:** безопасная отдельное явное согласие на операторский ключ, его безопасная настройка
  и consented live check;
  private profile не становится доступным по одному ключу. Никакого auto-grant.
- [ ] **CLD/OPS:** разрешённый Cloud source, scheduler, отдельно разрешённая
  доставка, реальные latency/cost/retention/restore evidence и готовая privacy policy.

## Что по-прежнему нельзя обещать

17 discovery игр ≠ 17 декодеров; profiles 3, real knowledge facts 0. Универсальные
AppID/permissions ≠ универсальный parsing. Только Belmont JSON 1.1.3 имеет четыре
raw scalar поля, без pickup mapping/максимумов HP/маны. Manual import не Cloud;
Deck optional, inbox не push. Реальные Steam/Claude/Deck/controlled-fixture gates
остаются открыты. Новые credentials/cost/access и публикация private данных требуют
отдельной границы разрешения; работа над безопасными независимыми тестами продолжается.
