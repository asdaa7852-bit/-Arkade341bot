import tempfile,unittest
from pathlib import Path
from bot import SurvivalBot
from engine import setup,choose_roles,ROLES
class API:
    def send(self,*a,**kw):return {}
class HistoryTests(unittest.TestCase):
    def test_full_games_rotate_without_last_three_roles(self):
        history={}
        ps={str(i):{} for i in range(20)}
        for _ in range(100):
            setup(ps,history)
            self.assertEqual(len({p['role'] for p in ps.values()}),20)
            for uid,p in ps.items():
                self.assertNotIn(p['role'],history.get(uid,[]))
                history[uid]=(history.get(uid,[])+[p['role']])[-3:]
    def test_impossible_history_still_produces_unique_valid_roles(self):
        ps={str(i):{} for i in range(20)}
        history={u:list(ROLES)[:3] for u in ps}
        result=choose_roles(ps,history);self.assertEqual(set(result),set(ROLES))
    def test_begin_records_history_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            b=SurvivalBot(API(),str(Path(d)/'s.json'));b.username='Arkade341bot'
            b.games['-1']={'owner':'1','phase':'lobby','players':{str(i):{'name':str(i),'alive':True,'role':'citizen'} for i in range(1,5)}}
            b.state['role_history']={'1':['doctor','armor','mafia']}
            b.message({'text':'/begin','from':{'id':1},'chat':{'id':-1,'type':'group'}})
            self.assertEqual(b.games['-1']['phase'],'night')
            role=b.games['-1']['players']['1']['role'];self.assertNotIn(role,['doctor','armor','mafia'])
            self.assertEqual(b.state['role_history']['1'],['armor','mafia',role])
            restored=SurvivalBot(API(),b.path);self.assertEqual(restored.state['role_history'],b.state['role_history'])
