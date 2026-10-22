import copy
import random
import unittest
from engine import ROLES, SPECIAL, setup, resolve_night, council, valid_action

class RoleTests(unittest.TestCase):
    def game(self, *roles):
        ps={str(i):{'name':str(i),'role':r,'hp':100,'alive':True,'power':0} for i,r in enumerate(roles,1)}
        return {'players':ps,'votes':{},'round':1}
    def run_night(self,g): return resolve_night(g,random.Random(42))
    def test_all_twenty_assigned_once(self):
        ps={str(i):{} for i in range(20)};setup(ps)
        self.assertEqual({p['role'] for p in ps.values()},set(ROLES))
        hunter=next(p for p in ps.values() if p['role']=='hunter')
        self.assertIn(hunter['prey'],ps)
    def test_specials_limits(self):
        for role,(kind,limit) in SPECIAL.items():
            with self.subTest(role=role):
                g=self.game(role,'doctor');p=g['players']['1']
                action=kind+'~2' if kind in ('shot','poison','steal') else kind
                self.assertTrue(valid_action(g['players'],'1',action))
                p['used']=limit
                self.assertFalse(valid_action(g['players'],'1',action))
                self.assertFalse(valid_action(g['players'],'2',action))
    def test_raid_and_armor(self):
        g=self.game('mafia','armor');g['votes']={'1':'2','2':'loot'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],75)
    def test_sniper_ignores_guard_and_armor(self):
        g=self.game('sniper','armor');g['votes']={'1':'shot~2'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],55)
        self.assertEqual(g['players']['1']['used'],1)
    def test_assassin(self):
        g=self.game('assassin','doctor');g['votes']={'1':'2','2':'loot'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],60)
    def test_trapper_deterministic(self):
        g=self.game('trapper','doctor','detective');g['votes']={'2':'1','3':'1'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],85)
        self.assertEqual(g['players']['3']['hp'],100)
    def test_thief_preserves_simultaneous_attack_power(self):
        g=self.game('thief','mafia');g['players']['2']['power']=15
        g['votes']={'1':'steal~2','2':'1'};self.run_night(g)
        self.assertEqual(g['players']['1']['hp'],50)
        self.assertEqual(g['players']['1']['power'],10)
        self.assertEqual(g['players']['2']['power'],5)
    def test_poison_three_following_nights_both_orders(self):
        for roles,src,t in [(('poisoner','doctor'),'1','2'),(('doctor','poisoner'),'2','1')]:
            g=self.game(*roles);g['votes']={src:'poison~'+t};self.run_night(g)
            self.assertEqual(g['players'][t]['hp'],100)
            for hp in (90,80,70,70):
                g['votes']={};self.run_night(g)
                self.assertEqual(g['players'][t]['hp'],hp)
    def test_alchemist(self):
        g=self.game('alchemist','doctor');g['players']['1']['hp']=20;g['votes']={'1':'elixir'};self.run_night(g)
        self.assertEqual(g['players']['1']['hp'],60)
    def test_berserker_threshold_before_healing(self):
        g=self.game('berserker','doctor');g['players']['1']['hp']=40;g['votes']={'1':'2','2':'loot'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],60)
    def test_engineer(self):
        g=self.game('engineer','mafia','doctor');g['votes']={'1':'shelter','2':'1','3':'1'};self.run_night(g)
        self.assertEqual(g['players']['1']['hp'],80)
    def test_ghost_blocks_sniper_but_not_arena(self):
        g=self.game('ghost','sniper');g['votes']={'1':'hide','2':'shot~1'};g['round']=3;self.run_night(g)
        self.assertEqual(g['players']['1']['hp'],90)
    def test_vampire_effective_damage(self):
        g=self.game('vampire','doctor');g['players']['1']['hp']=40;g['players']['2']['hp']=6
        g['votes']={'1':'2'};self.run_night(g)
        self.assertEqual(g['players']['1']['hp'],42)
    def test_impostor(self):
        g=self.game('detective','impostor');g['votes']={'1':'loot'};_,notes=self.run_night(g)
        self.assertEqual(len(notes),1);self.assertNotIn('Самозванец',notes[0][1])
    def test_courtesan_legacy_boost_cannot_double_vote(self):
        g=self.game('agitator','doctor','armor');g['players']['1']['boosted']=True
        g['votes']={'1':'2','2':'1'}
        self.assertEqual(council(g),(None,0));self.assertFalse(g['players']['1']['boosted'])
    def test_immune_once(self):
        g=self.game('immune','doctor');g['players']['1']['poison']=[3]
        self.run_night(g);self.assertEqual(g['players']['1']['hp'],100)
        self.run_night(g);self.assertEqual(g['players']['1']['hp'],90)
    def test_hunter_bounty_and_attack(self):
        g=self.game('hunter','doctor','armor');g['players']['1']['prey']='2'
        g['players']['2']['hp']=10;g['votes']={'3':'2'};self.run_night(g)
        self.assertTrue(g['players']['1']['bounty'])
        g['votes']={'1':'3','3':'loot'};self.run_night(g)
        self.assertEqual(g['players']['3']['hp'],75)
    def test_avenger_and_no_hazard_revenge(self):
        g=self.game('avenger','mafia');g['players']['1']['hp']=20;g['votes']={'2':'1','1':'loot'};self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],75)
        g=self.game('avenger','mafia');g['players']['1']['hp']=1;g['round']=3;self.run_night(g)
        self.assertEqual(g['players']['2']['hp'],90)
    def test_order_independent_poison_and_theft(self):
        g=self.game('thief','poisoner','doctor');g['votes']={'1':'steal~2','2':'poison~3','3':'loot'};g['players']['2']['power']=10
        rev=copy.deepcopy(g);rev['players']=dict(reversed(list(rev['players'].items())))
        self.run_night(g);self.run_night(rev)
        self.assertEqual(g['players'],rev['players'])
