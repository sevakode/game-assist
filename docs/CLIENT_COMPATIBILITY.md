# AI-клиенты: документированная поддержка и готовность Game Assist

Дата проверки публичных официальных источников: **2026-10-31**. Это исследование
документации, не проверка реальных клиентов. Никакие клиенты не регистрировались,
приватные кабинеты не открывались, credentials и callback IDs не собирались.

Первый срез начат после `2ddc9b12f28af6e5a10e706f73d6105f2c7d9743`;
инструкции дополняют переданный checkpoint `d68dba4a02c2073c886d325bfd01fcf4613f5703`;
код приложения проверен на базе `ef1cc6e2cb58711997256c9df36698822cfc54d9`.
Последующие изменения backend/consent в родительской staging здесь не проверены.
`discovery.py`, его тесты и `AI_DISCOVERY.md` заморожены и не изменены.

## Как читать матрицу

- **Документировано** — утверждение официального поставщика о конкретном клиенте.
  Это не результат теста Game Assist. «Не подтверждено» означает пробел в
  просмотренных источниках, а не доказанное отсутствие функции.
- **Настроено** — состояние Game Assist из переданного задания: hosted allowlist
  подтверждён только для Claude; ChatGPT callback/плагин не подключены.
- **Проверено** — успешный реальный вход, выдача разрешений и вызов инструмента.
  Для перечисленных клиентов таких доказательств в этом срезе нет.
- Модель Claude/GPT/Gemini и приложение Claude/ChatGPT/Cursor/IDE/CLI — разные
  уровни. Выбор модели в одном клиенте не переносит коннекторы, токены или
  разрешения из другого. Поддержку Gemini CLI нельзя приписывать Gemini web/mobile,
  а VS Code/Copilot — всем продуктам под названием Copilot.

Одна публичная ссылка позволяет найти описание. Она не устанавливает соединение
во всех AI и не передаёт закрытые инструменты или токены. AI без коннекторов может
прочитать публичную страницу при наличии браузера; приватный прогресс недоступен.

## Компактная матрица

Везде ниже «HTTP» означает remote **Streamable HTTP**, не только обычный HTTP URL.
DCR — динамическая регистрация OAuth-клиента; CIMD — опубликованные метаданные
клиента; PKCE — защита обмена authorization code. Они не взаимозаменяемы.

| Клиент / поверхность | Документировано: HTTP / OAuth | Настроено в Game Assist | Проверено с Game Assist | Следующий шаг пользователя |
| --- | --- | --- | --- | --- |
| Claude: web, Desktop, mobile, Cowork; hosted connector | HTTP — да [C1]. DCR, CIMD, PKCE S256 — да [C2]. | Только hosted callback разрешён; использовать DCR, не CIMD. | Реальный OAuth/вызов ещё не доказан. | В Customize → Connectors добавить endpoint, выбрать Register automatically и Sign in now; пройти consent, включить коннектор в чате [C3]. |
| Claude Code: прямое CLI-подключение | Remote HTTP, DCR/CIMD — да [C4]; S256 указан для Claude Code в общей auth-документации [C2]. | Нет; hosted callback не покрывает CLI loopback. | Нет. | Пока ждать отдельной настройки и приёмки. Затем `claude mcp add --transport http <name> <endpoint>` и `/mcp` [C4]. |
| ChatGPT: custom MCP / plugin | HTTP — да [O1]; DCR/CIMD и S256 — да [O2]. | Callback и плагин не подключены; наличие RFC9207 в сервере не завершает настройку. | Нет. | После настройки: Plugins → Add custom MCP server, endpoint и OAuth; установить полученный plugin и выбрать его через @ [O3]. |
| Cursor | HTTP, DCR public client и PKCE — да; S256 и CIMD отдельно не подтверждены в просмотренной странице [U1]. | Нет; нужно проверить весь набор callback URI выбранной поверхности. | Нет. | После операторской приёмки добавить URL через Customize или `mcp.json`, затем OAuth [U1]. |
| VS Code / Copilot: конкретный harness | HTTP и DCR — да [V1]; CIMD и конкретный PKCE-метод в просмотренных руководствах не подтверждены. | Нет; loopback и HTTPS redirects требуют отдельного решения. | Нет. | MCP: Add Server → HTTP, выбрать scope/формат, выполнить вход; убедиться, что сервер доступен именно текущему harness [V2, V3]. |
| Gemini CLI | HTTP, OAuth и DCR — да; CIMD и PKCE-метод в просмотренном руководстве не подтверждены [G1]. | Нет; стандартный HTTP loopback не разрешён текущей политикой. | Нет. | После операторской приёмки добавить HTTP server, затем `/mcp auth <name>` [G1]. |
| Codex CLI / IDE extension | HTTP и OAuth — да; автоматическая регистрация описана; CIMD и PKCE-метод здесь не подтверждены [O4]. | Нет; текущий callback/loopback режим не принят сервером. | Нет. | После операторской приёмки добавить URL через `codex mcp add` или IDE MCP servers; `codex mcp login <name>` [O4]. |

