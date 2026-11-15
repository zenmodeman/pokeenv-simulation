"""Delaying Mega Evolution preserves Sturdy against Articuno's OHKO plan."""
import unittest

from poke_engine import Move, Pokemon, Side, State, generate_instructions, monte_carlo_tree_search


def matchup(*, skarmory_hp=323, articuno_hp=384, locked=False):
    return State(
        side_one=Side(pokemon=[Pokemon(
            id="skarmory", level=100, nature="jolly", evs=(208, 48, 0, 0, 0, 252),
            item="skarmorite", ability="sturdy",
            base_ability="sturdy", types=("steel", "flying"),
            hp=skarmory_hp, maxhp=323, attack=208, defense=316,
            special_defense=176, speed=262,
            moves=[Move(id="ironhead"), Move(id="roost")]),
            Pokemon(hp=0, terastallized=True)]),
        side_two=Side(pokemon=[Pokemon(
            id="articuno", level=100, ability="pressure", types=("ice", "flying"),
            hp=articuno_hp, maxhp=384, defense=276, speed=206,
            moves=[Move(id="mindreader"), Move(id="sheercold")]),
            Pokemon(hp=0, terastallized=True)],
            volatile_statuses={"lockon"} if locked else set()))


def outcomes(state, move):
    return [(b.percentage, state.apply_instructions(b))
            for b in generate_instructions(state, move, "sheercold")
            if b.percentage > 0]


class MegaSkarmoryTests(unittest.TestCase):
    def test_sturdy_blocks_sheer_cold_even_when_damaged_and_locked_on(self):
        for hp in (323, 100):
            with self.subTest(hp=hp):
                state = matchup(skarmory_hp=hp, locked=True)
                base = outcomes(state, "ironhead")
                self.assertTrue(base)
                self.assertTrue(all(o.side_one.pokemon[0].hp == hp for _, o in base))
                self.assertTrue(all(o.side_one.pokemon[0].ability.lower() == "sturdy"
                                    for _, o in base))
                mega = outcomes(state, "ironhead-mega")
                # Iron Head can flinch; every non-flinch lets Sheer Cold KO.
                self.assertGreater(sum(p for p, o in mega
                                       if o.side_one.pokemon[0].hp == 0), 0)
                self.assertTrue(all(o.side_one.pokemon[0].ability.lower() == "stalwart"
                                    for _, o in mega))

    def test_mega_can_secure_cleanup_before_sheer_cold(self):
        state = matchup(skarmory_hp=100, articuno_hp=200, locked=True)
        self.assertTrue(any(o.side_two.pokemon[0].hp > 0
                            for _, o in outcomes(state, "ironhead")))
        mega = outcomes(state, "ironhead-mega")
        self.assertTrue(mega)
        self.assertTrue(all(o.side_two.pokemon[0].hp == 0
                            and o.side_one.pokemon[0].hp == 100 for _, o in mega))

    def test_search_retains_mega_option_after_a_base_turn(self):
        state = outcomes(matchup(locked=True), "ironhead")[0][1]
        result = monte_carlo_tree_search(state, 20, threads=1)
        self.assertTrue({"ironhead", "ironhead-mega"}
                        <= {o.move_choice for o in result.side_one})
