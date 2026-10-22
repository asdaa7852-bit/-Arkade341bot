import tempfile
import time
import unittest
from pathlib import Path
from bot import SurvivalBot
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append(text);return {}
class ConsumableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.bot.state['accounts']={'1':{'coins':1000,'wins':0,'games':0}}
        self.p={'name':'Игрок','role':'doctor','alive':True,'hp':70,'power':0,'poison':[3]}
        self.g={'owner':'1','phase':'night','deadline':time.time()+60,'players':{'1':self.p}}
        self.bot.games['-1']=self.g
    def cmd(self,text,mid=1):self.bot.message({'text':text,'message_id':mid,'from':{'id':1},'chat':{'id':1,'type':'private'}})
    def test_purchase_replay_and_repeat_purchase(self):
        self.cmd('/buy medkit');self.cmd('/buy medkit');self.cmd('/buy medkit',2)
        a=self.bot.state['accounts']['1'];self.assertEqual(a['coins'],600);self.assertEqual(a['consumables']['medkit'],1)
        self.assertEqual(self.p['hp'],90)
    def test_heal_once_and_persist(self):
        self.cmd('/buy medkit');self.cmd('/buy stim',2);self.cmd('/use medkit',3);self.cmd('/use stim',4)
        self.assertEqual(self.p['hp'],90);self.assertEqual(self.p['power'],0)
        restored=SurvivalBot(API(),self.bot.path);self.assertTrue(restored.games['-1']['players']['1']['consumable_used'])
        self.assertEqual(restored.state['accounts']['1']['consumables'],{'medkit':0,'stim':1})
    def test_full_hp_wrong_phase_dead_or_expired_does_not_consume(self):
        self.p['hp']=100;self.cmd('/buy medkit');self.cmd('/use medkit',2)
        self.p['hp']=50;self.g['phase']='vote';self.cmd('/use medkit',3)
        self.g['phase']='night';self.p['alive']=False;self.cmd('/use medkit',4)
        self.p['alive']=True;self.g['deadline']=0;self.cmd('/use medkit',5)
        self.assertEqual(self.bot.state['accounts']['1']['consumables']['medkit'],1)
        self.assertFalse(self.p.get('consumable_used'))
    def test_stim_cap_and_antidote(self):
        self.p['power']=18;self.cmd('/buy stim');self.cmd('/use stim',2);self.assertEqual(self.p['power'],20)
        self.p.pop('consumable_used');self.cmd('/buy antidote',3);self.cmd('/use antidote',4);self.assertEqual(self.p['poison'],[])

    def test_cosmetics_equip_on_purchase(self):
        self.cmd('/buy survivor')
        self.cmd('/buy fire',2)
        account=self.bot.state['accounts']['1']
        self.assertEqual(account['equipped'],{'title':'survivor','badge':'fire'})
        self.assertEqual(account['coins'],750)
