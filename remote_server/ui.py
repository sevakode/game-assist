"""Script-free game console views; all untrusted text/attributes are escaped."""
from datetime import datetime, timezone
from html import escape
from starlette.responses import HTMLResponse

GAME = 'Castlevania: Belmont’s Curse'


def esc(value):
    return escape(str(value), quote=True)


def hidden(name, value):
    return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'


def page(title, body):
    return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{esc(title)} · Game Assist</title><link rel="stylesheet" href="/assets/console.css"></head><body><a class="skip" href="#main">К содержимому</a><div class="shell"><header class="topbar"><a class="brand" href="/" aria-label="Game Assist — главная"><span class="brand-icon" aria-hidden="true"><i></i><i></i></span>Game Assist</a><span class="system-status">Только чтение</span></header><main id="main">{body}</main><footer>Сохранения не изменяются. Подсказки — без спойлеров.</footer></div><nav class="system-nav" aria-label="Основная навигация"><a href="/#library"><span class="nav-icon library-icon" aria-hidden="true"></span>Игры</a><a href="/#assistant"><span class="nav-icon assistant-icon" aria-hidden="true"></span>Помощник</a><a href="/setup"><span class="nav-icon device-icon" aria-hidden="true"></span>Устройство</a></nav></body></html>''')


def game_tile(status='Сводки пока нет'):
    return f'''<a class="game-tile selected" href="#selected-game" aria-label="{esc(GAME)} — выбранная игра"><span class="game-cover" aria-hidden="true"><span class="cover-rule"></span><strong>Belmont’s<br>Curse</strong><span class="cover-foot">Castlevania</span></span><span class="game-tile-copy"><strong>{GAME}</strong><small>{esc(status)}</small></span><span class="selection-mark" aria-hidden="true">✓</span></a>'''


def library(status):
    return f'''<aside class="library" id="library"><div class="library-heading"><h1>Игры</h1><span>1 поддерживается</span></div>{game_tile(status)}<p class="library-note">Каталог поддержки, не библиотека твоего Steam.</p></aside>'''


def selected_header():
    return f'''<header class="game-heading" id="selected-game"><p>Выбранная игра</p><h2>{GAME}</h2></header><nav class="section-nav" aria-label="Разделы игры"><a href="#context">Сводка</a><a href="#updates">Обновления</a><a href="#assistant">Помощник</a></nav>'''


def cloud_notice():
    return '<p class="capability-note"><strong>Steam Cloud недоступен.</strong> Сводка поступает только от отдельно подключённого Deck. Его установка необязательна.</p>'


def landing_body():
    return f'''<div class="account-strip"><div><strong>Аккаунт не подключён</strong><p>Вход и разрешения через Steam.</p></div><a class="button primary" href="/login">Войти через Steam</a></div><div class="console-layout">{library('Нет данных аккаунта')}<div class="workspace">{selected_header()}<section class="context-section" id="context"><div class="section-title"><h3>Сводка игры</h3><span class="status-text">Нет данных</span></div><div class="empty-context"><div class="save-icon" aria-hidden="true"></div><div><h4>Пока без сводки</h4><p>Войди, чтобы управлять доступом к игровым данным.</p><p class="small-text">Пароль вводится только на сайте Steam.</p></div></div>{cloud_notice()}<div class="action-row"><a class="button secondary" href="/setup">Настройка Deck</a><a class="plain-link" href="/devices/approve">У меня есть код</a></div></section><section class="utility-section" id="assistant"><div class="section-title"><h3>Помощник</h3><span class="status-text">Подключается отдельно</span></div><p>Здесь нет чата. Можно обсуждать игру в своём ChatGPT или Claude и без компаньона. Для передачи сводки подключи помощника после входа.</p></section><section class="utility-section" id="updates"><div class="section-title"><h3>Обновления</h3><span class="status-text">Не включены</span></div><p>Изменения сводки можно получать на этой странице после подключения устройства. Не push-уведомления.</p></section></div></div>'''


def timestamp(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).strftime('%d.%m.%Y, %H:%M UTC')
    except (ValueError, TypeError, OverflowError, OSError):
        return 'Время неизвестно'


def scalar_text(scalar):
    if isinstance(scalar, dict) and scalar.get('status') == 'known' and type(scalar.get('value')) in (int, float):
        return str(scalar['value'])
    return 'Неизвестно'


def connection_panel(mcp_url):
    if not mcp_url:
        return ''
    return f'''<details class="connection"><summary>Подключить помощника</summary><label for="mcp-url">Адрес сервера MCP, только чтение</label><input id="mcp-url" class="endpoint" readonly value="{esc(mcp_url)}"><ol><li>В веб-версии Claude открой Settings → Connectors → Add custom connector.</li><li>Укажи имя Game Assist и адрес сервера выше.</li><li>Войди через Steam и проверь разрешение на чтение сводок.</li></ol><p class="small-text">Доступность настройки зависит от аккаунта и правил рабочей области. Работа пользовательского MCP в мобильном ChatGPT здесь не проверена.</p><a class="plain-link" href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp" rel="noreferrer">Инструкция Claude</a></details>'''


