"""Synthetic contracts for the standalone public document; no service/DB access."""
import ast
from html.parser import HTMLParser
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from remote_server import data_handling


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class DataHandlingTests(unittest.TestCase):
    def test_public_route_is_independent_of_request_identity(self):
        async def endpoint(request):
            return data_handling.data_handling_page()

        with TestClient(Starlette(routes=[Route('/data-handling', endpoint)])) as client:
            anonymous = client.get('/data-handling')
            supplied = client.get('/data-handling?owner=synthetic-owner&game=999',
                                  headers={'Cookie': 'session=synthetic-cookie',
                                           'Authorization': 'Bearer synthetic-token'})
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(anonymous.content, supplied.content)
        self.assertNotIn('set-cookie', anonymous.headers)
        self.assertNotIn('synthetic-', supplied.text)
        self.assertEqual(anonymous.headers['cache-control'], 'no-store')
        self.assertEqual(anonymous.headers['referrer-policy'], 'no-referrer')

    def test_renderer_has_no_request_config_or_storage_dependencies(self):
        self.assertEqual(len(inspect.signature(data_handling.data_handling_page).parameters), 0)
        tree = ast.parse(Path(data_handling.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {'html', 'starlette.responses'})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertEqual(calls, {'escape', '_section', 'HTMLResponse'})
        first = data_handling.data_handling_page()
        second = data_handling.data_handling_page()
        self.assertEqual(first.body, second.body)
        self.assertEqual(first.raw_headers, second.raw_headers)

    def test_all_editorial_text_is_escaped(self):
        marker = '<em data-example="quoted">A & B</em>'
        with patch.object(data_handling, 'TITLE', marker), \
             patch.object(data_handling, 'SECTIONS', ((marker, (marker,)),)), \
             patch.object(data_handling, 'RETENTION', ((marker, marker),)):
            source = data_handling.data_handling_page().body.decode()
        doc = Document(source)
        self.assertNotIn(marker, source)
        self.assertIn('&lt;em data-example=&quot;quoted&quot;&gt;', source)
        self.assertNotIn('em', [tag for tag, _ in doc.elements])
        self.assertEqual(''.join(doc.text).count(marker), 6)

    def test_document_has_no_active_controls_or_external_resources(self):
        doc = Document(data_handling.data_handling_page().body.decode())
        forbidden = {'script', 'form', 'input', 'iframe', 'img', 'object', 'embed'}
        self.assertFalse(forbidden.intersection(tag for tag, _ in doc.elements))
        for tag, attrs in doc.elements:
            self.assertFalse(any(key.startswith('on') for key in attrs))
            for key in ('href', 'src'):
                if key in attrs:
                    self.assertIn(attrs[key], {'/', '#main', '/assets/console.css',
                                              '/games', '/import', '/setup', '/connect/claude'})
        self.assertEqual(sum(tag == 'h1' for tag, _ in doc.elements), 1)
        self.assertTrue(any(tag == 'main' and attrs.get('id') == 'main'
                            for tag, attrs in doc.elements))

    def test_disclosures_cover_consent_retention_and_deletion_limits(self):
        text = ' '.join(Document(data_handling.data_handling_page().body.decode()).text)
        for required in ('SteamID', 'Steam Cloud', 'library.read', 'progress.read',
                         'по умолчанию выключен', 'currentHealth', 'currentMana',
                         'healthUpgradeFragmentCount', 'manaUpgradeFragmentCount',
                         '24 часа', '10 минут', '2 минуты', '30 дней', '31 день',
                         'Автоматического TTL нет', 'Ленивая очистка', '6 часов',
                         'не является полным удалением аккаунта',
                         'не удаляет уже переданные ответы', 'Virginia', 'aws-us-east-1',
                         'не подтверждены', 'не окончательная политика'):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_no_private_resource_ids_contacts_or_key_status_claim(self):
        source = data_handling.data_handling_page().body.decode()
        for forbidden in ('tiny-bar-', 'libfile_', 'file_000', 'SGC_STEAM_API_KEY',
                          'mailto:', 'ключ отсутствует', 'ключ настроен'):
            self.assertNotIn(forbidden, source)
        self.assertIn('не проверяет, настроен ли он сейчас', source)


if __name__ == '__main__':
    unittest.main()
