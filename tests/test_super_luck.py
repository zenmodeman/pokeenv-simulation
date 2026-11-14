"""Regression checks against the compiled engine, including its chance branches."""
import unittest

from poke_engine import Move, Pokemon, Side, State, generate_instructions


class SuperLuckTests(unittest.TestCase):
    def outcomes(self, move, ability="superluck", defender="none", hp=1000):
        attacker = Pokemon(id="unfezant", hp=1000, maxhp=1000,
                           ability=ability, item="powerherb", attack=200, speed=200,
                           moves=[Move(id=move)])
        target = Pokemon(id="snorlax", hp=hp, maxhp=hp, ability=defender,
                         defense=200, speed=100, moves=[Move(id="splash")])
        state = State(side_one=Side(pokemon=[attacker]), side_two=Side(pokemon=[target]))
        outcomes = []
        for branch in generate_instructions(state, move, "splash"):
            result = state.apply_instructions(branch)
            outcomes.append((branch.percentage, hp - result.side_two.pokemon[0].hp,
                             result.side_one.pokemon[0].item.lower()))
        self.assertAlmostEqual(sum(p for p, _, _ in outcomes), 100, places=4)
        return outcomes

    def assert_crit_probability(self, move, ability, expected):
        outcomes = self.outcomes(move, ability)
        damage = sorted({d for _, d, _ in outcomes if d > 0})
        self.assertEqual(len(damage), 2)
        hits = sum(p for p, d, _ in outcomes if d > 0)
        crits = sum(p for p, d, _ in outcomes if d == damage[-1])
        self.assertAlmostEqual(crits / hits, expected, places=5)

    def test_super_luck_adds_a_stage_to_each_move(self):
        for move in ("skyattack", "nightslash"):
            with self.subTest(move=move):
                self.assert_crit_probability(move, "superluck", 0.5)
                self.assert_crit_probability(move, "none", 0.125)
        for move in ("return", "bravebird"):
            with self.subTest(move=move):
                self.assert_crit_probability(move, "superluck", 0.125)
                self.assert_crit_probability(move, "none", 1 / 24)

    def test_power_herb_skips_charge_and_is_consumed(self):
        outcomes = self.outcomes("skyattack")
        self.assertTrue(all(item == "none" for _, _, item in outcomes))
        self.assertAlmostEqual(sum(p for p, d, _ in outcomes if d > 0), 90, places=4)
        self.assertAlmostEqual(sum(p for p, d, _ in outcomes if d > 70), 45, places=4)

    def test_armor_blocks_super_luck_crits(self):
        for ability in ("battlearmor", "shellarmor"):
            with self.subTest(ability=ability):
                outcomes = self.outcomes("skyattack", defender=ability)
                self.assertEqual(len({d for _, d, _ in outcomes if d > 0}), 1)

    def test_super_luck_increases_ko_probability_in_roll_branch(self):
        # 60 HP lies inside Sky Attack's noncritical damage range for these stats.
        ordinary = self.outcomes("skyattack", ability="none", hp=60)
        lucky = self.outcomes("skyattack", hp=60)
        ordinary_ko = sum(p for p, d, _ in ordinary if d == 60) / 90
        lucky_ko = sum(p for p, d, _ in lucky if d == 60) / 90
        # Remove the crit contribution: the remaining KO-roll fraction is identical.
        self.assertGreater(lucky_ko, ordinary_ko)
        self.assertAlmostEqual((lucky_ko - 0.5) / 0.5,
                               (ordinary_ko - 0.125) / 0.875, places=5)


if __name__ == "__main__":
    unittest.main()
