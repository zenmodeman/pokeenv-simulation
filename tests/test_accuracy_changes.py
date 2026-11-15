"""Check the custom profile against actual engine chance branches and Showdown."""
import json
from pathlib import Path
import subprocess
import unittest

import poke_engine
from poke_engine import Move, Pokemon, Side, State, generate_instructions

ROOT = Path(__file__).resolve().parents[1]
ACCURACY_CHANGES = {
    "skyattack": 90,
    "highhorsepower": 95,
    "sandtomb": 85,
    "playrough": 90,
    "ruination": 90,
    "drillrun": 95,
    "whirlpool": 85,
    "screech": 85,
    "meteorbeam": 90,
}


class AccuracyChangesTests(unittest.TestCase):
    def tearDown(self):
        poke_engine.set_accuracy_changes(False)

    def hit_probability(self, move, enabled, accuracy=0):
        poke_engine.set_accuracy_changes(enabled)
        attacker = Pokemon(id="mudsdale", hp=1000, maxhp=1000, item="powerherb",
                           attack=200, speed=200, moves=[Move(id=move)])
        target = Pokemon(id="snorlax", hp=1000, maxhp=1000, defense=200,
                         speed=100, moves=[Move(id="splash")])
        state = State(side_one=Side(pokemon=[attacker], accuracy_boost=accuracy),
                      side_two=Side(pokemon=[target]))
        return sum(branch.percentage for branch in generate_instructions(state, move, "splash")
                   if (state.apply_instructions(branch).side_two.defense_boost < 0 if move == "screech"
                       else state.apply_instructions(branch).side_two.pokemon[0].hp < 1000))

    def test_all_moves_and_restoring_standard_rules(self):
        for move, baseline in ACCURACY_CHANGES.items():
            with self.subTest(move=move):
                self.assertAlmostEqual(self.hit_probability(move, False), baseline, places=4)
                self.assertAlmostEqual(self.hit_probability(move, True), 100, places=4)
                self.assertAlmostEqual(self.hit_probability(move, False), baseline, places=4)

    def test_accuracy_stages_still_apply_and_other_moves_are_unchanged(self):
        for move in ACCURACY_CHANGES:
            self.assertAlmostEqual(self.hit_probability(move, True, accuracy=-1), 75, places=4)
        self.assertAlmostEqual(self.hit_probability("stoneedge", True), 80, places=4)

    def test_showdown_format_changes_all_moves_without_mutating_base_data(self):
        # Load the shipped format using Showdown's own TypeScript compiler and Dex.
        script = r'''
const fs = require('fs');
const vm = require('vm');
const esbuild = require('./pokemon-showdown/node_modules/esbuild');
const {Dex} = require('./pokemon-showdown/dist/sim/dex');
const source = fs.readFileSync('mechanics/custom-formats.ts', 'utf8');
const compiled = esbuild.transformSync(source, {loader: 'ts', format: 'cjs'}).code;
const context = {module: {exports: {}}, exports: {}};
vm.runInNewContext(compiled, context);
const format = context.module.exports.Formats.find(f => f.onModifyMove);
const result = {};
for (const id of ['skyattack', 'highhorsepower', 'sandtomb', 'playrough', 'ruination', 'drillrun', 'whirlpool', 'screech', 'meteorbeam', 'stoneedge']) {
    const move = {...Dex.moves.get(id)};
    format.onModifyMove(move);
    result[id] = [move.accuracy, Dex.moves.get(id).accuracy];
}
console.log(JSON.stringify(result));
'''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                                text=True, capture_output=True)
        self.assertEqual(json.loads(result.stdout), {
            **{move: [100, baseline] for move, baseline in ACCURACY_CHANGES.items()},
            "stoneedge": [80, 80],
        })
