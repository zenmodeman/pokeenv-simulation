import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from poke_engine import Move, Pokemon, Side, State, SideConditions, generate_instructions

from foul_play_player import (FoulPlayPlayer, KnownSetMatch, Turn, battle_to_poke_engine_state,
                              healing_protect, select_search_move)


TEAMS = [
    "Iron Valiant @ Focus Sash\nAbility: Quark Drive\nEVs: 4 Def / 252 SpA / 252 Spe\nTimid Nature\n- Close Combat\n- Moonblast",
    "Dragonite @ Choice Band\nAbility: Multiscale\nAdamant Nature\n- Outrage\n- Earthquake",
]


def request(role, species, moves, ability, item, stats, hp):
    return {
        "rqid": 1,
        "active": [{"moves": [{"id": m, "move": m, "pp": 8, "maxpp": 8,
                                "target": "normal", "disabled": False} for m in moves],
                    "canTerastallize": "Fairy"}],
        "side": {"id": role, "pokemon": [{
            "ident": f"{role}: {species}", "details": species,
            "condition": f"{hp}/{hp}", "active": True, "stats": stats,
            "moves": moves, "baseAbility": ability, "ability": ability,
            "item": item, "teraType": "Fairy", "terastallized": "",
        }]},
    }


def requests():
    return {
        0: request("p1", "Iron Valiant", ["closecombat", "moonblast"], "quarkdrive",
                   "focussash", {"atk": 266, "def": 217, "spa": 339, "spd": 156, "spe": 364}, 289),
        1: request("p2", "Dragonite", ["outrage", "earthquake"], "multiscale",
                   "choiceband", {"atk": 403, "def": 226, "spa": 212, "spd": 236, "spe": 259}, 323),
    }


class HealingProtectTests(unittest.TestCase):
    def state(self, response="tackle", *, hp=250, protect=0, status="none", enemy_item="none"):
        return State(
            side_one=Side(pokemon=[Pokemon(id="tinglu", hp=hp, maxhp=496,
                item="leftovers", status=status, moves=[Move(id="protect")])],
                side_conditions=SideConditions(protect=protect)),
            side_two=Side(pokemon=[Pokemon(id="pikachu", hp=100, maxhp=200,
                item=enemy_item, attack=400, moves=[Move(id=response)])]))

    def result(self, response="tackle", visits=90, score=0.8):
        return SimpleNamespace(
            total_visits=visits + 100,
            side_one=[SimpleNamespace(move_choice="protect", visits=visits, total_score=visits * score),
                      SimpleNamespace(move_choice="payback", visits=100, total_score=80)],
            side_two=[SimpleNamespace(move_choice=response)])

    def test_prefers_competitive_guaranteed_healing(self):
        self.assertTrue(healing_protect(self.state(), self.result()))

    def test_rejects_full_hp_consecutive_protect_and_residual_damage(self):
        for state in (self.state(hp=496), self.state(protect=1), self.state(status="poison")):
            with self.subTest(state=state):
                self.assertFalse(healing_protect(state, self.result()))

    def test_rejects_setup_substitute_bypass_and_enemy_healing(self):
        for response in ("swordsdance", "substitute", "feint", "rest"):
            with self.subTest(response=response):
                self.assertFalse(healing_protect(self.state(response), self.result(response)))
        self.assertFalse(healing_protect(self.state(enemy_item="leftovers"), self.result()))

    def test_preserves_search_preference_when_protect_is_worse(self):
        self.assertFalse(healing_protect(self.state(), self.result(visits=74)))
        self.assertFalse(healing_protect(self.state(), self.result(score=0.7)))

    def test_consecutive_protect_gate_precedes_context_and_policy(self):
        for streak in (1, 2, 3):
            threshold = 1.0 - 3.0 ** -streak
            for roll, blocked in ((threshold - 0.00001, True), (threshold, False)):
                with self.subTest(streak=streak, roll=roll), \
                     patch("foul_play_player.random.random", return_value=roll), \
                     patch("foul_play_player.healing_protect", side_effect=lambda s, r:
                           any(o.move_choice == "protect" for o in r.side_one)), \
                     patch("foul_play_player.select_move_from_mcts_results",
                           side_effect=lambda results: max(results[0][0].side_one,
                                                          key=lambda o: o.visits).move_choice):
                    self.assertEqual(select_search_move(self.state(protect=streak), self.result()),
                                     "payback" if blocked else "protect")

    def test_first_protect_does_not_roll_gate(self):
        with patch("foul_play_player.random.random") as rng:
            self.assertEqual(select_search_move(self.state(), self.result()), "protect")
        rng.assert_not_called()

    def test_blocked_protect_can_use_unvisited_alternative(self):
        result = self.result()
        result.side_one[1].visits = 0
        with patch("foul_play_player.random.random", return_value=0):
            self.assertEqual(select_search_move(self.state(protect=1), result), "payback")

    def test_blocked_protect_without_alternative_fails_explicitly(self):
        result = self.result()
        result.side_one = result.side_one[:1]
        with patch("foul_play_player.random.random", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "no alternative"):
                select_search_move(self.state(protect=1), result)


