import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from bot import SurvivalBot
class API:
    def __init__(self):self.messages=[];self.calls=[]
    def send(self,chat,text,keyboard=None):self.messages.append((str(chat),text,keyboard));return {}
    def call(self,method,**kw):self.calls.append((method,kw));return {}
class ExileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={str(i):{'coins':2500,'wins':0,'games':0,'consumables':{'exile':1}} for i in range(1,5)}
        self.g={'owner':'1','phase':'night','round':1,'nonce':'abc','deadline':time.time()+60,'votes':{'2':'1'},'players':{str(i):{'name':'Игрок'+str(i),'hp':100,'alive':True,'role':'armor','power':0} for i in range(1,5)}}
        self.bot.games['-1']=self.g
    def click(self,actor='1',target='2',nonce='abc',source=None):
        self.bot.callback({'id':'q','from':{'id':int(actor)},'message':{'chat':{'id':int(actor),'type':'private'}},'data':f'exile:-1:{nonce}:{source or actor}:{target}'})
    def test_private_selection_and_anonymous_public_death(self):
        self.bot.message({'text':'/use exile','from':{'id':1},'chat':{'id':1,'type':'private'}})
        self.assertEqual(self.bot.api.messages[-1][0],'1');self.assertEqual(len(self.bot.api.messages[-1][2]),3)
        self.click();self.assertFalse(self.g['players']['2']['alive']);self.assertEqual(self.g['players']['2']['hp'],0)
        public=[text for chat,text,k in self.bot.api.messages if chat=='-1']
        self.assertEqual(len(public),1);self.assertIn('Игрок2',public[0]);self.assertNotIn('Игрок1',public[0])
        self.assertNotIn('2',self.g['votes']);self.assertTrue(self.g['secret_exile_used'])
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],0)
        self.click('3','4');self.assertTrue(self.g['players']['4']['alive'])
        restored=SurvivalBot(API(),self.bot.path);self.assertTrue(restored.games['-1']['secret_exile_used'])
    def test_invalid_clicks_never_consume(self):
        self.click(target='1');self.click(nonce='old');self.click(actor='3',source='1')
        self.g['players']['1']['consumable_used']=True;self.click()
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],1)
        self.assertTrue(self.g['players']['2']['alive'])
    def test_final_survivor_gets_normal_win(self):
        self.g['players']['3']['alive']=False;self.g['players']['4']['alive']=False
        self.click();self.assertNotIn('-1',self.bot.games)
        self.assertEqual(self.bot.state['accounts']['1']['wins'],1)
    def test_purchase_price_and_replay(self):
        self.bot.state['accounts']['1']['consumables']['exile']=0
        m={'text':'/buy exile','message_id':1,'from':{'id':1},'chat':{'id':1,'type':'private'}}
        self.bot.message(m);self.bot.message(m)
        self.assertEqual(self.bot.state['accounts']['1']['coins'],500)
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],1)
    def test_failed_save_rolls_back_elimination(self):
        with patch.object(self.bot,'save',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.click()
        self.assertTrue(self.bot.games['-1']['players']['2']['alive'])
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['exile'],1)
