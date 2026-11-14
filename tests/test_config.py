import json
from pathlib import Path
import tempfile
import unittest

from attempt import ROOT, load_config


class ConfigTests(unittest.TestCase):
    def test_multiline_toml_matches_json(self):
        with tempfile.TemporaryDirectory() as directory:
            toml_path = Path(directory) / "sets.toml"
            toml_path.write_text("""battles_per_pair = 2
[[sets]]
name = "Garchomp"
team = '''
Garchomp @ Choice Scarf
Ability: Rough Skin
- Earthquake
'''
[[sets]]
name = "Dragonite"
team = '''
Dragonite @ Choice Band
Ability: Multiscale
- Outrage
'''
""", encoding="utf-8")
            config = load_config(toml_path)
            self.assertEqual(config["sets"][0]["team"],
                             "Garchomp @ Choice Scarf\nAbility: Rough Skin\n- Earthquake")
            self.assertEqual(config["search_time_ms"], 100)
            json_path = Path(directory) / "sets.json"
            json_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(load_config(json_path), config)

            toml_path.write_text(toml_path.read_text().replace(
                "name = \"Dragonite\"", "name = \"Garchomp\""))
            with self.assertRaisesRegex(ValueError, "unique"):
                load_config(toml_path)

    def test_bundled_toml(self):
        config = load_config(ROOT / "sets.toml")
        self.assertGreaterEqual(len(config["sets"]), 2)


if __name__ == "__main__":
    unittest.main()