class StateBridgeTests(unittest.TestCase):
    def setUp(self):
        self.match = KnownSetMatch(TEAMS, 50)
        self.first = Turn(requests=requests(), messages=[
            ["", "switch", "p1a: Iron Valiant", "Iron Valiant", "289/289"],
            ["", "switch", "p2a: Dragonite", "Dragonite", "100/100"],
            ["", "turn", "1"],
        ])
        self.match.prepare("test-battle", self.first)

    def test_exact_opponent_state_and_independent_perspectives(self):
        a, b = self.first.snapshots[0], self.first.snapshots[1]
        self.assertEqual(a.opponent.active.hp, 323)
        self.assertEqual(a.opponent.active.stats["attack"], 403)
        self.assertEqual(b.opponent.active.stats["special-attack"], 339)
        self.assertEqual(b.user.name, "p2")
        self.assertEqual(a.user.active.evs, (0, 0, 4, 252, 0, 252))
        a.user.active.hp = 1
        self.assertEqual(b.opponent.active.hp, 289)
        self.assertEqual(self.match.states["test-battle"].user.active.hp, 289)

    def test_stat_drops_pp_item_and_disabled_moves_reach_search(self):
        reqs = requests()
        reqs[0]["side"]["pokemon"][0]["condition"] = "101/289"
        reqs[0]["side"]["pokemon"][0]["item"] = ""
        reqs[0]["active"][0]["moves"][0]["pp"] = 7
        reqs[1]["active"][0]["moves"][1]["disabled"] = True
        turn = Turn(requests=reqs, messages=[
            ["", "move", "p1a: Iron Valiant", "Close Combat", "p2a: Dragonite"],
            ["", "-unboost", "p1a: Iron Valiant", "def", "1"],
            ["", "-unboost", "p1a: Iron Valiant", "spd", "1"],
            ["", "turn", "2"],
        ])
        self.match.prepare("test-battle", turn)
        state = battle_to_poke_engine_state(turn.snapshots[0])
        self.assertEqual(state.side_one.defense_boost, -1)
        self.assertEqual(state.side_one.special_defense_boost, -1)
        self.assertEqual(state.side_one.pokemon[0].hp, 101)
        self.assertEqual(state.side_one.pokemon[0].moves[0].pp, 7)
        self.assertEqual(state.side_one.pokemon[0].item.lower(), "none")
        self.assertTrue(state.side_two.pokemon[0].moves[1].disabled)
        reverse = battle_to_poke_engine_state(turn.snapshots[1])
        self.assertEqual(reverse.side_two.defense_boost, -1)

    def test_engine_models_close_combat_defensive_drops(self):
        state = battle_to_poke_engine_state(self.first.snapshots[0])
        branches = generate_instructions(state, "closecombat", "earthquake")
        self.assertTrue(branches)
        # At least one noncritical branch survives long enough to apply both drops.
        applied = False
        for branch in branches:
            outcome = state.apply_instructions(branch)
            applied |= (outcome.side_one.defense_boost == -1
                        and outcome.side_one.special_defense_boost == -1)
        self.assertTrue(applied)

    def test_search_returns_a_legal_action(self):
        result = self.match.search(self.first.snapshots[0])
        self.assertIn(result, {"closecombat", "moonblast"})

    def test_accuracy_and_evasion_stages_reach_engine(self):
        snapshot = self.first.snapshots[0]
        snapshot.user.active.boosts["accuracy"] = -2
        snapshot.opponent.active.boosts["evasion"] = 1
        with patch("foul_play_player.monte_carlo_tree_search", side_effect=RuntimeError("capture")) as search:
            with self.assertRaisesRegex(RuntimeError, "capture"):
                self.match.search(snapshot)
        state = search.call_args.args[0]
        self.assertEqual(state.side_one.accuracy_boost, -2)
        self.assertEqual(state.side_two.evasion_boost, 1)

    def test_search_disables_tera_for_both_sides_without_changing_active(self):
        with patch("foul_play_player.monte_carlo_tree_search", side_effect=RuntimeError("capture")) as search:
            with self.assertRaisesRegex(RuntimeError, "capture"):
                self.match.search(self.first.snapshots[0])
        state = search.call_args.args[0]
        from poke_engine import monte_carlo_tree_search
        result = monte_carlo_tree_search(state, 20, threads=1)
        for options in (result.side_one, result.side_two):
            self.assertFalse(any(option.move_choice.endswith("-tera") for option in options))
        self.assertFalse(state.side_one.pokemon[0].terastallized)
        self.assertFalse(state.side_two.pokemon[0].terastallized)

    def test_mega_choices_change_form_stats_ability_and_persist(self):
        teams = ["Charizard @ Charizardite X\nAbility: Blaze\nJolly Nature\n- Dragon Claw", TEAMS[1]]
        match = KnownSetMatch(teams, 50)
        reqs = requests()
        reqs[0] = request("p1", "Charizard", ["dragonclaw"], "blaze", "charizarditex",
                          {"atk": 204, "def": 192, "spa": 228, "spd": 206, "spe": 259}, 297)
        reqs[0]["active"][0]["canMegaEvo"] = True
        turn = Turn(requests=reqs)
        match.prepare("mega", turn)
        with patch("foul_play_player.monte_carlo_tree_search", side_effect=RuntimeError("capture")) as search:
            with self.assertRaisesRegex(RuntimeError, "capture"):
                match.search(turn.snapshots[0])
        state = search.call_args.args[0]
        from poke_engine import monte_carlo_tree_search
        result = monte_carlo_tree_search(state, 20, threads=1)
        self.assertIn("dragonclaw-mega", {o.move_choice for o in result.side_one})
        branches = generate_instructions(state, "dragonclaw-mega", "earthquake")
        evolved = state.apply_instructions(branches[0]).side_one.pokemon[0]
        self.assertEqual(evolved.id.lower(), "charizardmegax")
        self.assertEqual(evolved.ability.lower(), "toughclaws")
        self.assertTrue(evolved.mega_evolved)
        self.assertGreater(evolved.attack, state.side_one.pokemon[0].attack)
        reqs[0]["side"]["pokemon"][0].update(
            details="Charizard-Mega-X", ability="toughclaws",
            stats={"atk": 296, "def": 258, "spa": 270, "spd": 206, "spe": 259})
        reqs[0]["active"][0].pop("canMegaEvo")
        next_turn = Turn(requests=reqs, messages=[
            ["", "detailschange", "p1a: Charizard", "Charizard-Mega-X"],
            ["", "-mega", "p1a: Charizard", "Charizard", "Charizardite X"],
        ])
        match.prepare("mega", next_turn)
        for snapshot in next_turn.snapshots.values():
            active = snapshot.user.active if snapshot.user.name == "p1" else snapshot.opponent.active
            self.assertTrue(active.is_mega)
            self.assertEqual(active.stats["attack"], 296)
            self.assertEqual(active.ability, "toughclaws")

    def test_search_failure_is_explicit(self):
        with patch("foul_play_player.monte_carlo_tree_search", side_effect=RuntimeError("broken")):
            with self.assertRaisesRegex(RuntimeError, "broken"):
                self.match.search(self.first.snapshots[0])


class SynchronizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_sends_mega_order_and_rejects_tera(self):
        player = SimpleNamespace(
            match=SimpleNamespace(choose=AsyncMock(return_value="dragonclaw-mega")),
            side_index=0, requests={"mega": {}}, pending_messages={},
            create_order=Mock(return_value="order"), search_error=None)
        move = SimpleNamespace(id="dragonclaw")
        battle = SimpleNamespace(battle_tag="mega", available_moves=[move], can_mega_evolve=True)
        self.assertEqual(await FoulPlayPlayer.choose_move(player, battle), "order")
        player.create_order.assert_called_once_with(move, mega=True)
        player.match.choose.return_value = "dragonclaw-tera"
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await FoulPlayPlayer.choose_move(player, battle)
        player.match.choose.return_value = "dragonclaw-mega"
        battle.can_mega_evolve = False
        with self.assertRaisesRegex(RuntimeError, "unavailable Mega"):
            await FoulPlayPlayer.choose_move(player, battle)

    async def test_waits_for_both_private_requests_before_either_search(self):
        match = KnownSetMatch(TEAMS, 50)
        reqs = requests()
        battle = SimpleNamespace(battle_tag="sync-battle", turn=1)
        seen = []

        def search(snapshot):
            seen.append((snapshot.user.name, snapshot.opponent.active.hp,
                         snapshot.opponent.last_selected_move.move))
            return "closecombat" if snapshot.user.name == "p1" else "outrage"

        with patch.object(match, "search", side_effect=search):
            first = asyncio.create_task(match.choose(0, battle, reqs[0], []))
            await asyncio.sleep(0)
            self.assertEqual(seen, [])
            second = asyncio.create_task(match.choose(1, battle, reqs[1], []))
            self.assertEqual(await asyncio.gather(first, second), ["closecombat", "outrage"])
        self.assertCountEqual(seen, [("p1", 323, ""), ("p2", 289, "")])


if __name__ == "__main__":
    unittest.main()