Нет основания помечать неизвестные ячейки «да» только потому, что клиент заявляет
совместимость с MCP. Даже «да» во всех протокольных колонках не означает готовый
доступ конкретного пользователя к Game Assist.

## Краткие инструкции: готовность указана перед действиями

**Сейчас разрешённый сервером путь для приёмки — Claude hosted.** Это ещё не
доказанная end-to-end совместимость. Остальные рецепты — ручная настройка клиента
**после** закрытия указанного blocker оператором, не обещание работающего входа.
Ни одну команду из рецептов в этом исследовании не запускали.

`ENDPOINT` ниже — значение `config.issuer + '/mcp'`, показанное проверенной
страницей подключения конкретной установки. Заменить это обозначение перед
вводом; оно не является hostname. Использовать `/mcp`, не адрес главной или `/connect`.
Ручной JSON нужно объединить с существующей конфигурацией, а не перезаписать файл.

После входа попросить AI: «Вызови get_progress. Покажи только доступные мне данные;
если данных нет, скажи об этом и спроси, во что я играю». Проверить именно результат
вызова инструмента. Ответ из памяти модели не подтверждает связь. Библиотеку
проверять отдельно по GA3; этот запрос её разрешений не выдаёт.

### Claude hosted — доступен путь для приёмки

Платформа: начинать в web; hosted connector распространяется на поддерживаемые
поверхности аккаунта, включая Desktop/mobile/Cowork [C1, C5]. Локальный Desktop
MCP и прямой Claude Code не входят в эту отметку. Права на добавление зависят от
плана и организации [C3].

1. Открыть Customize → Connectors → Add custom connector, ввести Game Assist
   и `ENDPOINT`. Если управление принадлежит организации — сначала её администратор
   добавляет коннектор, затем пользователь подключает свой аккаунт.
2. Выбрать Sign in now и Register automatically. Не выбирать published identity:
   это CIMD, которого Game Assist не реализует [C2, C3; GA2].
3. Завершить Steam-вход и проверить запрошенные разрешения на странице Game Assist.
4. В новом чате включить Game Assist через `+` → Connectors и выполнить контрольный
   запрос выше [C3].

Ручной путь — этот диалог; подтверждённого endpoint-install deep link нет.
Blocker готовности: реальный OAuth/вызов ещё не зафиксирован. Если вход отклонён,
сохранить только текст ошибки без URL с code/state; не заменять OAuth ручным токеном.

### ChatGPT web — следующий кандидат, пока не настроен

Платформа: custom MCP на web; mobile в этом режиме не поддерживается. Учитывать
workspace/admin permissions и отдельные ограничения Pro read/fetch; наличие плана
не доказывает доступ к конкретному потоку [O3].

1. **Сначала операторский этап ниже.** Затем в доступном аккаунту интерфейсе
   Plugins выбрать Add custom MCP server и ввести имя и `ENDPOINT`.
