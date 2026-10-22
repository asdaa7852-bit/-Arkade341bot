import tempfile
import time
import unittest
from bot import SurvivalBot
from engine import ROLE_PERKS, ROLES, defaults, setup, valid_action, resolve_night


class API:
    def __init__(self): self.messages = []
    def send(self, chat, text, keyboard=None): self.messages.append((chat, text, keyboard))
    def call(self, *args, **kwargs): return {}


class PerkTests(unittest.TestCase):
    def game(self, role):
        ps = {str(i): dict(name=str(i), role='doctor', alive=True, hp=100, power=0) for i in range(1, 4)}
        ps['1']['role'] = role
        return dict(players=ps, votes={'1': 'perk~2'}, round=1, phase='night', nonce='abc', deadline=time.time()+60)

    def test_all_twenty_roles_once_and_separate_from_original_ability(self):
        self.assertEqual(set(ROLE_PERKS), set(ROLES))
        for role in ROLES:
            with self.subTest(role=role):
                g = self.game(role)
                self.assertTrue(valid_action(g['players'], '1', 'perk~2'))
                resolve_night(g)
                self.assertTrue(g['players']['1']['perk_used'])
                self.assertEqual(g['players']['1']['used'], 0)
                self.assertFalse(valid_action(g['players'], '1', 'perk~3'))

    def test_heal_cap_and_direct_damage(self):
        g = self.game('doctor'); g['players']['2']['hp'] = 40
        resolve_night(g); self.assertEqual(g['players']['2']['hp'], 73)
        g = self.game('doctor'); g['players']['2']['hp'] = 90
        resolve_night(g); self.assertEqual(g['players']['2']['hp'], 100)
        g = self.game('sniper'); resolve_night(g)
        self.assertEqual(g['players']['2']['hp'], 67)

    def test_attack_modifiers_current_night_only(self):
        for role, hp in [('mafia', 67), ('detective', 83)]:
            g = self.game(role); g['votes'].update({'2': '3', '3': 'loot'})
            resolve_night(g); self.assertEqual(g['players']['3']['hp'], hp)
            g['votes'] = {'2': '3', '3': 'loot'}
            before = g['players']['3']['hp']
            resolve_night(g); self.assertEqual(g['players']['3']['hp'], min(100, before+25)-25)

    def test_invalid_targets_and_new_match_reset(self):
        g = self.game('doctor'); ps = g['players']
        for target in ('1', '99'):
            self.assertFalse(valid_action(ps, '1', 'perk~'+target))
        ps['2']['alive'] = False
        self.assertFalse(valid_action(ps, '1', 'perk~2'))
        ps['1']['perk_used'] = True; setup(ps)
        self.assertTrue(all(not p['perk_used'] for p in ps.values()))
        defaults(ps['1']); self.assertFalse(ps['1']['perk_used'])

    def test_buffs_do_not_stack_and_opposites_cancel(self):
        for role, expected in [('berserker', 67), ('detective', 75)]:
            g = self.game('mafia')
            g['players']['4'] = dict(name='4', role=role, alive=True, hp=100, power=0)
            g['votes'].update({'4': 'perk~2', '2': '3', '3': 'loot'})
            resolve_night(g)
            self.assertEqual(g['players']['3']['hp'], expected)

    def test_harm_death_and_bounty(self):
        g = self.game('avenger'); g['players']['2']['hp'] = 30
        g['players']['3'].update(role='hunter', prey='2')
        resolve_night(g)
        self.assertEqual(g['players']['2']['hp'], 0)
        self.assertFalse(g['players']['2']['alive'])
        self.assertTrue(g['players']['3']['bounty'])

    def test_private_target_menu_choice_lock_and_saved_once_limit(self):
        with tempfile.TemporaryDirectory() as d:
            api = API(); bot = SurvivalBot(api, d+'/s.json'); bot.username = 'Arkade341bot'
            g = self.game('doctor'); g['votes'] = {}; bot.games['-1'] = g
            q = dict(id='q', data='perk:-1:abc:1', **{'from': {'id': 1}}, message={'chat': {'id': 1, 'type': 'private'}})
            bot.callback(q)
            rows = api.messages[-1][2]
            self.assertEqual(len(rows), 2)
            q['data'] = 'v:-1:abc:perk~2'; bot.callback(q)
            q['data'] = 'v:-1:abc:perk~3'; bot.callback(q)
            self.assertEqual(g['votes']['1'], 'perk~2')
            resolve_night(g); bot.save()
            restored = SurvivalBot(API(), bot.path)
            self.assertTrue(restored.games['-1']['players']['1']['perk_used'])
