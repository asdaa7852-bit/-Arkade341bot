import tempfile
import time
import unittest
from pathlib import Path
from bot import SurvivalBot, leader

class API:
    def __init__(self): self.messages=[]
    def send(self, chat, text, keyboard=None): self.messages.append((chat,text))
    def call(self,*a,**kw): return {}

class SurvivalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api=API()
        self.bot=SurvivalBot(self.api,str(Path(self.tmp.name)/'state.json'))
        self.g={'owner':'1','phase':'night','round':1,'nonce':'abc','deadline':time.time()+60,'votes':{},'players':{str(i):{'name':str(i),'role':r,'hp':100,'power':0,'alive':True} for i,r in enumerate(['mafia','doctor','detective','armor'],1)}}
        self.bot.games['-1']=self.g
    def click(self,u,target,nonce='abc'):
        self.bot.callback({'id':'q','from':{'id':int(u)},'data':f'v:-1:{nonce}:{target}'})
    def resolve(self):
        self.g['deadline']=0
        self.bot.tick()
    def test_guard_and_role_armor(self):
        self.g['votes']={'1':'4','2':'4'}
        self.resolve()
        self.assertEqual(self.g['players']['4']['hp'],80) # 60/2 -10
    def test_loot_and_medic(self):
        self.g['players']['2']['hp']=40
        self.g['votes']={'2':'loot','1':'2'}
        self.resolve()
        self.assertEqual(self.g['players']['2']['hp'],30) # 40+25-35
        self.assertEqual(self.g['players']['2']['power'],5)
    def test_simultaneous_death(self):
        for p in self.g['players'].values(): p['hp']=10
        self.g['round']=12
        self.resolve()
        self.assertNotIn('-1',self.bot.games)
        self.assertTrue(any('Победителя нет' in t for _,t in self.api.messages))
    def test_last_survivor(self):
        for u in ['2','3']: self.g['players'][u]['alive']=False
        self.g['players']['4']['hp']=10
        self.g['votes']={'1':'4','4':'loot'}
        self.resolve()
        self.assertNotIn('-1',self.bot.games)
        self.assertTrue(any('Выжил сильнейший: 1' in t for _,t in self.api.messages))
    def test_validation(self):
        self.click('1','1');self.click('99','2');self.click('1','2','old');self.click('1','0')
        self.assertEqual(self.g['votes'],{})
        self.click('1','2');self.click('1','guard')
        self.assertEqual(self.g['votes'],{'1':'2'})
    def test_dead_and_expired(self):
        self.g['players']['2']['alive']=False
        self.click('2','1');self.click('1','2')
        self.g['deadline']=0
        self.click('1','3')
        self.assertEqual(self.g['votes'],{})
    def test_council_tie(self):
        self.g.update(phase='vote',votes={'1':'2','2':'1'})
        self.resolve()
        self.assertEqual(self.g['phase'],'night')
        self.assertTrue(all(p['hp']==100 for p in self.g['players'].values()))
    def test_council_damage(self):
        self.g.update(phase='vote',votes={'1':'2','3':'2'})
        self.resolve()
        self.assertEqual(self.g['players']['2']['hp'],0)
        self.assertFalse(self.g['players']['2']['alive'])
    def test_restart(self):
        self.bot.save()
        loaded=SurvivalBot(self.api,str(self.bot.path))
        self.assertEqual(loaded.games['-1']['nonce'],'abc')
    def test_scout(self):
        self.g['votes']={'3':'loot'}
        self.resolve()
        self.assertTrue(any(u=='3' and 'Разведка' in t for u,t in self.api.messages))

if __name__=='__main__': unittest.main()

class InterfaceTests(unittest.TestCase):
    setUp = SurvivalTests.setUp
    click = SurvivalTests.click
    resolve = SurvivalTests.resolve
    def test_mutant_regeneration_and_cap(self):
        p=self.g['players']['1'];p.update(role='mutant',hp=97)
        self.bot.phase('-1',self.g,'night')
        self.assertEqual(p['hp'],100)
        p['hp']=40
        self.bot.phase('-1',self.g,'discuss')
        self.assertEqual(p['hp'],40)
        self.bot.phase('-1',self.g,'night')
        self.assertEqual(p['hp'],45)
    def test_boost_only_before_voting_once(self):
        p=self.g['players']['1'];p['role']='agitator'
        self.g['phase']='discuss'
        self.click('1','boost')
        self.assertTrue(p['boost_used']);self.assertTrue(p['boosted'])
        p['boosted']=False
        self.click('1','boost')
        self.assertFalse(p['boosted'])
    def test_first_special_is_final_and_consumed(self):
        p=self.g['players']['1'];p['role']='sniper'
        self.click('1','shot~2');self.click('1','guard')
        self.resolve()
        self.assertEqual(p['used'],1)
    def test_all_buttons_authorized_and_fit_telegram(self):
        from engine import ROLES,defaults
        for role in ROLES:
            p=self.g['players']['1'];p.update(role=role,used=0);defaults(p)
            rows=self.bot.buttons('-1001234567890',self.g,'1')
            for row in rows:
                data=row[0]['callback_data']
                self.assertLessEqual(len(data.encode()),64)
                from engine import valid_action
                self.assertTrue(valid_action(self.g['players'],'1',data.split(':')[-1]))
    def test_begin_assigns_all_twenty_and_hides_secrets(self):
        from engine import ROLES
        self.g.update(phase='lobby',players={str(i):{'name':str(i),'alive':True,'role':'armor'} for i in range(1,21)})
        self.bot.username='Arkade341bot'
        self.bot.message({'text':'/begin','from':{'id':1},'chat':{'id':-1,'type':'supergroup'}})
        self.assertEqual({p['role'] for p in self.g['players'].values()},set(ROLES))
        group_text=' '.join(text for chat,text in self.api.messages if str(chat)=='-1')
        self.assertNotIn('Ваша роль:',group_text)
        self.assertEqual(self.g['phase'],'night')
