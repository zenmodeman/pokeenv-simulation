"""Mind Reader/Sheer Cold mechanics and known-set decision regressions."""
import unittest
from unittest.mock import patch

from poke_engine import Move, Pokemon, Side, State, generate_instructions, monte_carlo_tree_search
from foul_play_player import KnownSetMatch, Turn, select_search_move
from test_foul_play import request


def state(*, types=('normal', 'typeless'), ability='none', level=100,
          item='none', hp=400, volatiles=(), response='splash', user_hp=384, accuracy=-6):
    return State(side_one=Side(pokemon=[Pokemon(id='articuno', types=('ice', 'flying'),
        hp=user_hp, maxhp=384, level=100, speed=250, special_attack=200,
        moves=[Move(id='mindreader'), Move(id='sheercold'), Move(id='icebeam')]),
        Pokemon(hp=0, terastallized=True)],
        accuracy_boost=accuracy), side_two=Side(pokemon=[Pokemon(id='blissey', types=types,
        hp=hp, maxhp=400, level=level, ability=ability, item=item,
        special_defense=400, moves=[Move(id=response), Move(id="splash")]),
        Pokemon(hp=0, terastallized=True)],
        volatile_statuses=set(volatiles), substitute_health=100))


def outcomes(s, move, response='splash'):
    return [(branch.percentage, s.apply_instructions(branch))
            for branch in generate_instructions(s, move, response) if branch.percentage > 0]


class MindReaderTests(unittest.TestCase):
    def test_combo_guarantees_ko_and_expires(self):
        s = state()
        setup = outcomes(s, 'mindreader')
        self.assertEqual(len(setup), 1)
        locked = setup[0][1]
        self.assertIn('lockon', {v.lower() for v in locked.side_one.volatile_statuses})
        hits = outcomes(locked, 'sheercold')
        self.assertAlmostEqual(sum(p for p, o in hits if o.side_two.pokemon[0].hp == 0), 100)
        expired = outcomes(locked, 'icebeam')[0][1]
        self.assertNotIn('lockon', {v.lower() for v in expired.side_one.volatile_statuses})

    def test_unassisted_sheer_cold_ignores_accuracy_stages(self):
        branches = outcomes(state(), 'sheercold')
        self.assertAlmostEqual(sum(p for p, o in branches if o.side_two.pokemon[0].hp == 0), 30, places=4)

    def test_immunities_hold_even_with_mind_reader_or_no_guard(self):
        for kwargs in ({'types': ('ice', 'normal')}, {'ability': 'sturdy'},
                       {'level': 101}, {'types': ('ice', 'normal'), 'ability': 'noguard'}):
            with self.subTest(kwargs=kwargs):
                locked = outcomes(state(**kwargs), 'mindreader')[0][1]
                self.assertTrue(all(o.side_two.pokemon[0].hp == 400
                                    for _, o in outcomes(locked, 'sheercold')))

    def test_protect_and_substitute_block_setup(self):
        for kwargs, response in (({'response': 'protect'}, 'protect'),
                                 ({'volatiles': ('substitute',)}, 'splash')):
            with self.subTest(kwargs=kwargs):
                self.assertTrue(all('lockon' not in {v.lower() for v in o.side_one.volatile_statuses}
                                    for _, o in outcomes(state(**kwargs), 'mindreader', response)))

    def test_protect_sash_and_substitute_prevent_immediate_ko(self):
        for kwargs, response in (({'response': 'protect'}, 'protect'),
                                 ({'item': 'focussash'}, 'splash'),
                                 ({'volatiles': ('substitute',)}, 'splash')):
            with self.subTest(kwargs=kwargs):
                s = state(**kwargs)
                # Set up without Protect; Protect can then block the follow-up.
                locked = outcomes(s, 'mindreader')[0][1]
                self.assertTrue(all(o.side_two.pokemon[0].hp > 0
                                    for _, o in outcomes(locked, 'sheercold', response)))

    def test_search_can_choose_setup_and_follow_through(self):
        s = state()
        result = monte_carlo_tree_search(s, 100, threads=1)
        self.assertEqual(select_search_move(s, result), 'mindreader')
        locked = outcomes(s, 'mindreader')[0][1]
        result = monte_carlo_tree_search(locked, 100, threads=1)
        self.assertEqual(select_search_move(locked, result), 'sheercold')

    def test_search_prefers_immediate_reliable_ko(self):
        s = state(hp=1, accuracy=0)
        result = monte_carlo_tree_search(s, 100, threads=1)
        self.assertEqual(select_search_move(s, result), 'icebeam')

    def test_protocol_activation_reaches_both_perspectives_and_expires(self):
        teams = ['Articuno\nAbility: Pressure\n- Mind Reader\n- Sheer Cold',
                 'Blissey\nAbility: Natural Cure\n- Splash']
        match = KnownSetMatch(teams, 20)
        reqs = {0: request('p1', 'Articuno', ['mindreader', 'sheercold'], 'pressure', '',
                           {'atk': 100, 'def': 200, 'spa': 200, 'spd': 200, 'spe': 200}, 384),
                1: request('p2', 'Blissey', ['splash'], 'naturalcure', '',
                           {'atk': 100, 'def': 100, 'spa': 100, 'spd': 400, 'spe': 100}, 400)}
        match.prepare('reader', Turn(requests=reqs))
        turn = Turn(requests=reqs, messages=[
            ['', '-activate', 'p1a: Articuno', 'move: Mind Reader', '[of] p2a: Blissey']])
        match.prepare('reader', turn)
        for index, side_name in ((0, 'side_one'), (1, 'side_two')):
            with patch('foul_play_player.monte_carlo_tree_search', side_effect=RuntimeError('capture')) as search:
                with self.assertRaisesRegex(RuntimeError, 'capture'):
                    match.search(turn.snapshots[index])
            self.assertIn('lockon', {v.lower() for v in
                          getattr(search.call_args.args[0], side_name).volatile_statuses})
        following = Turn(requests=reqs)
        match.prepare('reader', following)
        self.assertNotIn('lockon', following.snapshots[0].user.active.volatile_statuses)
