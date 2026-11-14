"""Exercise the turn limit in a real Showdown battle, including a last-turn KO."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TurnLimitTests(unittest.TestCase):
    def test_draw_and_residual_win_on_turn_100(self):
        subprocess.run(["node", "-e", SCRIPT], cwd=ROOT, check=True,
                       text=True, capture_output=True)


SCRIPT = r'''
const fs = require('fs');
const vm = require('vm');
const root = process.cwd();
const esbuild = require(root + '/pokemon-showdown/node_modules/esbuild');
const {Battle, Dex} = require(root + '/pokemon-showdown/dist/sim');
const context = {module: {exports: {}}, exports: {}};
vm.runInNewContext(esbuild.transformSync(fs.readFileSync('mechanics/custom-formats.ts', 'utf8'), {loader:'ts', format:'cjs'}).code, context);
const local = context.module.exports.Formats.find(f => f.onResidual);
const format = {...Dex.formats.get('gen9customgame'), ...local};
const assert = require('assert/strict');
function start() {
    const battle = new Battle({format, seed:[1,2,3,4]});
    for (const side of ['p1','p2']) battle.setPlayer(side, {name:side, team:[{species:'Magikarp', moves:['splash'], ability:'swiftswim'}]});
    battle.makeChoices();
    for (const side of battle.sides) side.active[0].moveSlots[0].pp = 1000;
    while (!battle.ended && battle.turn < 100) battle.makeChoices('move 1', 'move 1');
    assert.equal(battle.ended, false);
    assert.equal(battle.turn, 100);
    return battle;
}
const draw = start();
draw.makeChoices('move 1', 'move 1');
assert.equal(draw.turn, 100);
assert.equal(draw.ended, true);
assert.equal(draw.winner, '');
assert.ok(draw.log.includes('|tie'));
const win = start();
win.p1.active[0].setStatus('psn');
win.p1.active[0].hp = 1;
win.makeChoices('move 1', 'move 1');
assert.equal(win.ended, true);
assert.equal(win.winner, 'p2');
assert.ok(!win.log.includes('|tie'));
'''