2. Настроить OAuth/DCR для существующего Game Assist public-client пути; не вводить
   придуманный client secret и не выбирать неподдерживаемый CIMD [O2].
3. Просмотреть предупреждение клиента, создать соединение, пройти Steam/consent,
   проверить обнаруженные tools. Названия кнопок сверить с фактическим UI [O3, O5].
4. Установить полученный plugin, открыть новый чат, выбрать его через @ и выполнить
   контрольный запрос [O3].

Ручной путь — UI добавления endpoint. Универсальный install URL не подтверждён.
Blocker: точный callback/соединение не настроены; общий домен ChatGPT недостаточен.
Legacy Apps flow не смешивать с текущим Plugins flow; отдельный Developer Mode
для последнего в инструкции не требуется [O3].

### Cursor desktop — рецепт после операторской приёмки

1. В `.cursor/mcp.json` проекта или `~/.cursor/mcp.json` пользователя добавить
   `{"mcpServers":{"game-assist":{"url":"ENDPOINT"}}}` [U1].
2. В Customize найти сервер и пройти предложенный OAuth-вход; затем контрольный
   запрос. Не добавлять bearer/секреты в JSON вместо OAuth.

Blocker: desktop DCR может зарегистрировать одновременно loopback и web callback;
Game Assist проверяет **весь** набор. HTTPS handoff сам по себе не решает отказ.
Web/Agents — отдельная поверхность с HTTPS callback, не доказанная этим desktop
рецептом. Mobile не проверен [U1; GA1].
Официальный `cursor://anysphere.cursor-deeplink/mcp/install` существует с name и
base64-конфигурацией, но готовая ссылка Game Assist не создана. Она только добавляет
конфигурацию с подтверждением; OAuth остаётся [U2].

### VS Code / Copilot — рецепт для выбранного harness

1. Выполнить MCP: Add Server → HTTP, вставить `ENDPOINT`, выбрать пользовательскую
   или workspace-конфигурацию [V2, V3].
2. Ручная альтернатива для **VS Code format** в `.vscode/mcp.json`:
   `{"servers":{"game-assist":{"type":"http","url":"ENDPOINT"}}}`.
   Для portable Copilot формат другой (`mcpServers`); не копировать файл вслепую [V3].
3. В MCP: List Servers выбрать сервер, запустить/пройти вход и выполнить контрольный
   запрос из текущей agent-сессии [V1–V3].

Blocker: требуются проверка полного redirect-набора и совместимости выбранного
harness с DCR/S256; desktop/browser/remote session не приравниваются [V1, V2; GA1].
Официальный `vscode:mcp/install` описан, точная сериализация здесь не подтверждена;
кнопка Game Assist не предлагается. Ручная установка через `code --add-mcp` также
документирована, но не снимает OAuth blocker [V1, V3].

### Gemini CLI — рецепт после решения native callback

Платформа: локальный CLI с браузером, не Gemini web/mobile.

1. В `settings.json`, в объект `mcpServers`, добавить
   `"game-assist":{"httpUrl":"ENDPOINT"}` [G1].
2. Запустить Gemini CLI и `/mcp auth game-assist`, завершить браузерный вход;
   `/mcp` показывает состояние и инструменты. Затем контрольный запрос [G1].

Blocker: стандартный redirect — HTTP loopback с выделяемым портом, не разрешённый
Game Assist. `redirectUri` и фиксированный порт не делают его автоматически
совместимым. Учитывать проверку RFC9207 `iss`, ограничения headless/SSH/container
без браузерного доступа. Deep link установки не найден; ручной settings-путь
не даёт обхода серверной политики [G1; GA1].

### Codex CLI / IDE — рецепт после операторской приёмки

1. В CLI: `codex mcp add game-assist --url ENDPOINT`, затем
   `codex mcp login game-assist`. Проверить подключение через `/mcp` [O4].
2. Ручная альтернатива: секция `[mcp_servers.game-assist]` с
   `url = "ENDPOINT"` в `~/.codex/config.toml`.
