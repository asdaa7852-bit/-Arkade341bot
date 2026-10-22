import tempfile,time,unittest
from pathlib import Path
from bot import SurvivalBot
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append((str(chat),text,keyboard));return {}
    def call(self,*a,**kw):return {}
class PurchaseMenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={'1':{'coins':2500,'wins':0,'games':0}}
        self.g={'phase':'night','owner':'1','round':1,'nonce':'abc','deadline':time.time()+60,'votes':{},'players':{str(i):{'name':'Игрок'+str(i),'role':'armor','power':0,'hp':100,'alive':i!=4} for i in range(1,5)}}
        self.bot.games['-1']=self.g
    def purchase(self):self.bot.message({'text':'/buy exile','message_id':1,'from':{'id':1},'chat':{'id':1,'type':'private'}}, button_action=True)
    def test_buy_immediately_shows_alive_targets_and_click_works(self):
        self.purchase();chat,text,rows=self.bot.api.messages[-1]
        self.assertEqual(chat,'1');self.assertEqual([r[0]['text'] for r in rows],['⚔️ Убрать: Игрок2','⚔️ Убрать: Игрок3'])
        self.bot.callback({'id':'q','from':{'id':1},'message':{'chat':{'id':1,'type':'private'}},'data':rows[0][0]['callback_data']})
        self.assertFalse(self.g['players']['2']['alive']);self.assertEqual(self.bot.state['accounts']['1']['coins'],500)
    def test_day_menu_is_refreshed_at_night_and_cannot_kill_during_day(self):
        self.g['phase']='discuss';self.purchase();data=self.bot.api.messages[-1][2][0][0]['callback_data']
        self.bot.callback({'id':'q','from':{'id':1},'message':{'chat':{'id':1,'type':'private'}},'data':data})
        self.assertTrue(self.g['players']['2']['alive']);self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],1)
        self.bot.phase('-1',self.g,'night')
        menus=[m for m in self.bot.api.messages if m[0]=='1' and m[2] and m[2][0][0].get('callback_data','').startswith('exile:')]
        self.assertEqual(len(menus),2);self.assertNotEqual(data,menus[-1][2][0][0]['callback_data'])
    def test_purchase_without_game_is_saved(self):
        self.bot.games.clear();self.purchase();self.assertIsNone(self.bot.api.messages[-1][2])
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],1)
