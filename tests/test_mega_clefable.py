"""Mega timing must account for the ability and typing lost and gained."""
import unittest

from poke_engine import Move, Pokemon, Side, State, generate_instructions, monte_carlo_tree_search


class MegaClefableTests(unittest.TestCase):
    def state(self, move, **boosts):
        return State(
            side_one=Side(pokemon=[Pokemon(id="clefable", item="clefablite",
                ability="unaware", types=("fairy", "typeless"), hp=394, maxhp=394,
                defense=200, special_defense=200, speed=100,
                moves=[Move(id="splash")])]),
            side_two=Side(pokemon=[Pokemon(id="mew", types=("psychic", "typeless"),
                hp=400, maxhp=400, attack=200, special_attack=200, speed=200,
                moves=[Move(id=move)])], **boosts))

    def outcomes(self, state, move, mega):
        return [(b.percentage, state.apply_instructions(b))
                for b in generate_instructions(state, "splash-mega" if mega else "splash", move)
                if b.percentage > 0]

    def damage(self, state, move, mega):
        return sum(p * (394 - o.side_one.pokemon[0].hp)
                   for p, o in self.outcomes(state, move, mega)) / 100

    def test_search_keeps_both_mega_and_base_choices(self):
        result = monte_carlo_tree_search(self.state("thunderbolt"), 20, threads=1)
        self.assertTrue({"splash", "splash-mega"} <= {o.move_choice for o in result.side_one})

    def test_unaware_is_lost_on_mega_evolution(self):
        for move, stat in (("psychic", "special_attack_boost"), ("tackle", "attack_boost")):
            with self.subTest(move=move):
                normal = self.state(move)
                boosted = self.state(move, **{stat: 6})
                self.assertAlmostEqual(self.damage(normal, move, False),
                                       self.damage(boosted, move, False))
                self.assertGreater(self.damage(boosted, move, True),
                                   self.damage(boosted, move, False))

    def test_flying_weaknesses_and_ground_immunity(self):
        for move in ("thunderbolt", "icebeam", "rockslide"):
            with self.subTest(move=move):
                state = self.state(move)
                self.assertGreater(self.damage(state, move, True), self.damage(state, move, False))
        state = self.state("earthquake")
        self.assertEqual(self.damage(state, "earthquake", True), 0)
        self.assertGreater(self.damage(state, "earthquake", False), 0)

    def test_magic_bounce_works_on_the_evolution_turn(self):
        for move in ("toxic", "screech"):
            state = self.state(move)
            base = [o for _, o in self.outcomes(state, move, False)]
            mega = [o for _, o in self.outcomes(state, move, True)]
            if move == "toxic":
                self.assertTrue(any(o.side_one.pokemon[0].status.lower() == "toxic" for o in base))
                self.assertTrue(all(o.side_one.pokemon[0].status.lower() == "none" for o in mega))
                self.assertTrue(any(o.side_two.pokemon[0].status.lower() == "toxic" for o in mega))
            else:
                self.assertTrue(any(o.side_one.defense_boost == -2 for o in base))
                self.assertTrue(all(o.side_one.defense_boost == 0 for o in mega))
                self.assertTrue(any(o.side_two.defense_boost == -2 for o in mega))
            self.assertTrue(all(o.side_one.pokemon[0].ability.lower() == "magicbounce" for o in mega))
