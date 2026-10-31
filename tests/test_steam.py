import json
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx

from server.steam import SteamService, SteamError, OPENID_NS, OPENID_ENDPOINT, ACHIEVEMENTS_ENDPOINT

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc).timestamp()
RETURN = 'http://127.0.0.1:8000/v1/steam/callback?state=synthetic'
ID = '76561198000000000'


def assertion():
    return {'openid.ns': OPENID_NS, 'openid.mode': 'id_res',
        'openid.op_endpoint': OPENID_ENDPOINT,
        'openid.claimed_id': 'https://steamcommunity.com/openid/id/' + ID,
        'openid.identity': 'https://steamcommunity.com/openid/id/' + ID,
        'openid.return_to': RETURN, 'openid.response_nonce': '2026-10-31T12:00:00Zsynthetic',
        'openid.assoc_handle': 'synthetic', 'openid.sig': 'synthetic',
        'openid.signed': 'op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle'}


class SteamTests(unittest.TestCase):
    def service(self, handler=None, key=''):
        self.requests = []
        def handle(request):
            self.requests.append(request)
            if handler:
                return handler(request)
            return httpx.Response(200, text=f'ns:{OPENID_NS}\nis_valid:true\n')
        return SteamService(api_key=key, transport=httpx.MockTransport(handle), clock=lambda: NOW)

    def test_login_url_contains_only_official_navigation(self):
        url = SteamService.login_url(RETURN)
        self.assertEqual(urlsplit(url).netloc, 'steamcommunity.com')
        self.assertEqual(parse_qs(urlsplit(url).query)['openid.return_to'], [RETURN])
        with self.assertRaises(SteamError):
            SteamService.login_url('http://external.test/callback')

    def test_verified_callback_and_replay(self):
        service = self.service()
        self.assertEqual(service.verify_callback(assertion(), RETURN), ID)
        request = self.requests[0]
        self.assertEqual(str(request.url), OPENID_ENDPOINT)
        self.assertEqual(request.method, 'POST')
        self.assertEqual(parse_qs(request.content.decode())['openid.mode'], ['check_authentication'])
        with self.assertRaisesRegex(SteamError, 'replayed_assertion'):
            service.verify_callback(assertion(), RETURN)
        self.assertEqual(len(self.requests), 1)

    def test_rejects_bad_fields_without_network(self):
        for field, value in [('openid.op_endpoint', 'https://invalid.example/'),
                ('openid.ns', 'bad'), ('openid.identity', 'bad'), ('openid.claimed_id', 'https://steamcommunity.com/openid/id/not-a-number'),
                ('openid.return_to', RETURN + 'other'), ('openid.signed', 'identity'),
                ('openid.response_nonce', '2020-01-01T00:00:00Zold'),
                ('openid.response_nonce', '2026-10-31T13:00:00Zfuture'), ('openid.sig', '')]:
            with self.subTest(field=field, value=value):
                service = self.service()
                data = assertion(); data[field] = value
                with self.assertRaises(SteamError):
                    service.verify_callback(data, RETURN)
                self.assertEqual(self.requests, [])

    def test_duplicate_parameters_rejected(self):
        service = self.service()
        with self.assertRaises(SteamError):
            service.verify_callback(list(assertion().items()) + [('openid.sig', 'second')], RETURN)
        self.assertEqual(self.requests, [])

    def test_direct_verification_fail_closed(self):
        for code, body in [(302, ''), (200, 'is_valid:false'), (200, 'is_valid:true'),
                (200, f'ns:{OPENID_NS}\nis_valid:true\nis_valid:false'), (200, 'x' * 17000), (500, '')]:
            with self.subTest(code=code, body=body[:50]):
                service = self.service(lambda r: httpx.Response(code, text=body, headers={'Location': 'https://invalid.example'}))
                with self.assertRaises(SteamError):
                    service.verify_callback(assertion(), RETURN)
                self.assertEqual(len(self.requests), 1)

    def test_not_configured_is_offline(self):
        service = self.service()
        self.assertEqual(service.get_achievements(ID, 4231820)['status'], 'not_configured')
        self.assertEqual(self.requests, [])

    def test_achievements_normalization_and_key_not_in_url(self):
        service = self.service(lambda r: httpx.Response(200, json={'playerstats': {'success': True, 'achievements': [
            {'apiname': 'SYNTHETIC', 'achieved': 1, 'unlocktime': 123, 'name': 'Synthetic fixture'}]}}), key='operator-fixture')
        result = service.get_achievements(ID, 4231820)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['achievements'][0]['achieved'], True)
        request = self.requests[0]
        self.assertEqual(str(request.url).split('?')[0], ACHIEVEMENTS_ENDPOINT)
        self.assertNotIn('operator-fixture', str(request.url))
        self.assertEqual(request.headers['x-webapi-key'], 'operator-fixture')

    def test_private_and_unavailable_not_inferred_as_zero_progress(self):
        for status, data, expected in [(200, {'playerstats': {'success': False, 'error': 'Profile is private'}}, 'private'),
            (403, {}, 'unavailable'), (429, {}, 'unavailable'), (302, {}, 'unavailable'),
            (200, {'playerstats': {'success': True, 'achievements': [{'apiname': 'A', 'achieved': 'false'}]}}, 'unavailable')]:
            with self.subTest(status=status, data=data):
                service = self.service(lambda r: httpx.Response(status, json=data), key='fixture')
                self.assertEqual(service.get_achievements(ID, 1)['status'], expected)

    def test_timeout_is_sanitized(self):
        def fail(request):
            raise httpx.ReadTimeout('secret-detail', request=request)
        service = self.service(fail, key='fixture')
        self.assertNotIn('secret-detail', json.dumps(service.get_achievements(ID, 1)))
        with self.assertRaisesRegex(SteamError, '^upstream_unavailable$'):
            service.verify_callback(assertion(), RETURN)

    def test_oversize_and_invalid_response(self):
        for body in [b'x' * 1048577, b'not json', b'[]']:
            service = self.service(lambda r: httpx.Response(200, content=body), key='fixture')
            self.assertEqual(service.get_achievements(ID, 1)['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
