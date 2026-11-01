"""Static public discovery only. No account, transport, or OAuth configuration changes."""
import ipaddress
import json
import re
from html import escape
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

DESCRIPTION = 'Game Assist — экспериментальный игровой компаньон с открытым кодом для совместимых AI-клиентов и разрешённых сводок сохранений.'
PUBLIC_PAGES = {
    '/': ('Game Assist — игровой компаньон', DESCRIPTION),
    '/connect': ('Подключить AI · Game Assist', DESCRIPTION),
    '/connect/claude': ('Подключить Claude · Game Assist', 'Инструкция подключения Game Assist к Claude через удалённый MCP. Реальный пользовательский OAuth ещё требует проверки.'),
    '/setup': ('Настройка Steam Deck · Game Assist', 'Настройка локального компаньона Game Assist для передачи разрешённой сводки выбранного сохранения. Проверка на реальном Steam Deck ещё требуется.'),
}
PRIVATE_PREFIXES = ('/games', '/import', '/account', '/oauth', '/authorize', '/token',
                    '/register', '/revoke', '/login', '/logout', '/steam', '/devices',
                    '/v1', '/mcp', '/healthz', '/downloads')
NOINDEX_HEAD = '<meta name="robots" content="noindex, nofollow">'


def trusted_origin(issuer: str) -> str:
    """Accept an explicitly configured HTTPS origin, never a request-derived URL."""
    if not isinstance(issuer, str) or not re.fullmatch(r'https://[A-Za-z0-9.\-\[\]:]+', issuer):
        raise ValueError('Explicit HTTPS issuer origin required')
    parsed = urlsplit(issuer)
    host = parsed.hostname
    if not host or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Issuer must be an origin without credentials or path')
    if ':' in host:
        ipaddress.IPv6Address(host)
    elif not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                 for label in host.split('.')):
        raise ValueError('Invalid issuer hostname')
    if parsed.netloc.endswith(':') or (parsed.port is not None and not 1 <= parsed.port <= 65535):
        raise ValueError('Invalid issuer port')
    return issuer


def json_ld(value: dict) -> str:
    """JSON inside a script data block, escaped for the HTML raw-text context."""
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':'))
            .replace('&', r'\u0026').replace('<', r'\u003c').replace('>', r'\u003e'))


def public_metadata(issuer: str, path: str) -> dict:
    origin = trusted_origin(issuer)
    title, description = PUBLIC_PAGES[path]  # Closed list: no account URLs or queries.
    url = origin + path
    structured = {'@context': 'https://schema.org', '@type': 'WebPage',
                  'name': title, 'description': description, 'url': url,
                  'inLanguage': 'ru', 'isPartOf': {'@type': 'WebSite', 'name': 'Game Assist', 'url': origin + '/'}}
    return {'title': title, 'description': description, 'canonical': url, 'structured_data': structured}


def public_head(issuer: str, path: str) -> str:
    """Additional head tags only: the existing page renderer still owns <title>."""
    data = public_metadata(issuer, path)
    esc = lambda value: escape(value, quote=True)
    return (f'<meta name="description" content="{esc(data["description"])}">'
            f'<link rel="canonical" href="{esc(data["canonical"])}">'
            '<meta property="og:type" content="website">'
            '<meta property="og:site_name" content="Game Assist">'
            '<meta property="og:locale" content="ru_RU">'
            f'<meta property="og:title" content="{esc(data["title"])}">'
            f'<meta property="og:description" content="{esc(data["description"])}">'
            f'<meta property="og:url" content="{esc(data["canonical"])}">'
            f'<script type="application/ld+json">{json_ld(data["structured_data"])}</script>')


def connect_body(issuer: str) -> str:
    endpoint = escape(trusted_origin(issuer) + '/mcp', quote=True)
    return f'''<div class="form-page"><a class="back-link" href="/">На главную</a>
<h1>Подключить AI</h1><p class="intro">{escape(DESCRIPTION)}</p>
<p>Ссылкой на эту страницу можно поделиться в чате. Для чтения твоих данных нужны поддержка коннекторов, подключение сервера и отдельное разрешение.</p>
<section class="utility-section"><h2>Claude</h2><p>Есть инструкция подключения. Реальный пользовательский OAuth ещё требует проверки.</p><a class="button primary" href="/connect/claude">Подключить Claude</a></section>
<section class="utility-section"><h2>ChatGPT</h2><p>Подключение Game Assist ещё не настроено и не проверено. Нужны поддерживаемый режим подключения и настройка приложения оператором.</p></section>
<section class="utility-section"><h2>Другие MCP-клиенты</h2><p>Нужна поддержка Streamable HTTP и OAuth с автоматической регистрацией (DCR) и PKCE S256. Оператор должен разрешить точный адрес возврата выбранного клиента. Совместимость проверяется отдельно.</p><p>Адрес MCP: <code>{endpoint}</code></p></section>
<section class="utility-section"><h2>AI без коннекторов</h2><p>Если AI умеет открывать ссылки, она может прочитать публичное описание. Приватные сохранения и автоматические инструменты по одной ссылке недоступны.</p></section>
<details><summary>Какие данные доступны</summary><p>Вход через Steam подтверждает личность, но не открывает Steam Cloud. Для сводки нужен ручной импорт или локальный компаньон с твоим разрешением.</p>
<p>Belmont’s Curse, формат 1.1.3: только текущие здоровье, мана и два сырых счётчика фрагментов. Это не максимумы, не карта и не полное прохождение. Декодеров прогресса Elden Ring и The Witcher 3 пока нет; наличие игры в каталоге не означает поддержку её сейва.</p>
<p>Библиотека Steam и достижения требуют отдельной настройки API оператором и разрешений игрока. Автоматическое определение текущей игры по последней активности не реализовано.</p>
<p>Исходные сохранения не изменяются. Фильтрация сводки ограничивает спойлеры, но поведение внешней AI не гарантируется.</p><a href="/setup">Настройка Steam Deck</a></details>
<p><a href="https://github.com/sevakode/game-assist">Исходный код</a> · MIT · экспериментальная beta</p></div>'''


