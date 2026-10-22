import tempfile
import unittest
from pathlib import Path
from bot import SurvivalBot, SHOP
class API:
    def __init__(self):self.messages=[];self.calls=[]
    def send(self,chat,text,keyboard=None):self.messages.append((chat,text,keyboard));return {}
    def call(self,method,**kw):self.calls.append((method,kw));return True
class ShopButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.bot=SurvivalBot(self.api,str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={'1':{'coins':1000,'wins':0,'games':0},'2':{'coins':0,'wins':0,'games':0}}
    def click(self,uid,item,qid='q1'):
        self.bot.callback({'id':qid,'data':'shop:buy:'+item,'from':{'id':uid},'message':{'message_id':7,'chat':{'id':-1,'type':'group'}}})
    def test_all_products_have_buttons(self):
        self.bot.message({'text':'/shop','from':{'id':1},'chat':{'id':1,'type':'private'}})
        rows=self.api.messages[-1][2]
        self.assertEqual({r[0]['callback_data'] for r in rows},{'shop:buy:'+k for k in SHOP})
        self.assertTrue(all(len(r[0]['callback_data'].encode())<=64 for r in rows))
    def test_click_charges_clicker_once_and_supports_multiple_products(self):
        self.click(1,'medkit');self.click(1,'medkit');self.click(1,'fire','q2')
        a=self.bot.state['accounts']['1'];self.assertEqual(a['coins'],650)
        self.assertEqual(a['consumables']['medkit'],1);self.assertIn('fire',a['inventory'])
        self.click(2,'medkit','q3');self.assertEqual(self.bot.state['accounts']['2']['coins'],0)
        self.assertFalse(self.bot.state['accounts']['2']['consumables'])
    def test_invalid_callback_does_not_spend(self):
        self.click(1,'missing');self.assertEqual(self.bot.state['accounts']['1']['coins'],1000)
