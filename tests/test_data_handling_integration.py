"""Public static document wired into the existing guarded service."""
import unittest
from unittest.mock import patch
import test_remote_service as service
from remote_server import data_handling, discovery, ui

class DataHandlingIntegration(unittest.TestCase):
    setUp=service.RemoteTests.setUp
    tearDown=service.RemoteTests.tearDown

    def test_anonymous_get_head_static_without_store_or_network(self):
        expected=data_handling.data_handling_page().body
        with patch.object(self.app.state.store,'session',side_effect=AssertionError('session read')), \
             patch.object(self.app.state.store,'db',side_effect=AssertionError('database read')), \
             patch('socket.create_connection',side_effect=AssertionError('network')):
            for suffix,headers in [('',{}),('?secret=do-not-reflect',{'cookie':'fake=private','authorization':'Bearer synthetic','x-forwarded-host':'untrusted.invalid'})]:
                response=self.client.get('/data-handling'+suffix,headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.content,expected)
                self.assertNotIn('set-cookie',response.headers)
                self.assertEqual(response.headers['x-robots-tag'],'noindex, nofollow')
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertEqual({v.strip() for v in response.headers['referrer-policy'].split(',')},{'no-referrer'})
                self.assertNotIn("'unsafe-inline'",response.headers['content-security-policy'])
            head=self.client.head('/data-handling')
            self.assertEqual(head.status_code,200)
            self.assertEqual(head.content,b'')
            self.assertEqual(head.headers['x-robots-tag'],'noindex, nofollow')

    def test_existing_boundaries_and_closed_discovery_are_preserved(self):
        self.assertEqual(sum(getattr(r,'path',None)=='/data-handling' for r in self.app.routes),1)
        self.assertEqual(self.client.get('/data-handling',headers={'host':'untrusted.invalid'}).status_code,400)
        self.assertNotEqual(self.client.post('/data-handling',headers={'origin':service.ORIGIN}).status_code,200)
        self.assertEqual(self.client.get('/assets/console.css').status_code,200)
        self.assertNotIn('/data-handling',discovery.PUBLIC_PAGES)
        self.assertNotIn('/data-handling',self.client.get('/sitemap.xml').text)
        self.assertIn('href="/data-handling"',self.client.get('/').text)
        self.assertIn('Как обрабатываются данные',ui.page('Private','').body.decode())
        self.assertNotIn('data-handling',ui.welcome_panel())
        self.assertEqual(self.client.get('/mcp').status_code,401)
