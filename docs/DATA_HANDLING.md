# Статическая страница «Как обрабатываются данные»

В текущем candidate подключены публичные `GET /data-handling` и `HEAD /data-handling`.
Модуль `remote_server/data_handling.py`, функция `data_handling_page()`, маршрут в
`remote_server/app.py`; общий footer в `remote_server/ui.py` содержит ссылку
«Как обрабатываются данные». Candidate **ещё не опубликован**.

Это техническое описание, не окончательная privacy policy, не юридическое
заключение и не compliance statement. Дата редакции текста: 2026-11-01.

## Контракт подключённой страницы

Страница доступна без входа. Handler не читает пользовательскую сессию, cookies
или Authorization, не создаёт сессию и не вызывает Steam. Renderer не принимает
request, конфигурацию или пользовательские данные. Ответ статичен; используются
существующий `/assets/console.css` и общие защитные границы приложения.
Новых scripts, внешних ресурсов и сетевых источников нет.

Ответ через общий Boundary содержит `X-Robots-Tag: noindex, nofollow`, no-store и strict-origin; страница
не добавлена в sitemap/discovery public-pages allowlist. Noindex — указание
поисковым роботам, не контроль доступа. Ссылка намеренно не называется
«Политика конфиденциальности», пока отдельная политика не завершена.

## Источники технических утверждений

| Тема | Доказательство |
| --- | --- |
| SteamID, сессии, отдельные scopes и текущие grants | `remote_server/schema.py`, `app.py`: login/callback, Store.projection, consent и MCP tools |
| 4 поля Belmont, локальное чтение и явная отправка | `remote_server/import.js`, `belmont-parser.js`, browser observations handler |
| Минимизированные библиотека/достижения, transient raw response | `library_reader.py`, `achievements.py`, Store.library/projection |
| Optional library consent выключен по умолчанию; refresh не расширяет права | `ui.py:consent_body`, consent handler в `app.py`, `oauth.py` |
| OAuth access 600 s, refresh 2592000 s, code 120 s | `oauth.py`: approve/_issue и refresh flow |
| Web session 86400 s; login/pending/pairing 600 s; device 2592000 s | `app.py`, `oauth.py` |
| Cache 24 h, dedup events 2678400 s, inbox 30 days | `app.py`: cache reads/writes, ingest, INBOX_TTL и notification methods |
| Revoke не удаляет профиль/сессии/registrations | `app.py:revoke/logout`, Store.revoke_scope/revoke_game; `oauth.py:revoke_subject` |
| Локальные credential/path/queue остаются отдельными копиями | `deck/client.py`, `deck/install.py:uninstall` |
| Часть логов редактируется; access log отключён | `achievements.py`, `database.py`, `__main__.py` |
| Render Virginia | Подтверждённое размещение сервиса; это не утверждение о регионах всех дополнительных копий |
| Neon aws-us-east-1, history retention 21600 s | Проверенные настройки проекта на 2026-10-31; история восстановления не является TTL всех данных/копий |

Получение ключа владельцем не доказывает, что источник уже настроен: renderer не читает environment,
не вызывает Steam и не выводит операторский secret variable name.
Публичная страница не содержит project IDs, Library IDs, приватных ссылок, контакта оператора или данных пользователя.
Техническое название региона `aws-us-east-1` — разрешённое публичное описание размещения, не ID проекта.

### Официальные источники

Источники проверены 2026-10-31; ссылки не означают принятие соглашений:

- [Steam Web API Terms](https://steamcommunity.com/dev/apiterms?l=english): §2 требует информирования о сохраняемых Steam Data и странах хранения. Это причина проверить окончательную политику; само техническое описание её не заменяет.
- [Render Logs](https://render.com/docs/logging): retention зависит от workspace plan; free compute не устанавливает его. Конкретный срок логов на странице не обещается.
- [Render Persistent Disks](https://render.com/docs/disks#disk-snapshots): snapshots диска не являются backup удалённой Neon БД.
- [Neon History window](https://neon.com/docs/postgres/backup-restore/history-window): история восстановления не является TTL рабочих строк или всех копий. На странице указано проверенное значение настройки, не предполагаемый default.
- [Neon Metrics and logs](https://neon.com/docs/reference/metrics-logs): сведения о доступном экспорте не доказывают его настройку у нас.

## Блокер для окончательной публичной политики

Техническая страница уже интегрирована в candidate; перечисленное ниже относится
к окончательной публичной политике, не к наличию маршрута. До выпуска окончательной политики владельцу нужно определить:

1. Юридическое имя/статус оператора, контакт для запросов о данных, целевые страны и возраст пользователей; не придумывать контакт или правовое основание.
2. Реальные logging/streaming/APM настройки, сроки, доступ операторов и внешних получателей. Тариф Render workspace неизвестен; service free не отвечает на этот вопрос.
3. Дополнительные backup/branch/export копии, их страны и сроки удаления. Регион Neon и шестичасовое PITR уже подтверждены — повторно запрашивать их не нужно.
4. Сроки хранения профиля, пользовательских labels, client registrations и неактивных snapshots; процесс полного удаления/экспорта, включая повторное применение отзывов после restore.
5. Используемые AI-поставщики и применимые настройки/условия получателей; кто оценит MCP-передачу, attribution и disclaimers относительно Steam Terms.
6. Кто принимает условия от имени оператора и подтверждает готовность публичной политики. Наличие API-ключа не заменяет эти сведения и не подтверждает принятие необходимых условий.

## Проверки и оставшиеся ограничения

```sh
python -m unittest discover -s tests -p 'test_data_handling*.py' -v
```

`test_data_handling.py` проверяет escaping, статический renderer без
request/config/storage, независимость от synthetic cookies/Authorization/query,
отсутствие Set-Cookie, активных элементов, внешних ресурсов и внутренних IDs,
а также раскрытие согласий, сроков и ограничений удаления.

`test_data_handling_integration.py` проверяет подключённый app: anonymous GET/HEAD
без Store/network, noindex, footer link, сохранение Host/method boundaries и
отсутствие страницы в sitemap/discovery allowlist. Это уже integration tests,
не только standalone renderer checks.

Focused checks и полный локальный прогон прошли; PostgreSQL tests в полном
прогоне пропущены, поэтому real-PostgreSQL acceptance не заявляется. Узкий
browser preview визуально проверен: страница читаема. Это не проверка
опубликованного маршрута, настоящего Steam/Claude или юридической готовности.
После публикации нужны GET/HEAD, headers, footer/CSS smoke checks на deployed
revision. Сроки провайдерских логов, дополнительные копии и полный процесс
удаления остаются открытыми вопросами выше.
