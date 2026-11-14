import csv
from pathlib import Path
import tempfile
import unittest

from attempt import standings, write_standings


class StandingsTests(unittest.TestCase):
    def test_totals_order_and_shared_ranks(self):
        rows = [
            dict(set_a="A", set_b="B", battles=4, a_wins=1, b_wins=2, ties=1),
            dict(set_a="C", set_b="A", battles=4, a_wins=2, b_wins=1, ties=1),
            dict(set_a="B", set_b="C", battles=4, a_wins=1, b_wins=1, ties=2),
        ]
        ranked = standings(rows)
        self.assertEqual([r["team"] for r in ranked], ["B", "C", "A"])
        self.assertEqual([r["points"] for r in ranked], [4.5, 4.5, 3])
        for entry in ranked:
            self.assertEqual(entry["battles"], 8)
            self.assertEqual(entry["wins"] + entry["losses"] + entry["ties"], 8)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "standings.csv"
            write_standings(rows, output)
            with output.open() as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual([r["rank"] for r in saved], ["1", "1", "3"])


if __name__ == "__main__":
    unittest.main()
