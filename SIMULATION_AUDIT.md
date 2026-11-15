# Simulation log audit

Audited a stable snapshot of `simulation.log`: 15,747 lines, battles 4419–4916,
497 completed battles and one battle in progress. The log was growing during
the audit. Line references below refer to this prefix of the original log.
The original findings are retained below. The corrections are now implemented;
see the implementation update at the end.

## Confirmed mechanics mismatches

### 1. Meteor Beam accuracy differs between search and Showdown — high priority

- Evidence: 15 Meteor Beam misses in the snapshot, including line 13847.
- `mechanics/custom-formats.ts:36` compares `move.id` with `Meteor Beam`;
  Showdown's ID is `meteorbeam`, so the override never applies.
- `vendor/poke-engine/src/genx/choice_effects.rs:42` includes METEORBEAM
  in the 100% accuracy profile.
- Verified with the shipped Showdown format and installed Python engine:
  Showdown reports 90%; engine branches give approximately 100% hit probability.
- Fix: use the lowercase ID and include Meteor Beam in both the engine and
  Showdown accuracy-profile regression tests. The current tests omit it.
  Re-run affected results after aligning the two implementations.

### 2. Gluttony/Custap turn order is wrong in search — high priority

- Evidence: Heatmor consumes Custap at 139/374 HP (lines 12449, 12459–12460),
  and at 109/374 HP (lines 12400, 12409–12410). Both exceed 25%.
- Showdown's `data/items.ts:1247` supports Gluttony's 50% threshold.
- Engine `genx/generate_instructions.rs:2711` only checks HP below 25%,
  and handles item consumption only when the two moves have equal priority.
  Its strict `<` comparison also misses the exact quarter-HP boundary.
- Reproduced with a faster Mismagius and a slower Gluttony Heatmor at
  150/374 HP: the engine lets Mismagius KO Heatmor before Fire Lash and leaves
  Custap unconsumed. Showdown's Custap should let Heatmor act first within
  their shared priority bracket.
- Fix: model thresholds, consumption, and fractional priority consistently,
  including both sides having Custap and differing move priorities.
  Custap must not promote a normal-priority attack above Sucker Punch.

### 3. Binding damage has no expiry in engine lookahead — high priority

- Evidence: Whirlpool expires repeatedly in the real log, e.g. lines 5245,
  5450, and 5658.
- Engine `genx/generate_instructions.rs:3600` applies PARTIALLYTRAPPED damage
  every turn. There is no binding duration counter or natural expiry branch.
- Reproduced: six consecutive Splash turns leave PARTIALLYTRAPPED present
  and reduce 1000 HP to 250, with no expiry branch.
- The protocol adapter removes the volatile when Showdown announces expiry;
  the error affects future search predictions before that announcement.
- Fix: track elapsed binding turns and model the remaining duration. This
  affects Whirlpool and Sand Tomb, and can overvalue trapping and distort
  healing/Protect decisions. Check source-faint cleanup as part of that fix.

## Confirmed questionable choices and policy gaps

### 4. The earlier Charm filter misses special sets with status moves

- Evidence: 34 Charms against Dondozo, 13 against Articuno, and one against
  Clefable. These configured sets have no moves using their own Attack.
- `irrelevant_attack_drops` currently requires every opposing move to have
  category `special`. Rest, Sleep Talk, Roost, and Mind Reader prevent it
  from identifying these cases. Verified that Charm remains enabled against
  the configured Articuno and Dondozo sets.
- Charm also appears three times against Umbreon and once against Wo-Chien.
  Their Foul Play uses Mismagius's Attack, so lowering their own Attack does
  not reduce that damage.
- Engine `genx/evaluate.rs:191` and `:237` assign Attack stages value without
  checking which moves use that stat; the previous adapter filter only
  partially compensates for this.
- Fix: evaluate actual stat dependencies, including Sleep Talk's callable
  attacks, Foul Play, Body Press, variable-category attacks, confusion, and
  move-copying effects. Avoid treating all physical-category moves as users
  of their owner's Attack.

### 5. Toxic is selected into known Poison immunity

- Evidence: seven Toxic immunity events against Glimmora, e.g. lines
  15113–15114 and 15182–15183. Another attempt misses, so it is not counted
  among those seven immunity messages.
- Umbreon has Inner Focus. Glimmora having Corrosion does not let Umbreon
  poison it; Corrosion belongs to the move user.
- This proves a wasted choice, not that the engine misimplements immunity.
  A search that regards every available action as losing can tie them.
- Fix: prefer useful legal alternatives over guaranteed no-effect status
  moves when the complete sets establish immunity. Preserve forced choices
  and genuine secondary effects.

### 6. Stat drops are selected at the stage floor

- Evidence: Mismagius uses Fake Tears at turn 28 of battle 4622, and the log
  reports `spd|0` (lines 5844–5845). It then dies to Whirlpool that turn.
