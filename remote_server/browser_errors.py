"""Fixed, non-sensitive recovery screens for ordinary browser navigations.

Protocol clients keep their original errors. Neither submitted form values nor
exception details are reflected. Recovery URLs are fixed or application-owned.
"""
from starlette.responses import PlainTextResponse
from . import ui

BROWSER_PATHS = frozenset({
    '/', '/setup', '/import', '/login', '/steam/callback', '/devices/approve',
    '/oauth/consent', '/account/games', '/account/games/add',
    '/account/games/permissions', '/account/games/revoke',
    '/account/achievements/refresh', '/account/library/permission', '/account/library/refresh', '/account/notifications',
    '/account/notifications/read', '/account/revoke', '/logout',
})


def wants_browser_error(request):
    # Fetch/API callers do not receive a document simply because their URL is shared.
    if request.url.path not in BROWSER_PATHS:
        return False
    for part in request.headers.get('accept', '').split(','):
        fields = [field.strip().lower() for field in part.split(';')]
        if fields[0] != 'text/html':
            continue
        quality = [field[2:] for field in fields[1:] if field.startswith('q=')]
        try:
            if len(quality) <= 1 and (not quality or 0 < float(quality[0]) <= 1):
                return True
        except ValueError:
            pass
    return False


def error_page(request, status):
    titles = {400: 'Не удалось завершить действие', 401: 'Нужно войти снова',
              403: 'Проверь доступ', 404: 'Игра или страница недоступна',
              409: 'Данные изменились', 413: 'Слишком большой запрос', 414: 'Слишком длинная ссылка',
              422: 'Проверь введённые данные', 429: 'Нужно немного подождать',
              503: 'Возможность пока недоступна'}
    title = titles.get(status, 'Действие не завершено')
    detail = 'Вернись к игре и попробуй ещё раз. Сохранения на устройстве не изменяются.'
    target, label = '/#library', 'К играм'
    path = request.url.path
    if status == 401:
        detail = 'Сеанс завершился. Войди через Steam и повторно проверь выбранную игру и разрешения.'
        target, label = '/login', 'Войти через Steam'
    elif path in ('/login', '/steam/callback'):
        detail = 'Вход не завершён или ссылка устарела. Начни вход заново; пароль вводится только на сайте Steam.'
        target, label = '/login', 'Начать вход заново'
    elif status == 403:
        detail = 'Сеанс, выбранная игра или разрешение изменились. Открой игру заново и проверь доступ перед повтором.'
    elif status == 409:
        detail = 'Список игр или разрешения изменились, пока страница была открыта. Проверь актуальный выбор заново.'
    elif status == 429:
        detail = 'Достигнут временный лимит. Подожди перед повтором. Достижения обновляются не чаще одного раза в 15 минут.'
    elif status == 503:
        detail = 'Эта возможность сейчас не настроена или временно недоступна. Остальные разделы можно использовать.'
    elif path == '/devices/approve':
        detail = 'Проверь код, игру и разрешения на экране своего Deck. Если код истёк, начни подключение заново на устройстве.'
        target, label = '/devices/approve', 'Ввести код заново'
    elif path == '/account/games/add':
        detail = 'Укажи положительный Steam AppID до 2147483647 и обычное название не длиннее 120 символов.'
    if status != 401 and path not in ('/login', '/steam/callback', '/devices/approve'):
        target = getattr(request.state, 'browser_return', target)
    response = ui.page(title, f'<div class="form-page"><h1>{ui.esc(title)}</h1><p class="intro">{ui.esc(detail)}</p><p class="small-text">Код ответа: {status}</p><div class="action-row"><a class="button primary" href="{ui.esc(target)}">{ui.esc(label)}</a><a class="plain-link" href="/">На главную</a></div></div>')
    response.status_code = status
    return response


async def http_exception(request, exc):
    if wants_browser_error(request):
        response = error_page(request, exc.status_code)
        # Preserve protocol timing/challenge headers but never copy a redirect.
        for key, value in (exc.headers or {}).items():
            if key.lower() in ('retry-after', 'www-authenticate'):
                response.headers[key] = value
        return response
    if exc.status_code in (204, 304):
        return PlainTextResponse(status_code=exc.status_code, headers=exc.headers)
    return PlainTextResponse(exc.detail, status_code=exc.status_code, headers=exc.headers)
