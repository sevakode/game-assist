"""Document-scoped CSP contracts; no browser or external callback requests."""
import asyncio
import unittest
from remote_server.app import ResponseSecurity


class ConsentCSPTests(unittest.TestCase):
    def policy(self, source, path='/oauth/consent', method='GET', status=200):
        async def run():
            messages = []
            async def app(scope, receive, send):
                await send({'type':'http.response.start','status':status,
                            'headers':[(b'content-security-policy', b"form-action 'none'")]})
                await send({'type':'http.response.body','body':b''})
            async def receive():
                return {'type':'http.request','body':b''}
            async def send(message):
                messages.append(message)
            await ResponseSecurity(app)({'type':'http','path':path,'method':method,
                'state':{'consent_callback_source':source}}, receive, send)
            return [v.decode() for k,v in messages[0]['headers'] if k==b'content-security-policy']
        return asyncio.run(run())

    def test_callback_source_is_exact_no_query_stripping_or_header_injection(self):
        exact = 'https://claude.ai/api/mcp/auth_callback'
        policy = self.policy(exact)
        self.assertEqual(len(policy), 1)
        self.assertIn("form-action 'self' " + exact + ';', policy[0])
        for source in (exact+'?x=1', exact+'#x', exact+'; script-src *', exact+'\r\nX: y',
                       'https:', 'https://*.claude.ai/callback', 'http://claude.ai/callback',
                       'https://user@claude.ai/callback', exact+'%2fextra', None):
            with self.subTest(source=source):
                self.assertEqual(self.policy(source)[0], "form-action 'none'")
                self.assertIn("form-action 'self';", self.policy(source)[1])
        # Explicit port stays explicit; neither origin-wide nor prefix source emitted.
        self.assertIn("form-action 'self' https://claude.ai:443/callback;",
                      self.policy('https://claude.ai:443/callback')[0])

    def test_only_successful_get_consent_document_can_extend_policy(self):
        source='https://claude.ai/api/mcp/auth_callback'
        for path, method, status in [('/games','GET',200),('/oauth/consent','POST',303),
                                     ('/oauth/consent','GET',400),('/oauth/consent','GET',303)]:
            policy=self.policy(source,path,method,status)
            self.assertEqual(len(policy),2)
            self.assertEqual(policy[0], "form-action 'none'")
            self.assertIn("form-action 'self';",policy[1])
            self.assertNotIn(source, " ".join(policy))

    def test_actual_data_handling_endpoint_retains_stricter_policy(self):
        import test_mcp_tool_metadata as fixtures
        from remote_server.data_handling import data_handling_page
        case = fixtures.MCPToolMetadataTests()
        case.setUp()
        try:
            response = case.client.get('/data-handling')
            self.assertEqual(response.status_code, 200)
            policies = response.headers.get_list('content-security-policy')
            self.assertEqual(len(policies), 2)
            self.assertEqual(policies[0], data_handling_page().headers['content-security-policy'])
            self.assertIn("form-action 'none'", policies[0])
            self.assertIn("form-action 'self';", policies[1])
            self.assertEqual(response.headers.get_list('referrer-policy'), ['strict-origin'])
        finally:
            case.doCleanups()
