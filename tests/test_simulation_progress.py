import asyncio
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from attempt import simulate
from simulation_progress import Progress, save_controls


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(sets=[dict(name=n, team=n) for n in "ABC"],
                           battles_per_pair=5, search_time_ms=1, timeout_seconds=5)

    def players(self, progress, checkpoint, *, interrupt=False, draws=False, stop_after=2):
        players, challengers = [], []

        def create(**kwargs):
            player = SimpleNamespace(n_finished_battles=0, n_won_battles=0,
                                     search_error=None,
                                     stop=AsyncMock())
            players.append(player)

            async def battle_against(opponent, n_battles):
                if interrupt and len(challengers) == stop_after:
                    progress.save(checkpoint)
                    raise RuntimeError("interrupted")
                challengers.append((kwargs["team"], opponent.team))
                player.n_finished_battles += 1
                opponent.n_finished_battles += 1
                if not draws:
                    player.n_won_battles += 1

            player.team = kwargs["team"]
            player.battle_against = battle_against
            return player

        return create, challengers, players

    def run_simulation(self, progress, output, factory):
        with patch("attempt.FoulPlayPlayer", side_effect=factory), \
                patch("attempt.KnownSetMatch"), \
                patch.dict("sys.modules", {"poke_engine": SimpleNamespace()}):
            return asyncio.run(simulate(self.config, output, False, progress))

    def test_resume_mid_pair_preserves_counts_challenger_and_completed_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "save.json", Path(directory) / "results.csv"
            progress = Progress(self.config, False)
            factory, _, players = self.players(progress, path, interrupt=True)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.run_simulation(progress, output, factory)
            for player in players:
                player.stop.assert_awaited_once()
            resumed = Progress.load(path, self.config, False)
            self.assertEqual(resumed.rows[0]["battles"], 2)
            factory, calls, _ = self.players(resumed, path)
            rows = self.run_simulation(resumed, output, factory)
            self.assertEqual(calls[:3], [("A", "B"), ("B", "A"), ("A", "B")])
            self.assertEqual(len(calls), 13)
            self.assertEqual([(r["a_wins"], r["b_wins"], r["battles"])
                              for r in rows], [(3, 2, 5)] * 3)
            with output.open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 3)
            resumed.save(path)
            final = Progress.load(path, self.config, False)
            factory, calls, _ = self.players(final, path)
            output.unlink()
            self.run_simulation(final, output, factory)
            self.assertEqual(calls, [])
            self.assertTrue(output.exists())

    def test_draw_shortcut_spans_resume_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "save.json", Path(directory) / "results.csv"
            progress = Progress(self.config, False)
            factory, _, _ = self.players(progress, path, interrupt=True, draws=True)
            with self.assertRaises(RuntimeError):
                self.run_simulation(progress, output, factory)
            resumed = Progress.load(path, self.config, False)
            factory, calls, _ = self.players(resumed, path, draws=True)
            rows = self.run_simulation(resumed, output, factory)
            self.assertEqual(len(calls), 7)  # one remaining draw, then three per new pair
            self.assertEqual([r["ties"] for r in rows], [5, 5, 5])

    def test_resume_skips_completed_pair_before_partial_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "save.json", Path(directory) / "results.csv"
            progress = Progress(self.config, False)
            factory, _, _ = self.players(progress, path, interrupt=True, stop_after=7)
            with self.assertRaises(RuntimeError):
                self.run_simulation(progress, output, factory)
            resumed = Progress.load(path, self.config, False)
            self.assertEqual([r["battles"] for r in resumed.rows], [5, 2])
            factory, calls, _ = self.players(resumed, path)
            self.run_simulation(resumed, output, factory)
            self.assertEqual(len(calls), 8)
            self.assertEqual(calls[0], ("A", "C"))
            self.assertNotIn(("A", "B"), calls)
            self.assertNotIn(("B", "A"), calls)

    def test_checkpoint_rejects_incompatible_settings_and_bad_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            Progress(self.config, False).save(path)
            for field, value in (("battles_per_pair", 6), ("search_time_ms", 2),
                                 ("sets", list(reversed(self.config["sets"])))):
                config = dict(self.config, **{field: value})
                with self.assertRaisesRegex(ValueError, "do not match"):
                    Progress.load(path, config, False)
            with self.assertRaises(ValueError):
                Progress.load(path, self.config, True)
            payload = json.loads(path.read_text())
            payload["rows"] = [dict(set_a="A", set_b="B", battles=2,
                                    a_wins=2, b_wins=1, ties=0)]
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                Progress.load(path, self.config, False)

    def test_failed_save_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            progress = Progress(self.config, False)
            progress.save(path)
            previous = path.read_bytes()
            with patch("simulation_progress.json.dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    progress.save(path)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    @unittest.skipUnless(os.name == "posix", "POSIX terminal controls")
    def test_single_key_prompt_confirmation_cancellation_and_terminal_restore(self):
        import pty
        import termios
        master, slave = pty.openpty()
        try:
            with os.fdopen(os.dup(slave)) as terminal, tempfile.TemporaryDirectory() as directory:
                original = termios.tcgetattr(slave)
                path = Path(directory) / "save.json"
                progress = Progress(self.config, False)

                async def exercise():
                    with patch.object(sys, "stdin", terminal):
                        with save_controls(asyncio.get_running_loop(), progress, path):
                            os.write(master, b"sn")
                            await asyncio.sleep(0.03)
                            self.assertFalse(path.exists())
                            os.write(master, b"s")
                            await asyncio.sleep(0.03)
                            self.assertFalse(path.exists())
                            os.write(master, b"y")
                            await asyncio.sleep(0.03)
                            self.assertTrue(path.exists())
                asyncio.run(exercise())
                self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            os.close(master)
            os.close(slave)
