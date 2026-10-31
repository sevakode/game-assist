"""Achievement controls are explicit, per-game and truthful about cached data."""
import unittest
from remote_server import ui


class AchievementUITests(unittest.TestCase):
    def render(self, selected=True, configured=True, authorized=False, cached=None):
        return ui.achievements_panel({'appid':1245620, 'selected':selected,
            'achievements_available':configured, 'achievements_authorized':authorized},
            {'achievements':cached} if cached is not None else None, 'safe-token')

    def test_default_off_and_operator_gate(self):
        off=self.render(configured=False)
        self.assertIn('не настроен оператором',off)
        self.assertIn('не нужно передавать API-ключ',off)
        self.assertNotIn('<form',off)
        unselected=self.render(selected=False)
        self.assertNotIn('<form',unselected)
        enabled=self.render()
        self.assertIn('name="scope" value="achievements.read"',enabled)
        self.assertIn('name="appid" value="1245620"',enabled)
        self.assertIn('name="csrf" value="safe-token"',enabled)
        self.assertIn('name="enabled" value="yes"',enabled)
        self.assertNotIn('/account/achievements/refresh',enabled)
        self.assertIn('Чтение достижений выключено',enabled)

    def test_authorized_refresh_and_offline_revoke(self):
        result=self.render(authorized=True)
        self.assertIn('name="enabled" value="no"',result)
        self.assertIn('action="/account/achievements/refresh"',result)
        self.assertIn('Данные ещё не запрошены',result)
        removed_key=self.render(authorized=True,configured=False)
        self.assertIn('Отключить достижения',removed_key)
        self.assertNotIn('/account/achievements/refresh',removed_key)

    def test_only_ok_authorized_cache_displays_escaped_names_not_identifiers(self):
        cached={'status':'ok','items':[{'apiname':'DO_NOT_EXPOSE_API_ID','name':'<script>title</script>','unlock_time':1},
                                     {'apiname':'HIDDEN_FALLBACK_ID','name':None,'unlock_time':None}], 'received_at':100,
                'locked_names':['NEVER_LOCKED_NAME'],'total':999}
        result=self.render(authorized=True,cached=cached)
        self.assertIn('&lt;script&gt;title&lt;/script&gt;',result)
        self.assertNotIn('<script>',result)
        self.assertIn('Открытое достижение',result)
        for secret in ('DO_NOT_EXPOSE_API_ID','HIDDEN_FALLBACK_ID','NEVER_LOCKED_NAME','999'):
            self.assertNotIn(secret,result)
        self.assertNotIn('&lt;script&gt;title',self.render(cached=cached))
        self.assertNotIn('&lt;script&gt;title',self.render(authorized=True,configured=False,cached=cached))

    def test_unavailable_expired_are_unknown_not_zero(self):
        for status in ('unavailable','expired','not_requested'):
            result=self.render(authorized=True,cached={'status':status,'items':[{'name':'STALE_NAME'}]})
            self.assertNotIn('STALE_NAME',result)
            self.assertNotIn('0%',result)
            self.assertNotIn('<progress',result)
        self.assertIn('текущий прогресс неизвестен',self.render(authorized=True,cached={'status':'expired'}))
        self.assertIn('не означает отсутствие',self.render(authorized=True,cached={'status':'unavailable'}))

    def test_home_integration_and_selection_review_never_auto_grants(self):
        catalog=[{'appid':1245620,'selected':True,'achievements_available':True,'achievements_authorized':True,'authorized_scopes':['achievements.read']}]
        home=ui.home_body({'games':[{'appid':1245620,'achievements':{'status':'ok','items':[{'name':'Unlocked only'}]}}]},'token',capabilities={'catalog':catalog,'selected_appid':1245620})
        self.assertIn('Unlocked only',home)
        self.assertIn('/account/achievements/refresh',home)
        review=ui.games_review_body('token',catalog)
        self.assertNotIn('name="achievements.read"',review)
        self.assertNotIn('value="achievements.read"',review)
        self.assertIn('здесь он не включается',review)