3. В IDE вместо CLI: gear → MCP servers → Add server → Streamable HTTP,
   URL, Save, Restart extension, затем Authenticate [O4]. После входа — контрольный
   запрос.

Blocker: стандартный loopback и режим callback должны быть отдельно приняты
сервером. Значение зависит от metadata/конфигурации; не переносить callback
другого сервера. IDE/CLI не доказывают поддержку cloud tasks или ChatGPT mobile.
Официальный endpoint-install deep link здесь не подтверждён [O4; GA1].

### Claude Code — прямой CLI пока не разрешён

Платформа: установленный Claude Code; это не настройка hosted connector.

1. После отдельной native-приёмки выполнить
   `claude mcp add --transport http game-assist ENDPOINT`.
2. Открыть `/mcp`, пройти OAuth, проверить tools и выполнить контрольный запрос [C4].

Это ручной путь; универсальная install-ссылка не подтверждена.
Blocker: HTTP-loopback callback не проходит текущий серверный HTTPS-only контракт;
`--callback-port` управляет портом, не исправляя схему или allowlist. Нельзя
предлагать пользователю разрешить произвольный localhost. Повторное использование
hosted коннектора в Claude Code — отдельный механизм, не доказательство работы
этого прямого CLI-рецепта [C2, C4; GA1].

**Checkpoint A — инструкции:** для семи вариантов указаны поверхность, ручной путь,
действие пользователя и blocker; примеры содержат только публичную конфигурацию.
Сопоставлены с источниками C1–G1 и O5; реальных подключений не выполнялось.

## Границы на стороне Game Assist

**GA1 — локально проверенный код:** `remote_server/app.py`, `Config.__post_init__`
в базе `ef1cc6e…` принимает только точные HTTPS redirect URI. В
`remote_server/oauth.py` регистрация проверяет каждый запрошенный redirect против
allowlist. Поэтому native HTTP-loopback — реальный текущий blocker, а не просто
отсутствующая строка настройки. Фиксированный порт сам по себе этого не исправляет.
Документ не предлагает ослаблять проверку, wildcard redirects, auth proxy или
передачу bearer вручную. Любая поддержка native flow — отдельная спроектированная,
проверенная backend-задача; конфигурации выше пока не являются ready-to-run гайдами.

**GA2 — базовый протокол:** Streamable HTTP, OAuth public-client DCR,
authorization-code + PKCE S256, exact redirect allowlist; CIMD не реализован.
Основание — локальные `remote_server/README.md`, `app.py`, `oauth.py` и задание
родителя. Это не результат нового live-аудита hosted deployment.

**GA3 — данные и согласия:** по актуальному заданию родителя библиотека требует
отдельного source consent, соответствующего OAuth scope и операторского Steam API
ключа. Старый baseline не доказывает готовность новых library tools/scopes staging.
Не придумывать имя нового scope: брать его из согласованного backend-контракта.
Вход в Steam устанавливает идентичность, не доступ к Steam Cloud. Разрешение на
библиотеку не разрешает автоматически сейвы, достижения, выбор всех игр или
определение текущей игры. Отсутствующие данные должны оставаться неизвестными.

**GA4 — неизвестный live-статус:** реальный вход и чтение разрешённого прогресса
не подтверждены ни для одного клиента этой матрицы. Нельзя менять «не проверено»
на «работает» по результату чтения документации или синтетического DCR-теста.

## Ближайший клиент после Claude: ChatGPT web

**Рекомендация, не результат live-теста:** первым расширением взять ChatGPT web
custom MCP с DCR public client. В отличие от прямых native CLI, этот путь позволяет
остаться в текущей модели точных HTTPS redirects; официально описаны HTTP, DCR,
S256 и выбор callback по issuer metadata [O1, O2]. Cursor desktop может требовать
набор с loopback; VS Code зависит от harness; для Gemini CLI/Codex/Claude Code
native callback пока блокируется. Не обещать срок до проверки аккаунта и UI.

### Безопасные работы до приглашения пользователя