def home_body(projection, csrf, inbox=None, capabilities=None):
    capabilities = capabilities or {}
    game = next((g for g in projection.get('games', []) if g.get('appid') == 4231820), None)
    summary = game.get('summary') if game else None
    status = 'Сводка от устройства' if summary else 'Сводки пока нет'
    if summary:
        scalars = summary.get('player_scalars', {})
        metrics = ''.join(f'<div class="metric"><dt>{label}</dt><dd>{esc(scalar_text(scalars.get(key)))}</dd></div>' for key, label in [('currentHealth','Текущее здоровье'),('currentMana','Текущая мана'),('healthUpgradeFragmentCount','Фрагменты здоровья'),('manaUpgradeFragmentCount','Фрагменты маны')])
        progress = f'''<dl class="metrics">{metrics}</dl><p class="small-text received">Получено: {esc(timestamp(game.get('received_at')))}</p><details class="data-details"><summary>Что означают эти значения</summary><p>Это переданные значения, не независимая проверка игры. Время самого сохранения неизвестно. Здоровье и мана — не максимумы; смысл счётчиков фрагментов не подтверждён. Карта, процент прохождения и достижения по ним не определяются.</p></details>'''
    else:
        progress = '<div class="empty-context"><div class="save-icon" aria-hidden="true"></div><div><h4>Пока без сводки</h4><p>Нет разрешённой сводки от устройства. Можно подключить Deck или пользоваться помощником без него.</p></div></div>'
    inbox = inbox or {'enabled': False, 'items': []}
    enabled = bool(inbox.get('enabled'))
    updates = ''.join(f'<li><div><p>{esc(item.get("message", "Новая сводка устройства"))}</p><time class="small-text">{esc(timestamp(item.get("created_at")))}</time></div>' + (f'<form method="post" action="/account/notifications/read">{hidden("csrf", csrf)}{hidden("notification_id", item.get("id", ""))}<button class="secondary compact">Прочитано</button></form>' if not item.get('read') else '<span class="status-text">Прочитано</span>') + '</li>' for item in inbox.get('items', []))
    updates = f'<ul class="inbox-list">{updates}</ul>' if updates else '<p class="empty-inbox">Пока нет уведомлений.</p>'
    control = (f'<form class="notification-control" method="post" action="/account/notifications">{hidden("csrf", csrf)}{hidden("appid", "4231820")}{hidden("enabled", "no" if enabled else "yes")}<button class="secondary">{"Выключить обновления" if enabled else "Включить обновления"}</button></form>' if enabled or inbox.get('can_enable') else '<p class="small-text">Для включения нужен компаньон и разрешение на чтение сводки.</p>')
    return f'''<div class="account-strip signed-in"><div><strong>Steam подключён</strong><p>Разрешения можно изменить в настройках доступа.</p></div><a class="plain-link" href="#account">Настройки</a></div><div class="console-layout">{library(status)}<div class="workspace">{selected_header()}<section class="context-section" id="context"><div class="section-title"><h3>Сводка игры</h3><span class="status-text">{esc(status)}</span></div>{progress}{cloud_notice()}<div class="action-row"><a class="button primary" href="/devices/approve">Подключить по коду</a><a class="plain-link" href="/setup">Настройка Deck</a></div></section><section class="utility-section" id="updates"><div class="section-title"><h3>Обновления</h3><span class="status-text">{'Включены' if enabled else 'Выключены'}</span></div>{updates}{control}<p class="small-text">Только на сайте, не push. Новые уведомления появляются при изменениях разрешённой сводки.</p></section><section class="utility-section" id="assistant"><div class="section-title"><h3>Помощник</h3><span class="status-text">Через MCP</span></div><p>Здесь нет чата. ChatGPT или Claude могут читать разрешённую сводку после отдельного OAuth-согласия.</p>{connection_panel(capabilities.get('mcp_url'))}</section><details class="utility-section account" id="account"><summary>Настройки доступа</summary><p>Доступ устройств и помощников можно отозвать. Сохранения на Deck останутся без изменений.</p><div class="account-actions"><form method="post" action="/logout">{hidden('csrf',csrf)}<button class="secondary">Выйти из аккаунта</button></form><details class="revoke-confirm"><summary>Отозвать весь доступ</summary><p>Это отключит устройства и помощников и удалит сводки с сервера.</p><form method="post" action="/account/revoke">{hidden('csrf',csrf)}<button class="danger">Отозвать весь доступ</button></form></details></div></details></div></div>'''