def connect_page(issuer: str) -> HTMLResponse:
    meta = public_metadata(issuer, '/connect')
    return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>{escape(meta['title'])}</title>{public_head(issuer, '/connect')}<link rel="stylesheet" href="/assets/console.css"></head><body><a class="skip" href="#main">К содержимому</a><div class="shell"><header class="topbar"><a class="brand" href="/">Game Assist</a></header><main id="main">{connect_body(issuer)}</main><footer><a class="plain-link" href="/data-handling">Как обрабатываются данные</a></footer></div></body></html>''')


def robots_txt(issuer: str) -> str:
    origin = trusted_origin(issuer)
    return ('User-agent: *\n' + ''.join(f'Disallow: {path}\n' for path in PRIVATE_PREFIXES)
            + f'\nSitemap: {origin}/sitemap.xml\n')


def sitemap_xml(issuer: str) -> bytes:
    origin = trusted_origin(issuer)
    root = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    for path in PUBLIC_PAGES:
        SubElement(SubElement(root, 'url'), 'loc').text = origin + path
    return tostring(root, encoding='utf-8', xml_declaration=True)


def llms_txt(issuer: str) -> str:
    origin = trusted_origin(issuer)
    return f'''# Game Assist

> {DESCRIPTION}

Экспериментальная справка. llms.txt не является стандартом OAuth, способом установки коннектора или гарантией индексации и рекомендаций AI.

## Публичные страницы
- [Главная]({origin}/): краткое описание.
- [Подключить AI]({origin}/connect): клиенты, требования и ограничения.
- [Claude]({origin}/connect/claude): инструкция; реальный пользовательский OAuth ещё требует проверки.
- [Steam Deck]({origin}/setup): локальный компаньон; требуется проверка на реальном устройстве.
- [Исходный код](https://github.com/sevakode/game-assist): MIT, экспериментальная beta.

## Возможности и ограничения
Удалённый MCP: {origin}/mcp (Streamable HTTP; OAuth DCR и PKCE S256). Каждый клиент требует совместимости и разрешённого точного адреса возврата. ChatGPT ещё не настроен и не проверен. AI без коннекторов может читать публичное описание, но не приватные данные или автоматические инструменты.

Steam OpenID подтверждает личность, не открывает Steam Cloud. Для сводки нужен ручной импорт или локальный компаньон с разрешением игрока. Исходные сохранения не изменяются.

Belmont’s Curse 1.1.3: только текущие здоровье, мана и два сырых счётчика фрагментов; не максимумы, не карта и не полное прохождение. Декодеров прогресса Elden Ring и The Witcher 3 нет. Каталог игр не равен покрытию парсеров.

Библиотека Steam и достижения требуют отдельной настройки API оператором и разрешений игрока. Автоматическое определение текущей игры по последней активности не реализовано. Фильтрация сводки ограничивает спойлеры, но поведение внешней AI не гарантируется.
'''


def public_routes(*, issuer: str) -> list[Route]:
    """Add to the existing app, retaining its security middleware and OAuth routes.

    Request headers, cookies, query parameters, and user agents never affect output.
    All data is rendered at construction; no network or account access takes place.
    """
    origin = trusted_origin(issuer)
    pages = (
        ('/connect', connect_page(origin).body, 'text/html'),
        ('/robots.txt', robots_txt(origin), 'text/plain'),
        ('/sitemap.xml', sitemap_xml(origin), 'application/xml'),
        ('/llms.txt', llms_txt(origin), 'text/plain'),
    )
    def handler(body, media_type):
        async def serve(request):
            return Response(body, media_type=media_type, headers={'X-Content-Type-Options': 'nosniff'})
        return serve
    return [Route(path, handler(body, media_type), methods=['GET']) for path, body, media_type in pages]
