import tempfile,unittest
from pathlib import Path
from bot import SurvivalBot, GROUP_COMMANDS
class API:
    def __init__(self):self.messages=[];self.calls=[]
    def send(self,chat,text,keyboard=None):self.messages.append((text,keyboard));return {}
    def call(self,method,**kw):self.calls.append((method,kw));return {}
class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.bot=SurvivalBot(self.api,str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
    def cmd(self,text,kind='group'):
        self.bot.message({'text':text,'from':{'id':1},'chat':{'id':-1 if kind=='group' else 1,'type':kind}})
    def test_scoped_menus(self):
        self.bot.configure_commands()
        menus={kw['scope']['type']:{c['command'] for c in kw['commands']} for method,kw in self.api.calls}
        self.assertEqual(menus['all_group_chats'],{c for c,d in GROUP_COMMANDS})
        self.assertIn('shop',menus['all_private_chats']);self.assertNotIn('shop',menus['default'])
    def test_group_help_and_start_are_short(self):
        self.cmd('/help');self.assertNotIn('/buy',self.api.messages[-1][0]);self.assertNotIn('/stars',self.api.messages[-1][0])
        self.cmd('/start');self.assertNotIn('/shop',self.api.messages[-1][0]);self.assertIn('autostart_at',self.bot.games['-1'])
    def test_private_help_and_group_economy_redirect(self):
        self.cmd('/help','private');self.assertIn('/shop',self.api.messages[-1][0])
        self.cmd('/shop');self.assertTrue(self.api.messages[-1][1]);self.assertNotIn('accounts',self.bot.state)
    def test_old_group_shop_button_cannot_buy(self):
        self.bot.callback({'id':'q','data':'shop:buy:fire','from':{'id':1},'message':{'chat':{'id':-1,'type':'group'}}})
        self.assertNotIn('accounts',self.bot.state);self.assertTrue(self.api.calls[-1][1]['show_alert'])
