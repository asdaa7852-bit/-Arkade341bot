import tempfile,time,unittest
from pathlib import Path
from bot import SurvivalBot
from engine import council,vote_counts
class API:
    def __init__(self):self.messages=[]
    def send(self,chat,text,keyboard=None):self.messages.append((str(chat),text,keyboard));return {}
    def call(self,*args,**kw):return {}
class VoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=API();self.bot=SurvivalBot(self.api,str(Path(self.tmp.name)/'s.json'));self.bot.username='Arkade341bot'
        self.g={'owner':'1','phase':'discuss','round':1,'players':{str(i):{'name':'Игрок'+str(i),'alive':True,'hp':100,'power':0,'role':'immune' if i==2 else 'armor'} for i in range(1,5)}}
        self.bot.games['-1']=self.g
    def test_ballots_private_and_report_public(self):
        self.bot.phase('-1',self.g,'vote')
        private=[m for m in self.api.messages if m[0]!='-1'];self.assertEqual(len(private),4)
        for uid,text,rows in private:
            self.assertTrue(rows);self.assertNotIn('v:-1:'+self.g['nonce']+':'+uid,[b['callback_data'] for row in rows for b in row])
        group=[m for m in self.api.messages if m[0]=='-1'];self.assertTrue(all('callback_data' not in b for m in group for row in m[2] or [] for b in row))
        def click(uid,target,private=True):
            self.bot.callback({'id':'q','from':{'id':int(uid)},'data':f'v:-1:{self.g["nonce"]}:{target}','message':{'chat':{'id':int(uid) if private else -1,'type':'private' if private else 'group'}}})
        click('1','2',False);self.assertFalse(self.g['votes'])
        click('1','3');click('1','2');click('3','2');click('2','0')
        self.g['deadline']=0;self.bot.tick()
        self.assertFalse(self.g['players']['2']['alive']);self.assertEqual(self.g['players']['2']['hp'],0)
        report=next(text for chat,text,rows in self.api.messages if text.startswith('🗳 Итоги'))
        self.assertIn('Игрок1 → Игрок2',report);self.assertIn('Игрок2: 2',report);self.assertIn('Игрок4 → не голосовал',report)
    def test_tie_abstentions_and_invalid_votes(self):
        self.g['votes']={'1':'2','2':'1','3':'0','4':'0'};self.assertIsNone(council(self.g)[0])
        self.g['votes']={'1':'2','2':'0','3':'0','4':'0'};self.assertEqual(council(self.g)[0],'2')
        self.assertFalse(self.g['players']['2']['alive'])
        self.g['votes']={'2':'1','1':'1','99':'1'};self.assertFalse(vote_counts(self.g))
