"""Presentation contract without editing global console CSS or transmitting data."""
from html.parser import HTMLParser
import unittest
from diagnostics.preview import preview_page, VALUES
from diagnostics.report import PROPERTIES

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags = []; self.options = []; self.option = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); self.tags.append((tag, attrs))
        if tag == 'option':
            self.option = [attrs.get('value'), '']; self.options.append(self.option)
    def handle_endtag(self, tag):
        if tag == 'option': self.option = None
    def handle_data(self, data):
        if self.option is not None: self.option[1] += data

class PreviewUITests(unittest.TestCase):
    def test_console_shell_navigation_and_mobile_semantics(self):
        source = preview_page(); doc = PageParser(); doc.feed(source)
        self.assertTrue(any(t == 'link' and a.get('href') == '/assets/console.css' for t,a in doc.tags))
        self.assertTrue(any(t == 'meta' and a.get('name') == 'color-scheme' and a.get('content') == 'dark' for t,a in doc.tags))
        self.assertIn('width=device-width', source)
        self.assertIn('system-nav', source)
        self.assertIn('Очистить поля', source); self.assertIn('Назад к играм', source); self.assertIn('Отмена', source)
        self.assertEqual(sum(t == 'details' and a.get('class') == 'utility-section'
                             for t,a in doc.tags), 2)
        self.assertEqual(sum(t == 'details' and a.get('class') == 'nav-advanced'
                             for t,a in doc.tags), 1)
        self.assertIn('<summary>Ещё</summary>', source)
        self.assertNotIn('>Устройство<', source)
        self.assertFalse(any(t == 'details' and 'open' in a for t,a in doc.tags))
        self.assertNotIn('<form', source); self.assertNotIn('Request ID', source)
        self.assertNotIn('X-Request-ID', source)
        self.assertIn('Отправка отчётов пока отключена', source)
        self.assertIn('class="action-row chooser-actions"', source)
        ids = [a.get('id') for t,a in doc.tags if t in ('input','select')]
        self.assertEqual(set(ids), set(PROPERTIES)-{'schema_version'})
        self.assertEqual(len(ids), len(set(ids)))
        for tag, attrs in doc.tags:
            if tag in ('input', 'select'):
                self.assertEqual(attrs['aria-describedby'], attrs['id'] + '-error')

    def test_translations_preserve_wire_values_and_empty_versions(self):
        source = preview_page(); doc = PageParser(); doc.feed(source)
        for value, label in doc.options:
            self.assertEqual(label, VALUES[value])
            self.assertNotEqual(label, value)
        for key, spec in PROPERTIES.items():
            for value in spec.get('enum', []):
                self.assertIn(value, VALUES)
        for tag, attrs in doc.tags:
            if tag == 'input' and attrs.get('id', '').endswith('_version'):
                self.assertEqual(attrs['value'], '')
                self.assertEqual(attrs['placeholder'], 'Например, 1.2.3')
