import tempfile
import unittest
from bot import SurvivalBot


class API:
    def __init__(self): self.messages=[];self.calls=[]
    def send(self,c,t,keyboard=None): self.messages.append((c,t,keyboard));return {}
    def call(self,method,**kwargs): self.calls.append((method,kwargs));return {}


class StreakTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.bot=SurvivalBot(self.api,self.tmp.name+'/s.json');self.bot.username='Arkade341bot'
    def finish(self, winner='1'):
        g={'players':{uid:dict(name=uid,role='armor',alive=uid==winner,hp=100 if uid==winner else 0) for uid in ('1','2')}}
        self.bot.games['-1']=g;self.bot.finish('-1',g);return g
    def exchange(self, mode='one', receipt='q', private=True):
        self.bot.callback({'id':receipt,'data':'exchange:'+mode,'from':{'id':1},'message':{'chat':{'id':1 if private else -1,'type':'private' if private else 'group'}}})
    def test_milestones_and_duplicate_finish(self):
        for _ in range(4):self.finish()
        a=self.bot.state['accounts']['1'];self.assertEqual(a['arena_coins'],0)
        g=self.finish();self.assertEqual(a['arena_coins'],1);self.assertEqual(a['win_streak'],5)
        self.bot.finish('-1',g);self.assertEqual(a['arena_coins'],1)
        for _ in range(5):self.finish()
        self.assertEqual(a['win_streak'],10);self.assertEqual(a['arena_coins'],3)
        for _ in range(10):self.finish()
        self.assertEqual(a['arena_coins'],6);self.assertEqual(a['best_win_streak'],20)
    def test_defeat_and_no_winner_reset_but_preserve_currency(self):
        for _ in range(5):self.finish()
        self.finish('2');a=self.bot.state['accounts']['1']
        self.assertEqual((a['win_streak'],a['arena_coins'],a['best_win_streak']),(0,1,5))
        self.finish();self.finish(None);self.assertEqual(a['win_streak'],0)
        restored=SurvivalBot(API(),self.bot.path)
        self.assertEqual(restored.state['accounts']['1']['arena_coins'],1)
    def test_exchange_ratio_receipt_and_finite_special_currency(self):
        self.bot.state['accounts']={'1':{'coins':25,'arena_coins':3}}
        self.bot.state['coin_owner_id']='1'
        self.exchange();a=self.bot.state['accounts']['1']
        self.assertEqual((a['coins'],a['arena_coins']),(125,2))
        self.exchange();self.assertEqual((a['coins'],a['arena_coins']),(125,2))
        self.exchange('all','new');self.assertEqual((a['coins'],a['arena_coins']),(325,0))
        self.exchange('one','empty');self.assertEqual(a['coins'],325)
    def test_group_and_save_failure_do_not_spend(self):
        self.bot.state['accounts']={'1':{'coins':0,'arena_coins':1}}
        self.exchange(private=False);a=self.bot.state['accounts']['1']
        self.assertEqual(a['arena_coins'],1)
        def fail():raise OSError('disk')
        self.bot.save=fail
        with self.assertRaises(OSError):self.exchange()
        self.assertEqual((a['coins'],a['arena_coins']),(0,1))
        self.assertFalse(self.bot.state.get('exchange_receipts'))
    def test_profile_buttons_bound_to_owner_in_group_and_private(self):
        self.bot.state['accounts']={'1':{'coins':0,'arena_coins':2}}
        for kind,chat in [('private',1),('group',-1)]:
            self.bot.message({'text':'/profile','from':{'id':1},'chat':{'id':chat,'type':kind}})
            rows=self.api.messages[-1][2]
            self.assertEqual(rows[0][0]['callback_data'],'exchange:one:1')
            self.assertEqual(rows[1][0]['callback_data'],'exchange:all:1')
        q={'id':'other','data':'exchange:one:1','from':{'id':2},'message':{'chat':{'id':-1,'type':'group'}}}
        self.bot.callback(q)
        self.assertEqual(self.bot.state['accounts']['1']['arena_coins'],2)
        q.update(id='mine',**{'from':{'id':1}});self.bot.callback(q)
        self.assertEqual(self.bot.state['accounts']['1']['arena_coins'],1)
        self.assertEqual(self.bot.state['accounts']['1']['coins'],100)
    def test_inspected_profile_has_no_exchange_controls(self):
        self.bot.state['coin_owner_id']='1'
        self.bot.state['accounts']={'2':{'coins':0,'arena_coins':3}}
        self.bot.message({'text':'/playerprofile 2','from':{'id':1},'chat':{'id':1,'type':'private'}})
        self.assertIsNone(self.api.messages[-1][2])
    def test_old_accounts_start_streak_from_zero_and_cancel_does_not_reset(self):
        self.bot.state['accounts']={'1':{'coins':100,'wins':50,'games':100}}
        self.finish();a=self.bot.state['accounts']['1']
        self.assertEqual(a['win_streak'],1);self.assertEqual(a['arena_coins'],0)
        g={'owner':'1','phase':'night','players':{}}
        self.bot.games['-1']=g
        self.bot.message({'text':'/stop','from':{'id':1},'chat':{'id':-1,'type':'group'}})
        self.assertEqual(a['win_streak'],1)
