import tempfile
import unittest
from bot import SurvivalBot, equipped_items, set_decorations, cosmetics, API
from profile_fx import render


class FakeAPI:
    def __init__(self): self.messages=[]; self.uploads=0; self.calls=[]
    def send(self, chat, text, keyboard=None): self.messages.append((chat,text,keyboard))
    def profile(self, chat, uid, text, keyboard=None): self.send(chat,text,keyboard)
    def decoration_animation(self, chat, items):
        self.uploads+=1
        return {'animation':{'file_id':'merged-'+','.join(items)}}
    def call(self, method, **kwargs): self.calls.append((method,kwargs)); return {}


class DecorationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.api=FakeAPI(); self.bot=SurvivalBot(self.api,self.tmp.name+'/s.json'); self.bot.username='Arkade341bot'
        self.account={'coins':5000,'inventory':['survivor','raider','legend','fire','wolf','diamond']}
        self.bot.state['accounts']={'1':self.account}
    def click(self, action):
        self.bot.callback({'id':action,'data':'inv:'+action,'from':{'id':1},'message':{'chat':{'id':1,'type':'private'}}})
    def message(self,text):
        self.bot.message({'text':text,'from':{'id':1},'chat':{'id':1,'type':'private'}})
    def test_migrate_legacy_and_four_slots(self):
        self.account['equipped']={'title':'survivor','badge':'fire'}
        self.assertEqual(equipped_items(self.account),['survivor','fire'])
        self.click('equip:raider'); self.click('equip:diamond')
        self.assertEqual(len(equipped_items(self.account)),4)
        self.click('equip:wolf'); self.assertEqual(len(equipped_items(self.account)),4)
        self.assertNotIn('wolf',equipped_items(self.account))
        self.click('equip:fire'); self.click('equip:wolf')
        self.assertEqual(equipped_items(self.account),['survivor','raider','diamond','wolf'])
        self.assertEqual(cosmetics(self.account).count(' · '),3)
        restored=SurvivalBot(FakeAPI(),self.bot.path)
        self.assertEqual(equipped_items(restored.state['accounts']['1']),equipped_items(self.account))
    def test_clear_all_and_unowned_rejected(self):
        set_decorations(self.account,['fire','wolf','diamond','legend'])
        self.click('unequip:all'); self.assertEqual(equipped_items(self.account),[])
        self.account['inventory']=[];self.click('equip:fire')
        self.assertEqual(equipped_items(self.account),[])
    def test_profile_shows_four_decorations_without_animation(self):
        set_decorations(self.account,['fire','wolf','diamond','legend'])
        self.message('/profile'); self.message('/profile')
        self.assertEqual(self.api.uploads,0)
        self.assertFalse(any(method=='sendAnimation' for method,_ in self.api.calls))
        text=self.api.messages[-1][1]
        for label in ('Огонь','Волк','Бриллиант','Гроза арены'):
            self.assertIn(label,text)
    def test_purchase_auto_equips_without_losing_owned_items(self):
        self.account['inventory'].remove('legend')
        set_decorations(self.account,['survivor','raider','fire','wolf'])
        self.bot.callback({'id':'purchase','data':'shop:buy:legend','from':{'id':1},'message':{'chat':{'id':1,'type':'private'}}})
        self.assertEqual(equipped_items(self.account),['raider','fire','wolf','legend'])
        self.assertIn('survivor',self.account['inventory'])
    def test_gif_loop_and_bounded_size(self):
        data=render(['fire','wolf','diamond','legend'])
        self.assertTrue(data.startswith(b'GIF89a'))
        self.assertIn(b'NETSCAPE2.0',data)
        self.assertLess(len(data),2_000_000)
