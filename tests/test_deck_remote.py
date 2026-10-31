"""In-process Deck/remote wire integration, synthetic save and fake Steam only."""
import contextlib
import io
import json
from pathlib import Path
import urllib.error
import unittest

from deck.client import Store, Runner, RePairRequired, pair
from remote_server.app import COOKIE, digest
import test_remote_service as service


class DeckRemoteTests(unittest.TestCase):
    setUp = service.RemoteTests.setUp
    tearDown = service.RemoteTests.tearDown
    sign_in = service.RemoteTests.sign_in
    csrf = service.RemoteTests.csrf

    def test_generic_metadata_pair_send_and_revoke(self):
        self.sign_in()
        test = self

        class Adapter:
            origin = service.ORIGIN

            def post(self, route, payload, token=None):
                headers = {'authorization': 'Bearer ' + token} if token else {}
                response = test.client.post(route, json=payload, headers=headers)
                if response.status_code >= 400:
                    raise urllib.error.HTTPError(self.origin + route, response.status_code, 'Rejected', {}, None)
                result = response.json()
                if route.endswith('/start'):
                    # Explicit simulated browser approval; never bypass consent records.
                    approved = test.client.post('/devices/approve', data={
                        'csrf': test.csrf(), 'user_code': result['user_code'], 'appid': str(payload['appid']),
                        'saves.metadata': 'yes'}, headers={'origin': self.origin})
                    test.assertEqual(approved.status_code, 200, approved.text)
                return result

        root = Path(self.temp.name)
        path = root / 'PRIVATE_SYNTHETIC_SAVE.bin'
        path.write_bytes(b'PRIVATE_UNKNOWN_FORMAT_CONTENTS')
        store = Store(root / 'deck-state')
        adapter = Adapter()
        with contextlib.redirect_stdout(io.StringIO()):
            pair(store, adapter, str(path), sleep=lambda _: None, appid=1245620, mode='metadata')
        runner = Runner(store, adapter, store.read('config.json'))
        runner.tick(); runner.tick()
        self.assertEqual(runner.state['sync_status'], 'synced')
        with self.app.state.store.db() as db:
            owner = db.execute('SELECT owner FROM sessions WHERE hash=?', (digest(self.client.cookies[COOKIE]),)).fetchone()['owner']
        projection = self.app.state.store.projection(owner)
        game = next(g for g in projection['games'] if g['appid'] == 1245620)
        self.assertEqual(game['status'], 'metadata_only_not_game_progress')
        self.assertIsNone(game['summary'])
        self.assertEqual(game['metadata']['size_bytes'], path.stat().st_size)
        self.assertNotIn('PRIVATE_', json.dumps(projection))
        revoked = self.client.post('/account/games/revoke', data={'csrf': self.csrf(), 'appid': '1245620'},
                                   headers={'origin': service.ORIGIN})
        self.assertEqual(revoked.status_code, 303, revoked.text)
        path.write_bytes(b'PRIVATE_CHANGED_CONTENTS_DIFFERENT_SIZE')
        runner.tick()
        with self.assertRaises(RePairRequired):
            runner.tick()
        self.assertFalse(self.app.state.store.projection(owner)['games'])