def device_body(csrf):
    return f'''<div class="form-page"><a class="back-link" href="/">К играм</a><h1>Подключение Deck</h1><p class="intro">Введи код, показанный на твоём Steam Deck. Не подтверждай код, присланный другим человеком.</p><form class="form-stack" method="post">{hidden('csrf',csrf)}<label for="device-code">Код устройства</label><input id="device-code" class="code-input" name="user_code" minlength="8" maxlength="8" pattern="[A-Fa-f0-9]{{8}}" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="A1B2C3D4" required><label for="game-select">Игра</label><select id="game-select" name="appid" required><option value="">Выбери игру</option><option value="4231820">{GAME}</option></select><fieldset><legend>Разрешения</legend><label class="check"><input type="checkbox" name="saves.summary" value="yes"><span>Четыре значения игрока<small>Текущие здоровье, мана и два счётчика фрагментов. Не максимумы.</small></span></label><label class="check"><input type="checkbox" name="saves.metadata" value="yes"><span>Метаданные сохранения<small>Удалённый приём метаданных пока не реализован.</small></span></label></fieldset><p class="small-text">Выбери хотя бы одно разрешение. Доступ помощника подтверждается отдельно.</p><div class="action-row"><button class="primary">Подключить устройство</button><a class="plain-link" href="/">Отмена</a></div></form></div>'''


def consent_body(csrf, req, client_label):
    return f'''<div class="form-page"><a class="back-link" href="/">К играм</a><h1>Доступ помощника</h1><p class="intro">Разрешить этому клиенту читать игровые сводки?</p><div class="client-label"><strong>Клиент и адрес возврата</strong><p>{esc(client_label)}</p></div><ul class="permission-list"><li>Только разрешённые тобой сводки.</li><li>Без сырых сохранений и Steam ID.</li><li>Переданные факты покинут Game Assist.</li></ul><p class="small-text">Доступ можно отозвать в настройках на главной.</p><form method="post">{hidden('csrf',csrf)}{hidden('request',req)}<div class="action-row"><button class="primary">Разрешить чтение сводки</button><a class="plain-link" href="/">Не подключать</a></div></form></div>'''


def approved_body():
    return '<div class="form-page"><h1>Устройство одобрено</h1><p class="intro">Вернись на Steam Deck, чтобы завершить настройку.</p><p>Доступ можно отозвать в настройках на главной.</p><div class="action-row"><a class="button primary" href="/">К играм</a></div></div>'


def setup_body(issuer, checksum, command=None):
    intro = '<div class="form-page setup"><a class="back-link" href="/">К играм</a><h1>Компаньон для Deck</h1><p class="intro">Необязательная утилита для передачи разрешённой сводки. Можно пользоваться помощником и без установки.</p><p class="capability-note">Steam Cloud недоступен. Компаньон читает выбранный файл на твоём устройстве, не изменяя его.</p>'
    if not checksum:
        return intro + '<section class="setup-section"><h2>Загрузка пока недоступна</h2><p>Архив компаньона ещё не собран. Установить его с этого сервиса пока нельзя.</p><a class="plain-link" href="/">Вернуться к играм</a></section></div>'
    return intro + f'''<section class="setup-section"><h2>Открыть на Steam Deck</h2><p>Переключись в Desktop Mode и открой <code>{esc(issuer+'/setup')}</code>. Вход в ChatGPT на Deck не нужен.</p><details><summary>Проверить требования</summary><p>Нужны Python 3.10+, модуль venv и активная сессия systemctl --user. Если их нет — остановись: не используй sudo и не отключай защиту SteamOS.</p></details></section><section class="setup-section"><h2>Скачать и проверить</h2><p>Сохрани архив как deck-companion.zip в Downloads. В нём исходный код стандартной библиотеки, без pip-пакетов и готовых бинарных файлов.</p><div class="action-row"><a class="button primary" href="/downloads/deck-companion.zip">Скачать ZIP</a><a class="plain-link" href="/downloads/deck-companion.zip.sha256">Файл SHA256</a></div><details><summary>Команды проверки и установки</summary><p>Изучи исходники и команды. Ничего не запускается автоматически. В Konsole сначала проверь контрольную сумму; продолжай только после OK.</p><pre>{esc(command or '')}</pre><p class="small-text">SHA256: <code>{esc(checksum)}</code></p></details></section><section class="setup-section"><h2>Подключить устройство</h2><p>Выбери путь к сохранению. На телефоне войди через Steam по адресу сопряжения и сравни код с кодом на своём Deck. Выбери игру AppID 4231820 и разрешённую сводку из четырёх полей.</p><div class="action-row"><a class="button secondary" href="/devices/approve">Ввести код устройства</a></div><details><summary>Фоновая работа и ограничения</summary><p>Установка спросит разрешение перед включением фоновой службы. Сохранения не изменяются. Сопряжение действует 30 дней.</p><p>Работа в Gaming Mode ещё требует проверки на реальном Deck. Бесплатный хостинг может просыпаться около минуты. Помощник подключается отдельно через OAuth.</p></details></section></div>'''
