"""Public-only discovery contracts; no live clients, crawlers, or Steam calls."""
import json
import socket
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from starlette.applications import Starlette
from starlette.testclient import TestClient

from remote_server import discovery as d

ORIGIN = 'https://self-host.example:8443'


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.structured = []
        self.in_json = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'script':
            self.in_json = attrs.get('type') == 'application/ld+json'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_json = False

    def handle_data(self, data):
        if self.in_json:
            self.structured.append(json.loads(data))


class PublicDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(Starlette(routes=d.public_routes(issuer=ORIGIN)), base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def test_factory_owns_only_four_public_get_routes(self):
        routes = d.public_routes(issuer=ORIGIN)
        self.assertEqual({r.path for r in routes}, {'/connect', '/robots.txt', '/sitemap.xml', '/llms.txt'})
        for route in routes:
            self.assertEqual(route.methods, {'GET', 'HEAD'})
            self.assertEqual(self.client.post(route.path).status_code, 405)
            self.assertEqual(self.client.head(route.path).content, b'')

    def test_requests_cannot_change_public_content_or_canonical(self):
        for path in ('/connect', '/robots.txt', '/sitemap.xml', '/llms.txt'):
            original = self.client.get(path)
            for agent in ('Mozilla/5.0', 'Googlebot', 'OAI-SearchBot', 'GPTBot'):
                response = self.client.get(path + '?token=SYNTHETIC_PRIVATE_VALUE', headers={
                    'host': 'untrusted.invalid', 'x-forwarded-host': 'untrusted.invalid',
                    'forwarded': 'host=untrusted.invalid;proto=http', 'user-agent': agent,
                    'cookie': 'session=SYNTHETIC_PRIVATE_VALUE'})
                self.assertEqual(response.content, original.content)
                self.assertNotIn('set-cookie', response.headers)
                self.assertNotIn('untrusted.invalid', response.text)
                self.assertNotIn('SYNTHETIC_PRIVATE_VALUE', response.text)
                self.assertNotIn('game-assist.onrender.com', response.text)
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_sitemap_is_exact_public_allowlist(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.headers['content-type'], 'application/xml')
        tree = ElementTree.fromstring(response.content)
        ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
        urls = [node.text for node in tree.findall(f'{ns}url/{ns}loc')]
        self.assertEqual(urls, [ORIGIN + p for p in ('/', '/connect', '/connect/claude', '/setup')])
        self.assertNotIn('lastmod', response.text)
        self.assertTrue(all('?' not in url and '#' not in url for url in urls))

    def test_robots_allows_public_content_and_blocks_private_prefixes(self):
        response = self.client.get('/robots.txt')
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        self.assertEqual(parser.site_maps(), [ORIGIN + '/sitemap.xml'])
        for agent in ('Googlebot', 'Bingbot', 'OAI-SearchBot', 'GPTBot', '*'):
            for path in (*d.PUBLIC_PAGES, '/assets/console.css', '/llms.txt'):
                self.assertTrue(parser.can_fetch(agent, ORIGIN + path), (agent, path))
            for path in d.PRIVATE_PREFIXES:
                self.assertFalse(parser.can_fetch(agent, ORIGIN + path))

    def test_metadata_is_closed_and_json_is_parseable(self):
        for path in d.PUBLIC_PAGES:
            doc = Document(d.public_head(ORIGIN, path))
            canonical = [a['href'] for t, a in doc.tags if t == 'link' and a.get('rel') == 'canonical']
            self.assertEqual(canonical, [ORIGIN + path])
            self.assertEqual(doc.structured[0]['url'], ORIGIN + path)
            self.assertEqual(doc.structured[0]['description'], d.PUBLIC_PAGES[path][1])
            self.assertNotIn('aggregateRating', json.dumps(doc.structured))
        for path in ('/account', '/games', '/?game=1', '/connect?token=secret', '//evil.example'):
            with self.assertRaises(KeyError):
                d.public_head(ORIGIN, path)

    def test_html_and_json_context_escaping(self):
        text = 'Test "quotes" & <tag> </script> \u2028'
        with patch.dict(d.PUBLIC_PAGES, {'/connect': (text, text)}):
            response = d.connect_page(ORIGIN)
            doc = Document(response.body.decode())
            self.assertEqual(doc.structured[0]['description'], text)
            self.assertEqual(sum(t == 'script' for t, _ in doc.tags), 1)
            description = [a['content'] for t, a in doc.tags if t == 'meta' and a.get('name') == 'description']
            self.assertEqual(description, [text])
            self.assertNotIn(b'<tag>', response.body)
        self.assertNotIn('<', d.json_ld({'value': text}))

    def test_invalid_issuers_fail_closed(self):
        for issuer in ('', 'http://example.com', 'https://example.com/', 'https://example.com/path',
                       'https://example.com?token=x', 'https://example.com#x', 'https://u:p@example.com',
                       'https://*.example.com', 'https://example.com\n', 'https://example.com:0',
                       'https://example.com:99999', 'https://example.com:', 'https://evil<script>.com',
                       'https://example.com\\other', 'https://-bad.example', 'https://x..example'):
            with self.subTest(issuer=issuer), self.assertRaises(ValueError):
                d.public_routes(issuer=issuer)
        self.assertIn('https://[::1]:8443/connect', d.public_head('https://[::1]:8443', '/connect'))

    def test_hub_and_llms_share_limits_without_install_promises(self):
        hub = self.client.get('/connect').text
        llms = self.client.get('/llms.txt').text
        self.assertIn('href="/connect/claude"', hub)
        self.assertEqual(sum(t == 'h1' for t, _ in Document(hub).tags), 1)
        self.assertFalse(any(t in ('form', 'iframe') for t, _ in Document(hub).tags))
        for body in (hub, llms):
            for fact in ('ChatGPT', 'Streamable HTTP', 'S256', 'DCR', 'Steam Cloud',
                         '1.1.3', 'Elden Ring', 'The Witcher 3', 'последней активности не реализовано'):
                self.assertIn(fact, body)
            self.assertIn(d.DESCRIPTION, body)
            self.assertNotIn('auth_callback', body)
        self.assertIn('не является стандартом OAuth', llms)

    def test_rendering_and_serving_do_not_make_network_calls(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('external network forbidden')):
            routes = d.public_routes(issuer=ORIGIN)
            with TestClient(Starlette(routes=routes)) as client:
                for route in routes:
                    self.assertEqual(client.get(route.path).status_code, 200)

    def test_mounted_routes_retain_existing_security_and_metadata(self):
        from remote_server.app import Config, create_app
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Config(ORIGIN, str(Path(directory) / 'test.sqlite'), ('https://client.example/callback',)))
            app.routes.extend(d.public_routes(issuer=ORIGIN))
            with TestClient(app, base_url=ORIGIN) as client:
                response = client.get('/connect')
                self.assertEqual(response.status_code, 200)
                self.assertIn("default-src 'none'", response.headers['content-security-policy'])
                self.assertNotIn('unsafe-inline', response.headers['content-security-policy'])
                self.assertEqual(client.get('/connect', headers={'host': 'evil.invalid'}).status_code, 400)
                self.assertEqual(client.get('/mcp').status_code, 401)
                metadata = client.get('/.well-known/oauth-authorization-server').json()
                self.assertEqual(metadata['issuer'], ORIGIN + '/')
                self.assertEqual(client.post('/account/library/refresh').status_code, 401)
