"""Public identity discovery never mutates private selection or permissions."""
import unittest
from unittest.mock import patch
from starlette.responses import HTMLResponse
from remote_server.games import DISCOVERY_TITLES,discovery_catalog,CURRENT_GAME_IDS
import test_remote_universal as universal

class DiscoveryTests(unittest.TestCase):
    setUp=universal.UniversalGameTests.setUp
    tearDown=universal.UniversalGameTests.tearDown
    sign_in=universal.UniversalGameTests.sign_in
    csrf=universal.UniversalGameTests.csrf
    owner=universal.UniversalGameTests.owner
    choose=universal.UniversalGameTests.choose
    catalog=universal.UniversalGameTests.catalog
    selected=universal.UniversalGameTests.selected
    add=universal.UniversalGameTests.add
    permission=universal.UniversalGameTests.permission

    def test_identity_catalog_bounded_offline_and_no_implicit_capability(self):
        entries=discovery_catalog();self.assertEqual(len(entries),17)
        self.assertEqual([g['appid'] for g in entries[:3]],list(CURRENT_GAME_IDS))
        self.assertEqual(len({g['appid'] for g in entries}),17)
        self.assertEqual([g['appid'] for g in entries if g['summary_supported']],[4231820])
        for g in entries:
            self.assertFalse(g['cloud_available']);self.assertFalse(g['achievements_available'])
            self.assertNotIn('selected',g);self.assertNotIn('owned',g)
            self.assertEqual(g['store_url'],f"https://store.steampowered.com/app/{g['appid']}/")
        entries[0]['name']='tampered';self.assertNotEqual(discovery_catalog()[0]['name'],'tampered')

    def test_public_focus_passes_discovery_without_writes(self):
        with patch('remote_server.app.ui.landing_body',return_value='public') as render:
            self.assertEqual(self.client.get('/games?game=1086940').status_code,200)
            self.assertEqual(render.call_args.kwargs['selected_appid'],1086940)
            self.assertEqual(len(render.call_args.kwargs['discovery_catalog']),17)
        with self.app.state.store.db() as db:
            for table in ('users','game_registrations','game_selections','grants'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.client.get('/games?game=999999').status_code,404)

    def test_add_review_scoped_permissions_and_user_isolation(self):
        self.sign_in();self.assertEqual(len(self.catalog()),3)
        self.assertEqual(self.add(1086940).status_code,303)
        game=next(g for g in self.catalog() if g['appid']==1086940)
        self.assertEqual(game['name'],"Baldur's Gate 3");self.assertFalse(game['user_label_unverified'])
        self.assertFalse(game['selected']);self.assertEqual(game['authorized_scopes'],[])
        self.assertEqual(self.choose([1086940]).status_code,303)
        self.assertEqual(self.permission(1086940,scope='saves.summary').status_code,422)
        self.assertEqual(self.permission(1086940,scope='saves.metadata').status_code,303)
        self.client.cookies.clear();self.sign_in('76561198000000002')
        self.assertNotIn(1086940,{g['appid'] for g in self.catalog()})

    def test_discovery_growth_never_expands_all_current_or_review(self):
        self.sign_in();revision=self.app.state.store.catalog_revision(self.owner(),self.catalog())
        with patch.dict(DISCOVERY_TITLES,{999998:'Future discovery'}):
            self.assertEqual(len(self.catalog()),3)
            self.assertEqual(self.app.state.store.catalog_revision(self.owner(),self.catalog()),revision)
            response=self.choose(action='review_all')
            self.assertNotIn('game_999998',response.text)
        self.assertEqual(self.selected(),set())

    def test_custom_label_stays_unverified_and_escaped(self):
        self.sign_in();self.add(1086940,'<custom>')
        game=next(g for g in self.catalog() if g['appid']==1086940)
        self.assertTrue(game['user_label_unverified']);self.assertEqual(game['name'],'<custom>')
        self.assertIn('&lt;custom&gt;',self.client.get('/games').text)
