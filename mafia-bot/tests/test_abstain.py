import tempfile,time,unittest
from pathlib import Path
from bot import SurvivalBot
from engine import council,vote_counts,setup
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append((str(chat),text,keyboard));return {}
    def call(self,*a,**kw):return {}
class AbstainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bot=SurvivalBot(API(),str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.g={'owner':'1','round':1,'players':{str(i):{'name':str(i),'alive':True,'hp':100,'role':'armor','power':0} for i in range(1,5)}}
        self.bot.games['-1']=self.g;self.bot.phase('-1',self.g,'vote')
    def click(self,target):
        self.bot.callback({'id':'q','from':{'id':1},'data':f'v:-1:{self.g["nonce"]}:{target}','message':{'chat':{'id':1,'type':'private'}}})
    def test_final_abstention_consumed_and_persisted(self):
        self.click('0');self.assertFalse(self.g['players']['1'].get('abstain_used'))
        council(self.g);self.bot.save()
        self.assertTrue(self.g['players']['1']['abstain_used'])
        restored=SurvivalBot(API(),self.bot.path);self.assertTrue(restored.games['-1']['players']['1']['abstain_used'])
        self.bot.phase('-1',self.g,'vote')
        ballot=[m for m in self.bot.api.messages if m[0]=='1'][-1][2]
        self.assertFalse(any(b['callback_data'].endswith(':0') for row in ballot for b in row))
        self.click('0');self.assertFalse(self.g['votes'])
        self.g['votes']={'1':'0'};self.assertFalse(vote_counts(self.g))
    def test_changed_vote_and_timeout_do_not_consume(self):
        self.click('0');self.click('2');council(self.g)
        self.assertFalse(self.g['players']['1'].get('abstain_used'))
        self.g['votes']={};council(self.g);self.assertFalse(self.g['players']['1'].get('abstain_used'))
    def test_new_game_resets_limit(self):
        for p in self.g['players'].values():p['abstain_used']=True
        setup(self.g['players']);self.assertTrue(all(not p['abstain_used'] for p in self.g['players'].values()))
