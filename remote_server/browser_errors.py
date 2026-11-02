"""Fixed, non-sensitive recovery screens for ordinary browser navigations.

Protocol clients keep their original errors. Neither submitted form values nor
exception details are reflected. Recovery URLs are fixed or application-owned.
"""
from starlette.responses import PlainTextResponse
from . import ui

BROWSER_PATHS = frozenset({
    '/', '/games', '/connect/claude', '/setup', '/import', '/login', '/steam/callback', '/devices/approve', '/devices/review',
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
    target, label = '/games#library', 'К играм'
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
        if path in ('/account/library/permission', '/account/library/refresh'):
            detail = 'Новый запрос списка игр не запущен: достигнут временный лимит. Обновление возможно не чаще одного раза в 15 минут; общий лимит может потребовать больше времени. Проверь текущий список и доступ.'
            if getattr(request.state, 'library_permission_saved', False):
                detail = 'Разрешение на чтение библиотеки было сохранено. ' + detail
    elif status == 503:
        detail = 'Эта возможность сейчас не настроена или временно недоступна. Остальные разделы можно использовать.'
    elif status == 400 and path == '/oauth/consent':
        title = 'Начни подключение заново из AI-клиента'
        detail = ('Этот запрос согласия недействителен: он мог истечь или уже быть использован. '
                  'Эта страница не подтверждает подключение. Вернись в AI-клиент и проверь его статус. '
                  'Если подключение не завершено, начни новую попытку оттуда. '
                  'Не обновляй старую страницу согласия и не отправляй её повторно. '
                  'Если переход из встроенного браузера не происходит, открой AI-клиент '
                  'в обычном браузере и начни новую попытку; не переноси старую ссылку возврата.')
        target, label = '/connect/claude', 'Инструкция подключения Claude'
    elif path in ('/devices/approve', '/devices/review'):
        detail = 'Подключение не подтверждено. Вернись к проверке запроса своего Deck. Если попытка истекла или уже использована, проверь состояние подключения на Deck перед новой попыткой.'
        if status == 422:
            detail = 'Игра или разрешения не прошли проверку. Подключение не подтверждено. Проверь, что игра добавлена в твой каталог, затем заново открой запрос устройства.'
        target, label = '/devices/approve', 'Ввести код заново'
    elif path == '/account/games/add':
        detail = 'Укажи положительный Steam AppID до 2147483647 и обычное название не длиннее 120 символов.'
    if status != 401 and path not in ('/login', '/steam/callback', '/devices/approve', '/devices/review'):
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