1. **Доступ к клиенту — владелец аккаунта/оператор.** Подтвердить право добавлять
   custom MCP в конкретном ChatGPT web workspace. Зафиксировать тип аккаунта и
   доступный UI, без персональных данных. В этом срезе кабинеты не открывались и
   соединение не создавалось. Если требуемый UI недоступен, это blocker, а не повод
   предлагать иной тариф или новый аккаунт без решения пользователя.
2. **Callback — оператор, отдельная разрешённая настройка.** Получить точный
   redirect для этого соединения из клиентского управления; сверить режим issuer
   identification и весь запрашиваемый DCR redirect-набор [O2]. Не угадывать
   callback IDs и не публиковать их в гайде. Добавление только проверенных HTTPS
   адресов в существующую конфигурацию — будущая работа основной задачи;
   данный документ никаких настроек не меняет.
3. **Backend-контракт — основной backend-агент.** Подтвердить в объединённой staging
   public-client DCR (`none`), S256, точный resource, согласованный issuer в metadata
   и authorization response, refresh/revoke. Согласовать новые library scopes с
   source consent. Старый baseline допускает только `progress.read`, поэтому
   этот документ не копирует его как контракт новой библиотечной интеграции.
4. **Изолированная проверка — backend-агент.** На синтетической базе проверить
   положительный поток с утверждённым HTTPS redirect, отказ другим redirects,
   несовпадающему issuer/resource и отсутствующему consent/scope. Существующие
   session/CSRF/CORS/MCP gates должны остаться. Это критерии приёмки, не выполненные
   тесты нового backend-среза.
5. **Реальный пилот — владелец тестового аккаунта.** После отдельного разрешения
   на создание соединения пройти шаги ChatGPT выше и контрольные сценарии ниже.
   Не публиковать plugin или расширять доступ workspace в рамках пилота.

Точные зависимости за пределами этого файла: operator-owned
`GA_OAUTH_REDIRECT_URIS`; `remote_server/app.py` (metadata, resource и список scopes);
`remote_server/oauth.py` (регистрация/consent/token contract); согласованный контракт
library source consent и его тесты; `remote_server/ui.py` и `/connect` wiring у основной задачи.
Изменение любого из них не входит в данный patch. Нельзя выключать HTTPS-only,
добавлять произвольный localhost или переносить токены вручную ради прохождения пилота.

### Обезличенная карточка приёмки

Заполняется после настоящего пилота; сейчас все пункты **не выполнены**.

| Сценарий | Требуемое наблюдение | Текущий статус |
| --- | --- | --- |
| Добавление и OAuth | Client/version/date, DCR, S256, утверждённый callback, успешный consent | Не выполнено |
| Нет импортированного сейва | Tool реально вызван, данные неизвестны; модель спрашивает игру/цель | Не выполнено |
| Есть разрешённая сводка | Только разрешённые поля тестового аккаунта, без сырого сейва | Не выполнено |
| Нет source consent или library scope | Библиотека не выдаётся; вход не расширяет доступ | Не выполнено |
| Разрешённая библиотека | При наличии операторской настройки выдаётся только разрешённый контракт | Не выполнено |
| Приватная/недоступная библиотека | Неизвестно/недоступно, без выдуманных игр или утверждения «0 игр» | Не выполнено |
| Отзыв и обновление токена | Отозванные права перестают действовать; refresh сохраняет границы доступа | Не выполнено |

В доказательства записывать только названия проверок, даты, версии, статусы и
обезличенные ошибки. Не записывать authorization code/state, cookie, bearer,
SteamID, содержимое библиотеки или полный callback URL. Публичный status-badge
менять на «проверено» только для реально прошедшей поверхности и версии.

**Checkpoint B — следующий клиент и handoff:** выбран ChatGPT web; описаны
операторские/серверные зависимости, семь сценариев приёмки и точная граница
полномочий. Продолжение за пределами документа ожидает утверждённого callback,
доступа владельца к UI и финального library scope-контракта. Эти действия не
отклонены и не выполнялись; результат неизвестным не считается, статус — ожидает
основную задачу/оператора. Повторное переписывание инструкций до новых фактов
не продвинет подключение.

