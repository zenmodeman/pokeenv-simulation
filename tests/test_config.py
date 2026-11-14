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

    def test_timeout_scales_and_explicit_value_is_a_floor(self):
        original = load_config(ROOT / "sets.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sets.json"
            for battles, search, explicit, expected in [
                (20, 100, None, 3200),
                (40, 500, 300, 16000),
                (20, 100, 9000, 9000),
            ]:
                config = dict(original, battles_per_pair=battles, search_time_ms=search)
                config.pop("timeout_seconds", None)
                if explicit is not None:
                    config["timeout_seconds"] = explicit
                path.write_text(json.dumps(config))
                self.assertEqual(load_config(path)["timeout_seconds"], expected)
            for invalid in (True, 0, -1, "300"):
                path.write_text(json.dumps(dict(original, timeout_seconds=invalid)))
                with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                    load_config(path)

    def test_bundled_toml(self):
        config = load_config(ROOT / "sets.toml")
        self.assertGreaterEqual(len(config["sets"]), 2)


if __name__ == "__main__":
    unittest.main()
