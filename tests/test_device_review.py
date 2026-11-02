"""In-process, synthetic two-step consent. No external Steam or device access."""
import unittest

import test_diagnostics_integration as fixtures
from test_remote_service import ORIGIN
from test_remote_ui import Elements


class DeviceReviewTests(unittest.TestCase):
    setUp = fixtures.IntegratedDiagnosticsTests.setUp
    tearDown = fixtures.IntegratedDiagnosticsTests.tearDown
    sign_in = fixtures.IntegratedDiagnosticsTests.sign_in
    csrf = fixtures.IntegratedDiagnosticsTests.csrf
    events = fixtures.IntegratedDiagnosticsTests.events
    check_response = fixtures.IntegratedDiagnosticsTests.check_response

    def start(self, appid=4231820, scopes=None):
        self.sign_in()
        return self.client.post('/v1/devices/pair/start', json={
            'appid': appid, 'scopes': scopes or ['saves.summary']}).json()

    def review(self, attempt):
        return self.client.post('/devices/review', data={
            'csrf': self.csrf(), 'user_code': attempt['user_code']}, headers={'origin': ORIGIN})

    def fields(self, response):
        return {a['name']: a['value'] for a in Elements(response.text).find('input', type='hidden')}

    def approve(self, data):
        return self.client.post('/devices/approve', data=data, headers={'origin': ORIGIN})

    def untouched(self):
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT owner FROM pairings').fetchone()[0])

    def test_summary_metadata_and_combined_exact_roundtrip(self):
        for scopes in (['saves.summary'], ['saves.metadata'], ['saves.metadata', 'saves.summary']):
            with self.subTest(scopes=scopes):
                attempt = self.start(scopes=scopes)
                first = Elements(self.client.get('/devices/approve').text)
                self.assertTrue(first.find('form', action='/devices/review'))
                self.assertFalse(first.find('select'))
                self.assertFalse(first.find('input', type='checkbox'))
                response = self.review(attempt)
                self.assertEqual(response.status_code, 200)
                self.check_response(response)
                review = Elements(response.text)
                self.assertFalse(review.find('select'))
                self.assertFalse(review.find('input', type='checkbox'))
                self.assertTrue(review.find('form', action='/devices/approve'))
                data = self.fields(response)
                self.assertEqual(set(data) - {'csrf', 'appid', 'user_code'}, set(scopes))
                self.assertEqual(data['appid'], str(attempt['appid']))
                self.assertNotIn(attempt['user_code'], self.output.getvalue())
                self.assertNotIn(attempt['device_code'], self.output.getvalue())
                self.assertEqual(self.approve(data).status_code, 200)
                polled = self.client.post('/v1/devices/pair/poll', json={'device_code': attempt['device_code']})
                self.assertEqual(polled.json()['scopes'], sorted(scopes))

    def test_review_and_cancel_do_not_grant(self):
        attempt = self.start()
        response = self.review(attempt)
        self.assertEqual(response.status_code, 200)
        self.client.get('/')
        self.untouched()

    def test_final_rejects_scope_and_game_changes_then_accepts_original_once(self):
        attempt = self.start()
        data = self.fields(self.review(attempt))
        for changed in (dict(data, **{'saves.metadata': 'yes'}), dict(data, appid='1245620')):
            self.assertEqual(self.approve(changed).status_code, 422)
            self.untouched()
        self.assertEqual(self.approve(data).status_code, 200)
        self.assertEqual(self.approve(data).status_code, 400)
        self.assertEqual(self.review(attempt).status_code, 400)

    def test_expiry_between_review_and_confirmation(self):
        attempt = self.start()
        data = self.fields(self.review(attempt))
        with self.app.state.store.db() as db:
            db.execute('UPDATE pairings SET expires=0')
        self.assertEqual(self.approve(data).status_code, 400)
        self.assertEqual(self.review(attempt).status_code, 400)
        self.untouched()

    def test_review_auth_origin_csrf_and_shared_rate_limit(self):
        self.assertEqual(self.client.post('/devices/review', data={}).status_code, 401)
        attempt = self.start()
        data = {'csrf': self.csrf(), 'user_code': attempt['user_code']}
        self.assertEqual(self.client.post('/devices/review', data=data).status_code, 403)
        self.assertEqual(self.client.post('/devices/review', data=dict(data, csrf='invalid'),
                                         headers={'origin': ORIGIN}).status_code, 403)
        for _ in range(10):
            response = self.review(attempt)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.review(attempt).status_code, 429)
        self.assertEqual(self.approve(self.fields(response)).status_code, 429)
        self.untouched()

    def test_catalog_membership_rechecked_at_confirmation(self):
        attempt = self.start(appid=570, scopes=['saves.metadata'])
        self.assertEqual(self.review(attempt).status_code, 422)
        with self.app.state.store.db() as db:
            owner = db.execute('SELECT owner FROM sessions').fetchone()[0]
            db.execute('INSERT INTO game_registrations(owner,appid,label,created) VALUES(?,?,?,?)',
                       (owner, 570, '<untrusted title>', 1))
        response = self.review(attempt)
        self.assertEqual(response.status_code, 200)
        self.assertIn('&lt;untrusted title&gt;', response.text)
        self.assertNotIn('<untrusted title>', response.text)
        data = self.fields(response)
        with self.app.state.store.db() as db:
            db.execute('DELETE FROM game_registrations')
        self.assertEqual(self.approve(data).status_code, 422)
        self.untouched()