- Noble Roar also produces zero drops twice, but both occurrences were
  randomly called by Sleep Talk (lines 5754 and 6435). Those are not direct
  Noble Roar selection errors.
- Fix: avoid pure debuffs that cannot change any relevant stat, while
  preserving forced moves and the original Sleep Talk action.

## Search behavior and diagnostic limitations

The upstream selector (`vendor/foul-play/fp/search/main.py:37`) randomly samples
all moves with at least 75% of the best visit count. It does not require
comparable average scores. The adapter has a score check for its Protect
preference, but the general selector still uses visits alone. This can retain
unhelpful moves, especially in positions where all choices have losing values.
The log does not record per-move visits, scores, or converted engine states,
so it cannot establish the cause of each individual choice.

Recommended diagnostic change: log the selected move, visits and average score
for every available action, search iterations, and a reproducible state snapshot
for flagged decisions. Then compare selected positions at 100 ms and a longer
budget before introducing broad tactical preferences.

Examples requiring that distinction:

- Garchomp uses Earthquake into Levitate at line 4123. It has only 38 HP and
  is slower than Mismagius, so this may be a tied losing position rather than
  an immunity-model bug. Rock Slide flinch possibilities merit replay.
- Manaphy abandons Rest under rain for Ice Beam, then dies to Shadow Ball
  (lines 8934–8944). This merits a longer-search replay; damage rolls,
  critical hits, PP, and remaining rain prevent proving the best action from
  that sequence alone.
- Nine failed Sucker Punches are not automatically errors: Mismagius can
  choose Charm or Fake Tears, and Sucker Punch creates a simultaneous-choice
  prediction problem.
- Roost/Moonlight failures after Meteor Beam misses do not prove bad healing
  logic: healing was selected before the faster opponent unexpectedly missed.
- Sleep Talk calling Rest and failing is a valid random outcome.

Recommended order: align Meteor Beam accuracy, repair Custap and binding
mechanics, improve diagnostics, then address stat relevance and guaranteed
no-effect choices. Re-run affected pairings after mechanics corrections.


## Implementation and expanded-log update

Reviewed a second stable snapshot of 28,567 lines and 1,047 completed battles.
The new section adds five Sludge Bomb immunity events and six Earth Power
immunity events against Corviknight/Skarmory. The current-decision no-effect
tie preference now covers these attacks, Toxic immunity, capped debuffs, and other
moves whose complete outcome distributions equal taking no action against
all legal modeled responses. It preserves faster Roost changing Ground
immunity, healing after incoming damage, meaningful ability interactions,
and forced choices. It also retains status bluffs against conditional attacks and
no-effect choices with clearly better search scores (such as residual or PP wins).
These contextual restrictions do not persist into later
search nodes.

The new log also exposed a confirmed Rest mechanics bug. Glastrier uses Rest
at full HP after Sirfetch'd selects Swords Dance (lines 21482–21483). The engine
previously modeled a successful Rest and sleep even at full HP. It now fails
without sleep or Chesto consumption, matching Showdown. The Rest correction
also respects groundedness for Electric Terrain and sleep-blocking abilities.

Implemented the three original mechanics corrections: matching Meteor Beam
accuracy, Custap thresholds/consumption/priority on both sides, and finite
binding duration with chance branches, observed elapsed ticks, and source-faint
cleanup. Binding counters round-trip through Python and serialized engine states.

Attack-stage evaluation now distinguishes the attacker's own stat from Foul
Play, Body Press, and fixed damage. The Charm filter recognizes status-bearing
special sets and retains unknown move-copying, variable-category, confusion,
and forced Struggle cases. Random selection among similarly visited moves
now also requires average scores within 0.01. Search logs record visits/scores
for both sides, total iterations, selected actions, and replay states for flagged
choices and near-certain losses; DEBUG includes all search inputs.

Regression coverage is in `tests/test_audit_regressions.py`,
`tests/test_charm.py`, the accuracy-profile tests, and Rust evaluator tests.
The README rebuild command now uses the vendored source instead of replacing
local patches with a PyPI release. Already-running processes continue to use
their previously loaded engine; start a new run to use the corrections.

A final snapshot reviewed during implementation reached 79,994 lines and 2,019
completed battles. The section after line 28,567 adds 103 Sleep Talk failures,
12 High Horsepower immunity events, five Sheer Cold immunity events, and two
Sand Tomb immunity events. The first Sleep Talk example (line 37,668) is an awake
Dondozo after two failed full-HP Rests, not a Sleep Talk wake-up gamble. Sheer
Cold targets Ice-type Glastrier (line 47,811); High Horsepower targets Corviknight
(line 58,565). New regression cases verify the contextual preference recognizes
these useless actions. Repeated Rest failures further support the corrected
full-HP mechanics. Leech Seed bouncing off Mega Clefable and into Grass-type
Wo-Chien appears too; that is a known no-effect outcome, not a failure of
Showdown's Magic Bounce mechanics. Repeated Protect failures and Sleep Talk
randomly calling Rest remain valid probabilistic outcomes.
