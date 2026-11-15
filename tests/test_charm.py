"""Known-set policy for Attack drops against special attackers."""
import unittest

from poke_engine import Move, Pokemon, Side, State, monte_carlo_tree_search
from foul_play_player import exclude_reflected_status_moves


class CharmPolicyTests(unittest.TestCase):
    def state(self, enemy_moves=('meteorbeam', 'powergem', 'earthpower', 'sludgebomb'),
              user_moves=('charm', 'faketears', 'shadowball'), volatiles=()):
        return State(side_one=Side(pokemon=[Pokemon(id='mismagius',
            moves=[Move(id=m) for m in user_moves])]),
            side_two=Side(pokemon=[Pokemon(id='glimmora',
                moves=[Move(id=m) for m in enemy_moves])],
                volatile_statuses=set(volatiles)))

    def test_charm_excluded_but_other_debuffs_retained(self):
        original = self.state()
        state = exclude_reflected_status_moves(original)
        self.assertTrue(state.side_one.pokemon[0].moves[0].disabled)
        self.assertFalse(original.side_one.pokemon[0].moves[0].disabled)
        self.assertFalse(state.side_one.pokemon[0].moves[1].disabled)
        result = monte_carlo_tree_search(state, 20, threads=1)
        self.assertNotIn('charm', {o.move_choice for o in result.side_one})

    def test_both_perspectives(self):
        state = self.state()
        reversed_state = State(side_one=state.side_two, side_two=state.side_one)
        self.assertTrue(exclude_reflected_status_moves(reversed_state)
                        .side_two.pokemon[0].moves[0].disabled)

    def test_preserves_physical_mixed_and_uncertain_sets(self):
        for moves in [('closecombat',), ('powergem', 'earthquake'), ('transform',),
                      ('shellsidearm',), ('terablast',)]:
            with self.subTest(moves=moves):
                state = exclude_reflected_status_moves(self.state(enemy_moves=moves))
                self.assertFalse(state.side_one.pokemon[0].moves[0].disabled)

    def test_preserves_forced_choice_and_attack_interactions(self):
        for kwargs in ({'user_moves': ('charm',)},
                       {'user_moves': ('charm', 'confuseray')},
                       {'user_moves': ('charm', 'foulplay')},
                       {'volatiles': ('confusion',)}):
            with self.subTest(kwargs=kwargs):
                state = exclude_reflected_status_moves(self.state(**kwargs))
                self.assertFalse(state.side_one.pokemon[0].moves[0].disabled)
