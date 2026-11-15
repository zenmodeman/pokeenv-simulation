"""Leek crit stages must affect the compiled search engine's damage branches."""
import unittest

from poke_engine import Move, Pokemon, Side, State, generate_instructions


class LeekTests(unittest.TestCase):
    def outcomes(self, move, item="leek", species="sirfetchd", ability="scrappy",
                 defender="none", hp=1000):
        attacker = Pokemon(id=species, hp=1000, maxhp=1000, ability=ability,
                           item=item, attack=200, speed=200, moves=[Move(id=move)])
        target = Pokemon(id="snorlax", hp=hp, maxhp=hp, ability=defender,
                         defense=200, speed=100, moves=[Move(id="splash")])
        state = State(side_one=Side(pokemon=[attacker]), side_two=Side(pokemon=[target]))
        outcomes = []
        for branch in generate_instructions(state, move, "splash"):
            result = state.apply_instructions(branch)
            if branch.percentage > 0:
                outcomes.append((branch.percentage, hp - result.side_two.pokemon[0].hp))
        self.assertAlmostEqual(sum(p for p, _ in outcomes), 100, places=4)
        return outcomes

    def assert_rate(self, move, expected, **kwargs):
        outcomes = self.outcomes(move, **kwargs)
        damage = sorted({d for _, d in outcomes})
        self.assertEqual(len(damage), 2)
        self.assertAlmostEqual(sum(p for p, d in outcomes if d == damage[-1]),
                               expected * 100, places=4)

    def test_high_crit_moves_are_guaranteed(self):
        for species in ("sirfetchd", "farfetchd", "farfetchdgalar"):
            for move in ("nightslash", "leafblade"):
                with self.subTest(species=species, move=move):
                    outcomes = self.outcomes(move, species=species)
                    self.assertEqual(len({d for _, d in outcomes}), 1)
                    normal = self.outcomes(move, species=species, item="none")
                    self.assertEqual(outcomes[0][1], max(d for _, d in normal))

    def test_ordinary_moves_have_fifty_percent_crits(self):
        self.assert_rate("tackle", 0.5)

    def test_requires_item_and_matching_species(self):
        self.assert_rate("nightslash", 0.125, item="none")
        self.assert_rate("leafblade", 0.125, species="snorlax")
        self.assert_rate("leafblade", 0.125, ability="klutz")

    def test_armor_blocks_crits(self):
        for ability in ("battlearmor", "shellarmor"):
            with self.subTest(ability=ability):
                outcomes = self.outcomes("leafblade", defender=ability)
                ordinary = self.outcomes("leafblade", defender=ability, item="none")
                self.assertEqual(outcomes, ordinary)

    def test_guaranteed_crit_in_ko_roll_branch(self):
        # The average ordinary damage lies within the noncritical roll range.
        hp = min(d for _, d in self.outcomes("nightslash", item="none"))
        normal = self.outcomes("nightslash", item="none", hp=hp)
        self.assertTrue(any(d < hp for _, d in normal))
        self.assertTrue(all(d == hp for _, d in self.outcomes("nightslash", hp=hp)))


if __name__ == "__main__":
    unittest.main()
