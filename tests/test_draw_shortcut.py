import asyncio
import csv
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from attempt import simulate, standings


class DrawShortcutTests(unittest.TestCase):
    def run_matchups(self, outcomes, battle_count=5, set_count=2):
        players = []
        calls = []

        def make_player(**kwargs):
            player = SimpleNamespace(
                n_finished_battles=0, n_won_battles=0, search_error=None,
                stop=AsyncMock(),
            )

            async def battle_against(opponent, n_battles):
                pair = players.index(player) // 2
                a, b = players[pair * 2:pair * 2 + 2]
                winner = outcomes[a.n_finished_battles]
                calls.append(pair)
                a.n_finished_battles += 1
                b.n_finished_battles += 1
                if winner == "a":
                    a.n_won_battles += 1
                elif winner == "b":
                    b.n_won_battles += 1

            player.battle_against = battle_against
            players.append(player)
            return player

        config = dict(sets=[dict(name=str(i), team=str(i)) for i in range(set_count)],
                      battles_per_pair=battle_count, search_time_ms=1, timeout_seconds=5)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.csv"
            with patch("attempt.FoulPlayPlayer", side_effect=make_player), \
                    patch("attempt.KnownSetMatch"), \
                    patch.dict("sys.modules", {"poke_engine": SimpleNamespace()}):
                rows = asyncio.run(simulate(config, output, accuracy_changes=False))
            with output.open() as handle:
                saved = list(csv.DictReader(handle))
        return rows, saved, calls

    def test_three_initial_draws_count_full_schedule_for_each_pair(self):
        rows, saved, calls = self.run_matchups([None] * 5, set_count=3)
        self.assertEqual(calls, [0] * 3 + [1] * 3 + [2] * 3)
        for row, stored in zip(rows, saved):
            self.assertEqual((row["battles"], row["ties"], row["a_wins"], row["b_wins"]),
                             (5, 5, 0, 0))
            self.assertEqual(stored["ties"], "5")
        self.assertTrue(all(entry["points"] == 5 for entry in standings(rows)))

    def test_early_win_prevents_shortcut_even_with_later_draws(self):
        for winner in ("a", "b"):
            with self.subTest(winner=winner):
                rows, _, calls = self.run_matchups([None, winner, None, None, None])
                self.assertEqual(len(calls), 5)
                self.assertEqual(rows[0]["ties"], 4)
                self.assertEqual(rows[0][f"{winner}_wins"], 1)

    def test_short_schedule_only_counts_configured_battles(self):
        rows, _, calls = self.run_matchups([None] * 2, battle_count=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(rows[0]["ties"], 2)
