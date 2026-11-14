"""Search mechanics and protocol logging for reflected stat drops."""
import unittest
from unittest.mock import AsyncMock, patch

from poke_engine import Move, Pokemon, Side, State, generate_instructions
from foul_play_player import FoulPlayPlayer


class MirrorArmorTests(unittest.TestCase):
    def outcomes(self, move="nobleroar", ability="unaware", attack_boost=0,
                 target_ability="mirrorarmor", target_boost=0):
        state = State(
            side_one=Side(pokemon=[Pokemon(id="dondozo", hp=500, maxhp=500,
                ability=ability, speed=200, moves=[Move(id=move)])],
                attack_boost=attack_boost),
            side_two=Side(pokemon=[Pokemon(id="corviknight", hp=500, maxhp=500,
                ability=target_ability, speed=100, moves=[Move(id="splash")])],
                attack_boost=target_boost))
        return [state.apply_instructions(b) for b in generate_instructions(state, move, "splash")
                if b.percentage > 0]

    def test_noble_roar_reflects_both_drops(self):
        for outcome in self.outcomes():
            self.assertEqual(outcome.side_one.attack_boost, -1)
            self.assertEqual(outcome.side_one.special_attack_boost, -1)
            self.assertEqual(outcome.side_two.attack_boost, 0)
            self.assertEqual(outcome.side_two.special_attack_boost, 0)

    def test_reflection_respects_recipient_ability_and_stage_limit(self):
        for ability, expected in (("clearbody", 0), ("contrary", 1), ("mirrorarmor", -1)):
            for outcome in self.outcomes(ability=ability):
                self.assertEqual(outcome.side_one.attack_boost, expected)
                self.assertEqual(outcome.side_two.attack_boost, 0)
        for outcome in self.outcomes(attack_boost=-6):
            self.assertEqual(outcome.side_one.attack_boost, -6)
        for outcome in self.outcomes(target_boost=-6):
            self.assertEqual(outcome.side_one.attack_boost, 0)
            self.assertEqual(outcome.side_one.special_attack_boost, -1)

    def test_self_drops_and_other_abilities_are_unchanged(self):
        for outcome in self.outcomes(move="growl", target_ability="pressure"):
            self.assertEqual(outcome.side_two.attack_boost, -1)
        for outcome in self.outcomes(move="curse", ability="mirrorarmor"):
            self.assertEqual(outcome.side_one.speed_boost, -1)
            self.assertEqual(outcome.side_one.attack_boost, 1)

    def test_damaging_secondary_drop_is_reflected(self):
        outcomes = self.outcomes(move="chillingwater")
        self.assertTrue(any(o.side_one.attack_boost == -1 for o in outcomes))
        self.assertTrue(all(o.side_two.attack_boost == 0 for o in outcomes))


class MirrorArmorLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_ability_and_each_reflected_drop_are_logged_once(self):
        events = [["", "-ability", "p2a: Corviknight", "Mirror Armor"],
                  ["", "-unboost", "p1a: Dondozo", "atk", "1"],
                  ["", "-unboost", "p1a: Dondozo", "spa", "1"]]
        player = object.__new__(FoulPlayPlayer)
        player.pending_messages = {}
        player.side_index = 0
        player.requests = {}
        with patch("poke_env.player.Player._handle_battle_message", new_callable=AsyncMock), \
             self.assertLogs("simulation", level="INFO") as logs:
            await FoulPlayPlayer._handle_battle_message(player, [[">battle-test"], *events])
            player.side_index = 1
            await FoulPlayPlayer._handle_battle_message(player, [[">battle-test"], *events])
        self.assertEqual(len(logs.output), 3)
        for event, entry in zip(events, logs.output):
            self.assertIn("|".join(event), entry)

class KnownAbilityPolicyTests(unittest.TestCase):
    def state(self, ability="synchronize", moves=("screech", "foulplay")):
        return State(side_one=Side(pokemon=[Pokemon(id="umbreon", ability=ability,
            moves=[Move(id=m) for m in moves])]),
            side_two=Side(pokemon=[Pokemon(id="corviknight", ability="mirrorarmor",
                moves=[Move(id="metalsound"), Move(id="bravebird")])]))

    def test_disables_screech_before_search_without_hiding_set(self):
        from foul_play_player import exclude_reflected_status_moves
        state = self.state()
        outcome = exclude_reflected_status_moves(state)
        self.assertTrue(outcome.side_one.pokemon[0].moves[0].disabled)
        self.assertFalse(outcome.side_one.pokemon[0].moves[1].disabled)
        self.assertFalse(state.side_one.pokemon[0].moves[0].disabled)
        self.assertEqual(outcome.side_two.pokemon[0].ability.lower(), "mirrorarmor")

    def test_engine_policy_cannot_select_excluded_moves_on_either_side(self):
        from foul_play_player import exclude_reflected_status_moves
        from poke_engine import monte_carlo_tree_search
        state = exclude_reflected_status_moves(self.state(ability="mirrorarmor"))
        result = monte_carlo_tree_search(state, 20, threads=1)
        self.assertNotIn("screech", {o.move_choice for o in result.side_one})
        self.assertNotIn("metalsound", {o.move_choice for o in result.side_two})

    def test_applies_to_both_sides_and_retains_forced_or_beneficial_choices(self):
        from foul_play_player import exclude_reflected_status_moves
        outcome = exclude_reflected_status_moves(self.state(ability="mirrorarmor"))
        self.assertTrue(outcome.side_one.pokemon[0].moves[0].disabled)
        self.assertTrue(outcome.side_two.pokemon[0].moves[0].disabled)
        for ability in ("contrary", "defiant", "competitive", "moldbreaker"):
            self.assertFalse(exclude_reflected_status_moves(self.state(ability=ability))
                             .side_one.pokemon[0].moves[0].disabled)
        self.assertFalse(exclude_reflected_status_moves(self.state(moves=("screech",)))
                         .side_one.pokemon[0].moves[0].disabled)
