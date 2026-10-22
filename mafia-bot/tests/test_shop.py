import tempfile
import unittest
from pathlib import Path
from bot import SurvivalBot, cosmetics

class API:
    def __init__(self): self.messages=[]
    def send(self, chat, text, keyboard=None): self.messages.append(text)

class ShopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'state.json'))
        self.bot.username='Arkade341bot'
        self.account={'coins':500,'wins':5,'games':10,'name':'Игрок'}
        self.bot.state['accounts']={'1':self.account}
    def cmd(self,text):
        self.bot.message({'text':text,'from':{'id':1},'chat':{'id':1,'type':'private'}}, button_action=True)
    def test_purchase_once_and_persistence(self):
        self.cmd('/buy fire');self.cmd('/buy fire')
        self.assertEqual(self.account['coins'],350)
        self.assertEqual(self.account['inventory'],['fire'])
        restored=SurvivalBot(API(),self.bot.path)
        self.assertEqual(restored.state['accounts']['1'],self.account)
    def test_insufficient_and_unknown(self):
        self.cmd('/buy legend');self.cmd('/buy unknown')
        self.assertEqual(self.account['coins'],500)
        self.assertEqual(self.account['inventory'],[])
    def test_equip_requires_ownership_and_slots(self):
        self.cmd('/equip diamond');self.assertFalse(cosmetics(self.account))
        self.cmd('/buy survivor');self.cmd('/buy fire')
        self.cmd('/equip survivor');self.cmd('/equip fire')
        self.assertEqual(cosmetics(self.account),'Выживший · 🔥 Огонь')
        self.cmd('/profile');self.assertIn('Выживший · 🔥 Огонь',self.bot.api.messages[-1])
        self.cmd('/unequip');self.assertFalse(cosmetics(self.account))
        self.assertEqual(len(self.account['inventory']),2)
    def test_old_accounts_and_empty_inventory(self):
        self.bot.state.pop('accounts');self.cmd('/shop');self.cmd('/inventory')
        self.assertIn('Пока пусто',self.bot.api.messages[-1])
