"""Mechanics and known-set policy regressions from the simulation-log audit."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from poke_engine import Move, Pokemon, Side, State, VolatileStatusDurations, generate_instructions
from foul_play_player import (KnownSetMatch, Turn, exclude_reflected_status_moves,
                              ineffective_search_moves, select_search_move)
from test_foul_play import request


def outcomes(state, move='splash', response='splash'):
    return [(b.percentage, state.apply_instructions(b))
            for b in generate_instructions(state, move, response) if b.percentage > 0]


def policy(moves, responses=('splash',)):
    return NS(side_one=[NS(move_choice=m, visits=100, total_score=50) for m in moves],
              side_two=[NS(move_choice=m, visits=100, total_score=50) for m in responses], total_visits=100 * len(moves))


def duel(moves=('charm', 'shadowball'), responses=('splash',), *, types=('normal', 'typeless'),
         enemy_ability='none', user_ability='none', user_hp=400, enemy_hp=400,
         special_defense_boost=0, enemy_speed=100, user_speed=200):
    return State(side_one=Side(pokemon=[Pokemon(hp=user_hp, maxhp=400, speed=user_speed,
        ability=user_ability, moves=[Move(id=m) for m in moves]), Pokemon(hp=0, terastallized=True)]),
        side_two=Side(pokemon=[Pokemon(hp=enemy_hp, maxhp=400, speed=enemy_speed,
        types=types, ability=enemy_ability, moves=[Move(id=m) for m in responses]),
        Pokemon(hp=0, terastallized=True)], special_defense_boost=special_defense_boost))


class CustapTests(unittest.TestCase):
    def state(self, hp=150, ability='gluttony', *, both=False, enemy_move='firelash', user_move='shadowball'):
        return State(side_one=Side(pokemon=[Pokemon(types=('ghost', 'typeless'),
            hp=1 if not both else 100, maxhp=400, item='custapberry' if both else 'none',
            speed=339, special_attack=500, moves=[Move(id=user_move)])]),
            side_two=Side(pokemon=[Pokemon(types=('fire', 'typeless'),hp=hp, maxhp=400,
            speed=166, attack=500, special_defense=100, ability=ability,
            item='custapberry',moves=[Move(id=enemy_move)])]))

    def test_gluttony_and_exact_thresholds(self):
        for hp, ability, first in [(200, 'gluttony', True), (201, 'gluttony', False),
                                    (100, 'none', True), (101, 'none', False)]:
            with self.subTest(hp=hp, ability=ability):
                for _, o in outcomes(self.state(hp, ability), 'shadowball', 'firelash'):
                    self.assertEqual(o.side_one.pokemon[0].hp == 0, first)
                    self.assertEqual(o.side_two.pokemon[0].item.lower() == 'none', first)

    def test_both_activate_and_speed_breaks_tie(self):
        for _, o in outcomes(self.state(100, both=True), 'shadowball', 'firelash'):
            self.assertEqual(o.side_two.pokemon[0].hp, 0)
            self.assertEqual(o.side_one.pokemon[0].item.lower(), 'none')
            self.assertEqual(o.side_two.pokemon[0].item.lower(), 'none')

    def test_consumed_even_across_priority_brackets(self):
        s = self.state(user_move='protect')
        for _, o in outcomes(s, 'protect', 'firelash'):
            self.assertEqual(o.side_two.pokemon[0].item.lower(), 'none')
            self.assertEqual(o.side_one.pokemon[0].hp, 1)
        # A berry never promotes an ordinary move above priority attacks.
        s = self.state(user_move='shadowsneak')
        for _, o in outcomes(s, 'shadowsneak', 'firelash'):
            self.assertEqual(o.side_one.pokemon[0].item.lower(), 'none')
            self.assertEqual(o.side_two.pokemon[0].item.lower(), 'none')

    def test_symmetric_turn_order(self):
        s = self.state()
        s = State(side_one=s.side_two, side_two=s.side_one)
        for _, o in outcomes(s, 'firelash', 'shadowball'):
            self.assertEqual(o.side_two.pokemon[0].hp, 0)
            self.assertEqual(o.side_one.pokemon[0].item.lower(), 'none')


class BindingTests(unittest.TestCase):
    def state(self, elapsed=0, *, item='none', ability='none', source_hp=1000, protect=False):
        return State(side_one=Side(pokemon=[Pokemon(hp=1000, maxhp=1000, ability=ability,
            moves=[Move(id='splash'), Move(id='protect')])],
            volatile_statuses={'partiallytrapped'},
            volatile_status_durations=VolatileStatusDurations(partiallytrapped=elapsed)),
            side_two=Side(pokemon=[Pokemon(hp=source_hp, maxhp=1000, item=item,
                moves=[Move(id='splash')])]))

    def test_four_or_five_ticks_and_state_is_reversible(self):
        initial = self.state().to_string()
        s = self.state()
        for age in range(1, 5):
            branches = outcomes(s)
            self.assertAlmostEqual(sum(p for p, _ in branches), 100)
            self.assertEqual({o.side_one.pokemon[0].hp for _, o in branches}, {1000 - 125 * age})
            s = branches[0][1]
            self.assertEqual(s.side_one.volatile_status_durations.partiallytrapped, age)
        branches = outcomes(s)
        self.assertAlmostEqual(sum(p for p, o in branches if
            'PARTIALLYTRAPPED' not in o.side_one.volatile_statuses), 50)
        self.assertEqual({o.side_one.pokemon[0].hp for _, o in branches}, {375, 500})
        final_tick = next(o for _, o in branches if 'PARTIALLYTRAPPED' in o.side_one.volatile_statuses)
        self.assertTrue(all('PARTIALLYTRAPPED' not in o.side_one.volatile_statuses
                            and o.side_one.pokemon[0].hp == 375 for _, o in outcomes(final_tick)))
        self.assertEqual(self.state().to_string(), initial)

    def test_grip_claw_binding_band_magic_guard_and_protect(self):
        for _, o in outcomes(self.state(elapsed=4, item='gripclaw')):
            self.assertIn('PARTIALLYTRAPPED', o.side_one.volatile_statuses)
        self.assertTrue(all('PARTIALLYTRAPPED' not in o.side_one.volatile_statuses
                            for _, o in outcomes(self.state(elapsed=7, item='gripclaw'))))
        self.assertTrue(all(o.side_one.pokemon[0].hp == 834
                            for _, o in outcomes(self.state(item='bindingband'))))
        self.assertTrue(all(o.side_one.pokemon[0].hp == 1000 and
                            o.side_one.volatile_status_durations.partiallytrapped == 1
                            for _, o in outcomes(self.state(ability='magicguard'))))
        self.assertTrue(all(o.side_one.pokemon[0].hp == 875
                            for _, o in outcomes(self.state(), 'protect')))

    def test_source_faint_removes_binding_before_residual_damage(self):
        s = self.state(elapsed=2)
        enemy = Pokemon(hp=1,maxhp=1000,types=('ghost','typeless'),moves=[Move(id='splash')])
        user = Pokemon(hp=1000,maxhp=1000,speed=200,moves=[Move(id='shadowball')])
        s = State(side_one=Side(pokemon=[user], volatile_statuses={'partiallytrapped'},
                  volatile_status_durations=s.side_one.volatile_status_durations),
                  side_two=Side(pokemon=[enemy]))
        for _, o in outcomes(s, 'shadowball'):
            self.assertEqual(o.side_one.pokemon[0].hp, 1000)
            self.assertNotIn('PARTIALLYTRAPPED', o.side_one.volatile_statuses)
            self.assertEqual(o.side_one.volatile_status_durations.partiallytrapped, 0)

    def test_round_trip_serialization(self):
        s = self.state(elapsed=3)
        self.assertEqual(State.from_string(s.to_string()).side_one
                         .volatile_status_durations.partiallytrapped, 3)

    def test_protocol_tracks_elapsed_ticks_in_both_perspectives(self):
        teams = ['Mismagius\nAbility: Levitate\n- Shadow Ball',
                 'Dondozo\nAbility: Oblivious\n- Whirlpool']
        stats = {'atk':100,'def':100,'spa':100,'spd':100,'spe':100}
        reqs = {0:request('p1','Mismagius',['shadowball'],'levitate','',stats,272),
                1:request('p2','Dondozo',['whirlpool'],'oblivious','',stats,491)}
        match = KnownSetMatch(teams,20)
        match.prepare('binding',Turn(requests=reqs))
        t = Turn(requests=reqs,messages=[['','-activate','p1a: Mismagius','move: Whirlpool',
                                        '[of] p2a: Dondozo'],['','upkeep']])
        match.prepare('binding',t)
        from foul_play_player import battle_to_poke_engine_state
        for i, name in [(0,'side_one'),(1,'side_two')]:
            engine = battle_to_poke_engine_state(t.snapshots[i])
            self.assertEqual(getattr(engine,name).volatile_status_durations.partiallytrapped,1)
        match.prepare('binding',Turn(requests=reqs,messages=[['','upkeep']]))
        self.assertEqual(match.states['binding'].user.active.volatile_status_durations['partiallytrapped'],2)
        match.prepare('binding',Turn(requests=reqs,messages=[
            ['','-end','p1a: Mismagius','Whirlpool','[partiallytrapped]'],['','upkeep']]))
        self.assertEqual(match.states['binding'].user.active.volatile_status_durations['partiallytrapped'],0)


class SearchDiagnosticsTests(unittest.TestCase):
    def test_search_logs_both_policies_and_a_replayable_flagged_state(self):
        teams = ['Mismagius\nAbility: Levitate\n- Shadow Ball',
                 'Glimmora\nAbility: Corrosion\n- Power Gem']
        stats = {'atk':100,'def':100,'spa':100,'spd':100,'spe':100}
        reqs = {0:request('p1','Mismagius',['shadowball'],'levitate','',stats,272),
                1:request('p2','Glimmora',['powergem'],'corrosion','',stats,370)}
        match = KnownSetMatch(teams,20)
        t = Turn(requests=reqs)
        match.prepare('diagnostics',t)
        r = policy(('shadowball',),('powergem',))
        r.side_one[0].total_score = 0
        with patch('foul_play_player.monte_carlo_tree_search',return_value=r), \
             self.assertLogs('simulation',level='INFO') as logs:
            match.search(t.snapshots[0])
        combined = '\n'.join(logs.output)
        self.assertIn('"side_one"',combined)
        self.assertIn('"side_two"',combined)
        replay = next(line.split(' state=',1)[1] for line in logs.output if 'Search replay' in line)
        self.assertEqual(State.from_string(replay).side_one.pokemon[0].id.lower(),'mismagius')


class RestTests(unittest.TestCase):
    def test_full_hp_rest_does_not_sleep_or_consume_chesto(self):
        s = State(side_one=Side(pokemon=[Pokemon(hp=400,maxhp=400,item='chestoberry',
            moves=[Move(id='rest')])]),side_two=Side(pokemon=[Pokemon(moves=[Move(id='splash')])]))
        for _, o in outcomes(s,'rest'):
            self.assertEqual(o.side_one.pokemon[0].status.lower(),'none')
            self.assertEqual(o.side_one.pokemon[0].item.lower(),'chestoberry')
            self.assertEqual(o.side_one.pokemon[0].rest_turns,0)

    def test_injured_rest_cures_status_and_consumes_chesto(self):
        s = State(side_one=Side(pokemon=[Pokemon(hp=200,maxhp=400,status='poison',item='chestoberry',
            moves=[Move(id='rest')])]),side_two=Side(pokemon=[Pokemon(moves=[Move(id='splash')])]))
        for _, o in outcomes(s,'rest'):
            self.assertEqual(o.side_one.pokemon[0].hp,400)
            self.assertEqual(o.side_one.pokemon[0].status.lower(),'none')
            self.assertEqual(o.side_one.pokemon[0].item.lower(),'none')


class KnownSetPolicyTests(unittest.TestCase):
    def test_charm_with_status_moves_and_alternative_damage_stats(self):
        for responses in [('mindreader','sheercold','ancientpower','roost'),
                          ('rest','sleeptalk','whirlpool','nobleroar'),
                          ('toxic','moonlight','foulplay','screech'),('bodypress',)]:
            with self.subTest(responses=responses):
                s = exclude_reflected_status_moves(duel(responses=responses))
                self.assertTrue(s.side_one.pokemon[0].moves[0].disabled)

    def test_charm_kept_when_special_attacker_must_struggle(self):
        s = duel(responses=('powergem',))
        enemy = Pokemon(moves=[Move(id='powergem',pp=0)])
        s = State(side_one=s.side_one,side_two=Side(pokemon=[enemy]))
        self.assertFalse(exclude_reflected_status_moves(s).side_one.pokemon[0].moves[0].disabled)

    def test_toxic_poison_steel_immunity_and_corrosion(self):
        for types in [('poison','rock'), ('steel','flying')]:
            s = duel(moves=('toxic','darkpulse'),types=types)
            self.assertIn('toxic',ineffective_search_moves(s,policy(('toxic','darkpulse'))))
            s = duel(moves=('toxic','darkpulse'),types=types,user_ability='corrosion')
            self.assertNotIn('toxic',ineffective_search_moves(s,policy(('toxic','darkpulse'))))

    def test_capped_debuffs_and_contrary(self):
        s = duel(moves=('faketears','darkpulse'),special_defense_boost=-6)
        self.assertIn('faketears',ineffective_search_moves(s,policy(('faketears','darkpulse'))))
        s = duel(moves=('faketears','darkpulse'),special_defense_boost=-6,enemy_ability='contrary')
        self.assertNotIn('faketears',ineffective_search_moves(s,policy(('faketears','darkpulse'))))

    def test_immune_attacks_and_faster_roost(self):
        s = duel(moves=('sludgebomb','earthpower','powergem'),responses=('roost','bravebird'),
                 types=('steel','flying'),enemy_speed=100)
        blocked = ineffective_search_moves(s,policy(('sludgebomb','earthpower','powergem'),('roost','bravebird')))
        self.assertIn('sludgebomb',blocked)
        self.assertIn('earthpower',blocked)
        s = duel(moves=('earthpower','powergem'),responses=('roost',),types=('steel','flying'),enemy_speed=300,enemy_hp=300)
        self.assertNotIn('earthpower',ineffective_search_moves(s,policy(('earthpower','powergem'),('roost',))))

    def test_later_log_awake_sleep_talk_ohko_and_flying_immunities(self):
        for moves, types in [(('sleeptalk','darkpulse'),('normal','typeless')),
                             (('sheercold','ancientpower'),('ice','typeless')),
                             (('highhorsepower','icepunch'),('steel','flying')),
                             (('sandtomb','stoneedge'),('ice','flying'))]:
            with self.subTest(moves=moves):
                s = duel(moves=moves,types=types)
                self.assertIn(moves[0],ineffective_search_moves(s,policy(moves)))

    def test_healing_at_full_hp_before_incoming_damage_is_retained(self):
        s = duel(moves=('rest','darkpulse'),responses=('tackle',),enemy_speed=300)
        self.assertNotIn('rest',ineffective_search_moves(s,policy(('rest','darkpulse'),('tackle',))))
        s = duel(moves=('rest','darkpulse'),responses=('swordsdance',))
        self.assertIn('rest',ineffective_search_moves(s,policy(('rest','darkpulse'),('swordsdance',))))

    def test_forced_no_effect_choice_and_state_preservation(self):
        s = duel(moves=('toxic',),types=('steel','typeless'))
        original = s.to_string()
        self.assertEqual(select_search_move(s,policy(('toxic',))),'toxic')
        self.assertEqual(s.to_string(),original)

    def test_preserves_status_bluffs_against_conditional_attacks(self):
        s = duel(moves=('charm','darkpulse'),responses=('thunderclap',))
        self.assertFalse(exclude_reflected_status_moves(s).side_one.pokemon[0].moves[0].disabled)
        self.assertNotIn('charm',ineffective_search_moves(s,policy(('charm','darkpulse'),('thunderclap',))))

    def test_no_effect_preference_respects_a_clearly_better_search_score(self):
        s = duel(moves=('toxic','darkpulse'),types=('steel','typeless'))
        r = policy(('toxic','darkpulse'))
        r.side_one[0].total_score = 99
        r.side_one[1].total_score = 1
        self.assertEqual(select_search_move(s,r),'toxic')

    def test_close_visits_do_not_override_clear_score_preference(self):
        s = duel(moves=('darkpulse','psychic'),types=('normal','typeless'))
        r = policy(('darkpulse','psychic'))
        r.side_one[0].total_score = 90
        with patch('foul_play_player.select_move_from_mcts_results',return_value='darkpulse') as choose:
            self.assertEqual(select_search_move(s,r),'darkpulse')
        self.assertEqual([o.move_choice for o in choose.call_args.args[0][0][0].side_one],['darkpulse'])


class ShowdownParityTests(unittest.TestCase):
    def test_real_custap_rest_and_binding_expiry(self):
        import subprocess
        from pathlib import Path
        script = r'''
const assert = require('assert/strict');
const {Battle} = require('./pokemon-showdown/dist/sim');
function start(one, two, seed=[1,2,3,4]) {
    const battle = new Battle({formatid:'gen9customgame',seed});
    battle.setPlayer('p1',{name:'p1',team:[one]});
    battle.setPlayer('p2',{name:'p2',team:[two]});
    battle.makeChoices();
    return battle;
}
const custap = start(
    {species:'Mismagius',ability:'levitate',moves:['shadowball']},
    {species:'Heatmor',ability:'gluttony',item:'custapberry',moves:['firelash']});
custap.p2.active[0].hp = Math.floor(custap.p2.active[0].maxhp / 2);
custap.makeChoices('move 1','move 1');
const attacks = custap.log.filter(l => l.startsWith('|move|'));
assert.ok(attacks[0].includes('Heatmor|Fire Lash'));
assert.equal(custap.p2.active[0].item,'');
const rest = start(
    {species:'Glastrier',ability:'chillingneigh',item:'chestoberry',moves:['rest']},
    {species:'Sirfetchd',ability:'scrappy',moves:['swordsdance']});
rest.makeChoices('move 1','move 1');
assert.equal(rest.p1.active[0].status,'');
assert.equal(rest.p1.active[0].item,'chestoberry');
assert.ok(rest.log.some(l => l.includes('|-fail|p1a: Glastrier|heal')));
const durations = new Set();
for (let i=1; i<=12; i++) {
    const b = start({species:'Blissey',ability:'naturalcure',moves:['splash']},
        {species:'Dondozo',ability:'oblivious',moves:['whirlpool','splash']},[i,2,3,4]);
    b.p1.active[0].hp = b.p1.active[0].maxhp = b.p1.active[0].baseMaxhp = 1000;
    b.makeChoices('move 1','move 1');
    if (!b.p1.active[0].volatiles.partiallytrapped) continue;
    for (let t=0; t<8 && b.p1.active[0].volatiles.partiallytrapped; t++) {
        b.makeChoices('move 1','move 2');
    }
    assert.ok(!b.p1.active[0].volatiles.partiallytrapped);
    // Battle.log contains both private/public damage lines; count turns.
    const residualTurns = new Set();
    let turn = 0;
    for (const line of b.log) {
        if (line.startsWith('|turn|')) turn = Number(line.split('|')[2]);
        if (line.startsWith('|-damage|p1a: Blissey|') && line.includes('[from] move: Whirlpool')) {
            residualTurns.add(turn);
        }
    }
    const ticks = residualTurns.size;
    assert.ok(ticks===4 || ticks===5,`unexpected binding ticks: ${ticks}`);
    durations.add(ticks);
}
assert.equal(durations.size,2);
'''
        result = subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],
                                text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
