"""Script-free game console views; all untrusted text/attributes are escaped."""
from datetime import datetime, timezone
from html import escape
from starlette.responses import HTMLResponse

GAME = 'Castlevania: Belmont’s Curse'
GAMES = {4231820: GAME, 1245620: 'Elden Ring', 292030: 'The Witcher 3: Wild Hunt'}


def focus_id(value, allowed=None):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 4231820
    return value if value in (allowed or GAMES) else 4231820


def game_catalog(capabilities=None):
    supplied = {g.get('appid'): g for g in (capabilities or {}).get('catalog', []) if type(g.get('appid')) is int and g['appid'] > 0}
    catalog = []
    for appid in dict.fromkeys([*GAMES, *supplied]):
        item = supplied.get(appid, {})
        title = GAMES.get(appid, item.get('name') or f'Steam AppID {appid}')
        catalog.append(dict(item, appid=appid, title=title, scopes=item.get('authorized_scopes', (['saves.summary'] if appid==4231820 and item.get('authorized') else []) + (['saves.metadata'] if item.get('metadata_authorized') else []))))
    return catalog



def esc(value):
    return escape(str(value), quote=True)


def hidden(name, value):
    return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'


def page(title, body):
    return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{esc(title)} · Game Assist</title><link rel="stylesheet" href="/assets/console.css"></head><body><a class="skip" href="#main">К содержимому</a><div class="shell"><header class="topbar"><a class="brand" href="/" aria-label="Game Assist — главная"><span class="brand-icon" aria-hidden="true"><i></i><i></i></span>Game Assist</a><span class="system-status">Только чтение</span></header><main id="main">{body}</main><footer>Сохранения не изменяются. Подсказки — без спойлеров.</footer></div><nav class="system-nav" aria-label="Основная навигация"><a href="/#library"><span class="nav-icon library-icon" aria-hidden="true"></span>Игры</a><a href="/#assistant"><span class="nav-icon assistant-icon" aria-hidden="true"></span>Помощник</a><a href="/setup"><span class="nav-icon device-icon" aria-hidden="true"></span>Устройство</a></nav></body></html>''')


def game_tile(status='Сводки пока нет', appid=4231820, active=True):
    title = GAMES[appid]
    cover_title = {4231820:'Belmont’s<br>Curse', 1245620:'Elden<br>Ring', 292030:'The<br>Witcher 3'}[appid]
    return f'<a class="game-tile {"selected" if active else ""}" href="/?game={appid}#selected-game" aria-label="Открыть {esc(title)}" {"aria-current=page" if active else ""}><span class="game-cover cover-{appid}" aria-hidden="true"><strong>{cover_title}</strong></span><span class="game-tile-copy"><strong>{esc(title)}</strong><small>{esc(status)}</small></span></a>'


def library(status, active=4231820, catalog=None, csrf=None):
    catalog = catalog or game_catalog()
    if csrf is None:
        content = '<div class="catalog-tiles">' + ''.join(game_tile('Декодер сводки доступен' if g['appid']==4231820 else 'Декодер недоступен', g['appid'], g['appid']==active) for g in catalog) + '</div><a class="plain-link" href="/login">Войти, чтобы выбрать игры и доступ</a>'
    else:
        choices = ''.join(f'<div class="game-choice {"focused" if g["appid"]==active else ""}"><label><input type="checkbox" name="game_{g["appid"]}" value="yes" {"checked" if g.get("selected") else ""}><span>{esc(g["title"])}<small>{"Название задано пользователем; не проверено. " if g["appid"] not in GAMES else ""}AppID {g["appid"]}</small><small>{"Выбрана" if g.get("selected") else "Не выбрана"} / {"Есть разрешения" if g.get("scopes") else "Нет разрешений"}</small></span></label><a class="game-open" href="{("/?game=" + str(g["appid"]) + "#selected-game") if g.get("selected") else "#library"}" aria-label="{("Открыть " if g.get("selected") else "Выбрать ") + esc(g["title"])}">{"Открыть" if g.get("selected") else "Выбрать"}</a></div>' for g in catalog)
        content = f'<form method="post" action="/account/games" class="game-chooser">{hidden("csrf",csrf)}<fieldset><legend>Выбери одну или несколько</legend>{choices}</fieldset><div class="chooser-actions"><button class="primary" name="action" value="review">Проверить выбор</button><button class="secondary" name="action" value="review_all">Выбрать все текущие ({len(catalog)})</button></div></form><p class="small-text">Выбор сохраняется после проверки. Разрешения на данные задаются отдельно для каждой игры.</p>'
    add_form = (f'<section class="add-game"><h2>Добавить игру</h2><form method="post" action="/account/games/add">{hidden("csrf",csrf)}<label for="new-appid">Steam AppID</label><input id="new-appid" name="appid" type="number" min="1" max="2147483647" step="1" inputmode="numeric" required placeholder="Например, 570"><label for="game-label">Твоё название (необязательно)</label><input id="game-label" name="label" maxlength="120" autocomplete="off"><button class="secondary">Добавить по AppID</button></form><p class="small-text">AppID — число в адресе игры Steam после /app/. Название не проверяется. Добавление не включает доступ или выбор игры. Метаданные можно разрешить отдельно; декодер прогресса нужен не для каждой операции.</p></section>' if csrf is not None else '')
    return f'<aside class="library" id="library"><div class="library-heading"><h1>Игры сервиса</h1><span>{len(catalog)} в каталоге</span></div>{content}{add_form}<p class="library-note">Добавленные игры, не библиотека твоего Steam. «Все текущие» не включает будущие добавления.</p><a class="plain-link community-link" href="https://github.com/sevakode/game-assist/blob/main/CONTRIBUTING.md" rel="noreferrer">Как добавить поддержку игры</a></aside>'


def games_review_body(csrf, catalog, catalog_revision='initial-three-v1'):
    entries = game_catalog({'catalog':catalog})
    planned = {g['appid']:g for g in entries}
    titles = {g['appid']:g['title'] for g in entries}
    rows = ''.join(f'<li><strong>{esc(title)}</strong>{"<small>Название задано пользователем; не проверено.</small>" if appid not in GAMES else ""}<span>{"Будет выбрана" if planned.get(appid, {}).get("selected") else "Не выбрана"}</span><small>{"Доступна только сводка из четырёх полей." if appid==4231820 else "Можно разрешить метаданные файла. Декодер прогресса недоступен."}</small></li>' for appid,title in titles.items())
    fields = ''.join(hidden(f'game_{appid}', 'yes') for appid in titles if planned.get(appid, {}).get('selected'))
    metadata_controls = ''.join(f'<label class="check"><input type="checkbox" name="metadata_{appid}" value="yes" {"checked" if planned[appid].get("metadata_authorized") or "saves.metadata" in planned[appid].get("scopes", []) else ""}><span>Метаданные: {esc(titles[appid])}<small>Только размер файла и время изменения. Без пути, имени, содержимого и прогресса.</small></span></label>' for appid in titles if planned[appid].get('selected'))
    belmont = planned.get(4231820, {})
    permission = (f'<label class="check"><input type="checkbox" name="summary_4231820" value="yes" {"checked" if belmont.get("authorized") else ""}><span>Разрешить сводку Belmont’s Curse<small>Только текущие здоровье, мана и два сырых счётчика фрагментов. Не максимумы и не полное прохождение.</small></span></label>' if belmont.get('selected') else '<p class="small-text">Belmont’s Curse не выбрана: разрешение на её сводку будет отключено.</p>')
    return f'<div class="form-page"><a class="back-link" href="/#library">Изменить выбор</a><h1>Проверка выбранных игр</h1><p class="intro">Только перечисленные здесь игры. Будущие добавления не включаются. Выбор не подтверждает владение игрой и сам по себе не разрешает чтение данных.</p><ul class="game-review">{rows}</ul><form method="post" action="/account/games">{hidden("csrf",csrf)}{hidden("action","confirm")}{hidden("catalog_revision",catalog_revision)}{fields}<fieldset class="review-permissions"><legend>Разрешения на данные</legend>{metadata_controls}{permission}<p class="small-text">Локальный компаньон читает только явно выбранный файл без изменений. На сервер уйдут лишь отмеченные здесь сведения, не содержимое сейва. Достижения, карта и Steam Cloud недоступны.</p></fieldset><p class="capability-note">Снятие выбора отключит доступ этой игры и удалит её серверные сводки и уведомления. Локальные сохранения не меняются.</p><div class="action-row"><button class="primary">Сохранить игры и разрешения</button><a class="plain-link" href="/#library">Отмена</a></div></form></div>'


def selected_header(appid=4231820, title=None):
    return f'<header class="game-heading" id="selected-game"><p>Открыта игра</p><h2>{esc(title or GAMES.get(appid, f"Steam AppID {appid}"))}</h2></header><nav class="section-nav" aria-label="Разделы игры"><a href="#context">Сводка</a><a href="#permissions">Доступ</a><a href="#assistant">Помощник</a></nav>'


def game_permissions(game, csrf):
    appid = game['appid']
    scopes = game.get('scopes', [])
    selected = bool(game.get('selected'))
    forms = []
    if selected:
        for scope, label in [('saves.metadata', 'метаданные файла')] + ([('saves.summary','сводку из 4 полей')] if appid==4231820 else []):
            granted = scope in scopes
            forms.append(f'<form method="post" action="/account/games/permissions">{hidden("csrf",csrf)}{hidden("appid",appid)}{hidden("scope",scope)}{hidden("enabled","no" if granted else "yes")}<button class="secondary">{"Отключить" if granted else "Разрешить"} {label}</button></form>')
        control = ''.join(forms)
    else:
        control = '<p class="small-text">Сначала выбери игру и сохрани выбор в разделе «Игры сервиса».</p>'
    summary_note = ('Для Belmont’s Curse дополнительно доступна сводка: текущие здоровье, мана и два сырых счётчика фрагментов. Не максимумы и не процент прохождения.' if appid==4231820 else 'Декодер прогресса этой игры пока недоступен. Метаданные не позволяют определить прохождение или достижения.')
    revoke = (f'<details class="revoke-confirm"><summary>Отозвать доступ этой игры</summary><p class="small-text">Отключит доступ и удалит серверные данные только этой игры.</p><form method="post" action="/account/games/revoke">{hidden("csrf",csrf)}{hidden("appid",appid)}<button class="danger">Отозвать доступ игры</button></form></details>' if selected or scopes else '')
    return f'<section class="utility-section" id="permissions"><div class="section-title"><h3>Доступ к этой игре</h3><span class="status-text">{"Есть разрешения" if scopes else "Не разрешён"}</span></div><p>Метаданные выбранного сейва — только размер и время изменения. Без имени, пути, хеша и содержимого файла.</p><p class="small-text">{summary_note}</p><div class="action-row">{control}</div><p class="small-text">Разрешение не означает, что устройство подключено или данные уже получены. Файл читается локально, без изменений.</p>{revoke}</section>'


def metadata_panel(game):
    metadata = (game or {}).get('metadata')
    if not metadata:
        return '<section class="metadata-panel"><h4>Метаданные выбранного сейва</h4><p class="small-text">Ещё не получены. Нужны отдельное разрешение и подключённый компаньон с выбранным файлом.</p></section>'
    size = metadata.get('size_bytes')
    modified = metadata.get('modified_ns')
    size_text = f'{size:,} байт'.replace(',', ' ') if type(size) is int and size>=0 else 'Неизвестно'
    modified_text = timestamp(modified/1_000_000_000) if type(modified) is int and modified>=0 else 'Время неизвестно'
    return f'<section class="metadata-panel"><h4>Метаданные выбранного сейва</h4><dl class="file-metadata"><div><dt>Размер файла</dt><dd>{esc(size_text)}</dd></div><div><dt>Изменён по данным устройства</dt><dd>{esc(modified_text)}</dd></div></dl><p class="small-text">Это сведения о файле, не расшифрованный прогресс. Содержимое, имя и путь не передаются.</p></section>'


def cloud_notice():
    return '<p class="capability-note"><strong>Steam Cloud недоступен.</strong> Метаданные и доступные сводки поступают от отдельно подключённого Deck. Его установка необязательна.</p>'


def landing_body(selected_appid=None):
    active = focus_id(selected_appid)
    context_copy = 'Войди, чтобы управлять доступом к игровым данным.' if active == 4231820 else 'Декодер этой игры пока недоступен. Можно отдельно разрешить метаданные сейва: размер и время изменения, без содержимого.'
    device_actions = '<div class="action-row"><a class="button secondary" href="/setup">Настройка Deck</a><a class="plain-link" href="/devices/approve">У меня есть код</a></div>' if active == 4231820 else ''
    return f'''<div class="account-strip"><div><strong>Аккаунт не подключён</strong><p>Вход и разрешения через Steam.</p></div><a class="button primary" href="/login">Войти через Steam</a></div><div class="console-layout">{library('Нет данных аккаунта', active)}<div class="workspace">{selected_header(active)}<section class="context-section" id="context"><div class="section-title"><h3>Сводка игры</h3><span class="status-text">Нет данных</span></div><div class="empty-context"><div class="save-icon" aria-hidden="true"></div><div><h4>Пока без сводки</h4><p>{context_copy}</p><p class="small-text">Пароль вводится только на сайте Steam.</p></div></div>{cloud_notice()}{device_actions}</section><section class="utility-section" id="permissions"><h3>Доступ к играм</h3><p>После входа можно добавлять игры по Steam AppID, выбирать одну, несколько или все текущие и проверять разрешения для каждой. Для Elden Ring и The Witcher 3 доступны метаданные, но расшифровка прогресса пока недоступна.</p><a class="plain-link" href="/login">Выбрать игры и разрешения</a></section><section class="utility-section" id="assistant"><div class="section-title"><h3>Помощник</h3><span class="status-text">Подключается отдельно</span></div><p>Здесь нет чата. Можно обсуждать игру в своём ChatGPT или Claude и без компаньона. Для передачи сводки подключи помощника после входа.</p></section><section class="utility-section" id="updates"><div class="section-title"><h3>Обновления</h3><span class="status-text">Не включены</span></div><p>Изменения сводки можно получать на этой странице после подключения устройства. Не push-уведомления.</p></section></div></div>'''


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
    catalog = game_catalog(capabilities)
    active = focus_id(capabilities.get('selected_appid'), [g['appid'] for g in catalog])
    current = next(g for g in catalog if g['appid'] == active)
    game = next((g for g in projection.get('games', []) if g.get('appid') == active), None)
    summary = game.get('summary') if game and active == 4231820 else None
    status = 'Сводка от устройства' if summary else 'Сводки пока нет'
    if summary:
        scalars = summary.get('player_scalars', {})
        metrics = ''.join(f'<div class="metric"><dt>{label}</dt><dd>{esc(scalar_text(scalars.get(key)))}</dd></div>' for key, label in [('currentHealth','Текущее здоровье'),('currentMana','Текущая мана'),('healthUpgradeFragmentCount','Фрагменты здоровья'),('manaUpgradeFragmentCount','Фрагменты маны')])
        progress = f'''<dl class="metrics">{metrics}</dl><p class="small-text received">Получено: {esc(timestamp(game.get('summary_received_at', game.get('received_at'))))}</p><details class="data-details"><summary>Что означают эти значения</summary><p>Это переданные значения, не независимая проверка игры. Время самого сохранения неизвестно. Здоровье и мана — не максимумы; смысл счётчиков фрагментов не подтверждён. Карта, процент прохождения и достижения по ним не определяются.</p></details>'''
    else:
        progress = '<div class="empty-context"><div class="save-icon" aria-hidden="true"></div><div><h4>Пока без сводки</h4><p>Нет разрешённой сводки от устройства. Можно подключить Deck или пользоваться помощником без него.</p></div></div>'
    if active != 4231820:
        status = 'Декодер недоступен'
        progress = '<div class="empty-context"><div><h4>Прогресс пока не расшифровывается</h4><p>Для этой игры нет проверенного декодера. Метаданные файла можно подключить отдельно; они не раскрывают прохождение, достижения или карту.</p></div></div>'
    inbox = (inbox or {'enabled': False, 'items': []}) if active == 4231820 else {'enabled':False, 'items':[]}
    device_actions = '<div class="action-row"><a class="button primary" href="/devices/approve">Подключить по коду</a><a class="plain-link" href="/setup">Настройка Deck</a></div>'
    enabled = bool(inbox.get('enabled'))
    updates = ''.join(f'<li><div><p>{esc(item.get("message", "Новая сводка устройства"))}</p><time class="small-text">{esc(timestamp(item.get("created_at")))}</time></div>' + (f'<form method="post" action="/account/notifications/read">{hidden("csrf", csrf)}{hidden("notification_id", item.get("id", ""))}<button class="secondary compact">Прочитано</button></form>' if not item.get('read') else '<span class="status-text">Прочитано</span>') + '</li>' for item in inbox.get('items', []))
    updates = f'<ul class="inbox-list">{updates}</ul>' if updates else '<p class="empty-inbox">Пока нет уведомлений.</p>'
    control = (f'<form class="notification-control" method="post" action="/account/notifications">{hidden("csrf", csrf)}{hidden("appid", "4231820")}{hidden("enabled", "no" if enabled else "yes")}<button class="secondary">{"Выключить обновления" if enabled else "Включить обновления"}</button></form>' if enabled or inbox.get('can_enable') else '<p class="small-text">Для включения нужен компаньон и разрешение на чтение сводки.</p>')
    if active != 4231820:
        control = '<p class="small-text">Обновления для этой игры недоступны: декодер не реализован.</p>'
    return f'''<div class="account-strip signed-in"><div><strong>Steam подключён</strong><p>Разрешения можно изменить в настройках доступа.</p></div><a class="plain-link" href="#library">Выбрать игры и доступ</a></div><div class="console-layout">{library(status, active, catalog, csrf)}<div class="workspace">{selected_header(active, current["title"])}<section class="context-section" id="context"><div class="section-title"><h3>Сводка игры</h3><span class="status-text">{esc(status)}</span></div>{progress}{metadata_panel(game)}{cloud_notice()}{device_actions}</section>{game_permissions(current, csrf)}<section class="utility-section" id="updates"><div class="section-title"><h3>Обновления</h3><span class="status-text">{'Включены' if enabled else 'Выключены'}</span></div>{updates}{control}<p class="small-text">Только на сайте, не push. Новые уведомления появляются при изменениях разрешённой сводки.</p></section><section class="utility-section" id="assistant"><div class="section-title"><h3>Помощник</h3><span class="status-text">Через MCP</span></div><p>Здесь нет чата. ChatGPT или Claude могут читать разрешённые сводки и метаданные после отдельного OAuth-согласия.</p>{connection_panel(capabilities.get('mcp_url'))}</section><details class="utility-section account" id="account"><summary>Настройки доступа</summary><p>Доступ устройств и помощников можно отозвать. Сохранения на Deck останутся без изменений.</p><div class="account-actions"><form method="post" action="/logout">{hidden('csrf',csrf)}<button class="secondary">Выйти из аккаунта</button></form><details class="revoke-confirm"><summary>Отозвать весь доступ</summary><p>Это отключит устройства и помощников и удалит сводки с сервера.</p><form method="post" action="/account/revoke">{hidden('csrf',csrf)}<button class="danger">Отозвать весь доступ</button></form></details></div></details></div></div>'''


def device_body(csrf, catalog=None, requested=None):
    games = game_catalog({'catalog':catalog or []})
    selected = [g for g in games if g.get('selected')] if catalog is not None else games[:1]
    request_appid = requested.get('appid') if isinstance(requested, dict) else None
    options = ''.join(f'<option value="{g["appid"]}" {"selected" if request_appid==g["appid"] else ""}>{esc(g["title"])}</option>' for g in selected)
    request_note = f'<p class="capability-note">Устройство запрашивает AppID {esc(request_appid)}. Проверь совпадение с игрой на Deck.</p>' if request_appid else ''
    empty_note = '<p class="capability-note">Сначала выбери игры на главной и сохрани выбор.</p>' if not selected else ''
    summary_option = ('<label class="check"><input type="checkbox" name="saves.summary" value="yes"><span>Сводка Belmont’s Curse<small>Только для AppID 4231820: текущие здоровье, мана и два счётчика фрагментов. Для другой игры не отмечай.</small></span></label>' if any(g['appid']==4231820 for g in selected) and request_appid in (None,4231820) else '<p class="small-text">Сводка прогресса для этой игры недоступна; можно передать только метаданные.</p>')
    return f'<div class="form-page"><a class="back-link" href="/">К играм</a><h1>Подключение Deck</h1><p class="intro">Введи код, показанный на твоём Steam Deck. Не подтверждай код, присланный другим человеком.</p>{request_note}{empty_note}<form class="form-stack" method="post">{hidden("csrf",csrf)}<label for="device-code">Код устройства</label><input id="device-code" class="code-input" name="user_code" minlength="8" maxlength="8" pattern="[A-Fa-f0-9]{{8}}" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="A1B2C3D4" required><label for="game-select">Игра</label><select id="game-select" name="appid" required><option value="">Выбери игру с экрана Deck</option>{options}</select><fieldset><legend>Что разрешено передавать</legend><label class="check"><input type="checkbox" name="saves.metadata" value="yes"><span>Метаданные выбранного сейва<small>Только размер файла и время изменения. Без имени, пути, хеша и содержимого.</small></span></label>{summary_option}</fieldset><p class="small-text">Выбери разрешения, совпадающие с запросом на Deck. Доступ помощника подтверждается отдельно. Компаньон не изменяет файл; содержимое сейва на сервер не отправляется.</p><div class="action-row"><button class="primary">Подключить устройство</button><a class="plain-link" href="/">Отмена</a></div></form></div>'


def consent_body(csrf, req, client_label):
    return f'''<div class="form-page"><a class="back-link" href="/">К играм</a><h1>Доступ помощника</h1><p class="intro">Разрешить этому клиенту читать игровые сводки и метаданные?</p><div class="client-label"><strong>Клиент и адрес возврата</strong><p>{esc(client_label)}</p></div><ul class="permission-list"><li>Только разрешённые тобой сводки и метаданные.</li><li>Без сырых сохранений и Steam ID.</li><li>Переданные факты покинут Game Assist.</li></ul><p class="small-text">Доступ можно отозвать в настройках на главной.</p><form method="post">{hidden('csrf',csrf)}{hidden('request',req)}<div class="action-row"><button class="primary">Разрешить чтение данных</button><a class="plain-link" href="/">Не подключать</a></div></form></div>'''


def approved_body():
    return '<div class="form-page"><h1>Устройство одобрено</h1><p class="intro">Вернись на Steam Deck, чтобы завершить настройку.</p><p>Доступ можно отозвать в настройках на главной.</p><div class="action-row"><a class="button primary" href="/">К играм</a></div></div>'


def setup_body(issuer, checksum, command=None):
    intro = '<div class="form-page setup"><a class="back-link" href="/">К играм</a><h1>Компаньон для Deck</h1><p class="intro">Необязательная утилита для передачи разрешённых метаданных и доступной сводки. Можно пользоваться помощником и без установки.</p><p class="capability-note">Steam Cloud недоступен. Компаньон читает выбранный файл на твоём устройстве, не изменяя его.</p>'
    if not checksum:
        return intro + '<section class="setup-section"><h2>Загрузка пока недоступна</h2><p>Архив компаньона ещё не собран. Установить его с этого сервиса пока нельзя.</p><a class="plain-link" href="/">Вернуться к играм</a></section></div>'
    return intro + f'''<section class="setup-section"><h2>Открыть на Steam Deck</h2><p>Переключись в Desktop Mode и открой <code>{esc(issuer+'/setup')}</code>. Вход в ChatGPT на Deck не нужен.</p><details><summary>Проверить требования</summary><p>Нужны Python 3.10+, модуль venv и активная сессия systemctl --user. Если их нет — остановись: не используй sudo и не отключай защиту SteamOS.</p></details></section><section class="setup-section"><h2>Скачать и проверить</h2><p>Сохрани архив как deck-companion.zip в Downloads. В нём исходный код стандартной библиотеки, без pip-пакетов и готовых бинарных файлов.</p><div class="action-row"><a class="button primary" href="/downloads/deck-companion.zip">Скачать ZIP</a><a class="plain-link" href="/downloads/deck-companion.zip.sha256">Файл SHA256</a></div><details><summary>Команды проверки и установки</summary><p>Изучи исходники и команды. Ничего не запускается автоматически. В Konsole сначала проверь контрольную сумму; продолжай только после OK.</p><pre>{esc(command or '')}</pre><p class="small-text">SHA256: <code>{esc(checksum)}</code></p></details></section><section class="setup-section"><h2>Подключить устройство</h2><p>Выбери путь к сохранению. На телефоне войди через Steam по адресу сопряжения и сравни код с кодом на своём Deck. Выбери ту же игру и разрешения, что указаны на Deck. Для любой добавленной игры доступны метаданные файла; сводка из четырёх полей — только для Belmont’s Curse (4231820).</p><div class="action-row"><a class="button secondary" href="/devices/approve">Ввести код устройства</a></div><details><summary>Фоновая работа и ограничения</summary><p>Установка спросит разрешение перед включением фоновой службы. Сохранения не изменяются. Сопряжение действует 30 дней.</p><p>Работа в Gaming Mode ещё требует проверки на реальном Deck. Бесплатный хостинг может просыпаться около минуты. Помощник подключается отдельно через OAuth.</p></details></section></div>'''