## Предложения для будущих guide pages

1. `/connect` оставить коротким: «Инструкция доступна; реальное подключение ещё
   проверяется» для Claude; «Требует настройки оператора» для остальных. Саму
   матрицу держать внутри документации, не на минимальной главной.
2. `/connect/claude` явно назвать hosted connector, DCR и отдельный Steam/consent
   шаг. Не направлять пользователя к CIMD и не включать Claude Code в ту же
   отметку готовности. Обновлять labels по фактическому интерфейсу аккаунта.
3. Будущие `/connect/chatgpt`, `/connect/cursor`, `/connect/vscode`,
   `/connect/gemini-cli`, `/connect/codex`, `/connect/claude-code` публиковать как
   инструкции подключения только после подтверждения соответствующей поверхности.
   До этого достаточно страницы статуса с конкретным blocker и официальным источником.
4. В каждом гайде: название приложения/поверхности и дата; требования аккаунта;
   endpoint только из trusted issuer; шаг добавления; OAuth/согласия; первый
   разрешённый read-only tool; честный сценарий «данных ещё нет»; отзыв доступа.
   Не просить API-ключи игрока, session cookies или callback URLs с code/state в чате.
5. Cursor/VS Code install buttons рассматривать после приёмки callback-пути:
   кодировать только публичные name/URL/type, показывать подтверждение клиента;
   рядом сохранять ручной способ. Не помещать токены и OAuth state в ссылки.
6. Критерий «проверено»: зафиксировать версию/поверхность и дату, metadata discovery,
   DCR, точный разрешённый callback, S256, consent, token refresh/revoke, первый
   разрешённый вызов и отсутствие данных без source consent/scope. Проверить
   private/empty library и отсутствие сейва. Протоколировать обезличенный результат,
   без credentials. Это будущая приёмка, не выполненные действия этого среза.

## Источники и ограничения исследования

Все ссылки ниже открыты 2026-10-31 через публичный web-доступ. Даты обновления
издателя не подменяются датой проверки. Лимиты планов/UI могут измениться.

- **C1:** [Claude: Build an MCP server](https://claude.com/docs/connectors/building).
- **C2:** [Claude: Authentication for connectors](https://claude.com/docs/connectors/building/authentication).
- **C3:** [Claude: Add an unlisted connector](https://claude.com/docs/connectors/custom/add-unlisted).
- **C4:** [Claude Code: MCP](https://code.claude.com/docs/en/mcp).
- **C5:** [Claude Help: custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- **O1:** [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server).
- **O2:** [OpenAI: Authentication](https://developers.openai.com/plugins/build/auth).
- **O3:** [OpenAI Help: Connecting custom MCP servers](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).
- **O4:** [Codex MCP guide, перенаправление официального developers URL](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- **O5:** [OpenAI: Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt).
- **U1:** [Cursor: MCP](https://prod.cursor.com/docs/mcp).
- **U2:** [Cursor: MCP Install Links](https://prod.cursor.com/docs/mcp/install-links).
- **V1:** [VS Code: MCP developer guide](https://code.visualstudio.com/api/extension-guides/ai/mcp).
- **V2:** [VS Code: Add MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers).
- **V3:** [VS Code: MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).
- **G1:** [Gemini CLI: MCP servers](https://geminicli.com/docs/tools/mcp-server/).

Исторический URL Claude Help `11503834-building-custom-connectors-via-remote-mcp-servers`
вернул **404**. Обхода не было: действующий официальный developer guide найден по
ссылке из доступного Help Center (C1). Это не блокирует выводы, подтверждённые C1–C3.
Поисковые snippets из сторонних каталогов и пользовательских GitHub issues не
использованы как доказательство поддержки. Не найденная install-ссылка не объявлена
несуществующей. Другие AI-приложения без проверенных здесь первичных сведений
намеренно не добавлены в список «поддерживаемых».
