# 1v1 Pokémon simulations

Configure named Pokémon sets in `sets.toml`, then run every unique pair against
one another using Foul Play search, poke-env, and the bundled Pokémon Showdown server:

```bash
python -m pip install -r requirements.txt
python attempt.py --start-server
```

Python 3.11+ and Rust/Cargo are required to build `poke-engine` from source.
The engine is vendored at v0.0.48 under `vendor/poke-engine/` and built locally
with Gen 9 mechanics support. Terastallization is disabled in simulations,
both in Showdown and throughout engine searches. A local patch includes Super Luck in
critical-hit stages: 12.5% for ordinary moves and 50% for high-crit moves such
as Sky Attack and Night Slash. Leek adds two stages for Sirfetch’d and Farfetch’d,
giving high-crit moves a 100% critical-hit chance. Battle Armor and Shell Armor still block crits.
Local engine patches also model Gluttony/Custap turn order, finite Whirlpool/Sand
Tomb durations, and Rest failing at full HP. The accuracy profile includes Meteor
Beam at 100% in both Showdown and search. Attack-stage evaluation uses the known
moves' stat dependencies. The adapter excludes irrelevant pure Attack drops and
prefers useful root choices among similarly scored moves when an alternative has
no modeled effect against every legal response, retaining forced choices and contextual healing/type changes. Per-move visits and scores
are logged for both sides; flagged choices and near-certain losses include
replayable engine states (all states are available at DEBUG logging level).
Re-run the install command after changing the vendored engine; an already
installed PyPI wheel does not contain this patch.
If you previously installed the same engine version with other build features,
rebuild it explicitly (pip may otherwise reuse that installation). Restart both
the simulation and Showdown server after engine or format changes; an existing
server keeps its previously loaded format:

```bash
python -m pip install --force-reinstall --no-cache-dir ./vendor/poke-engine/poke-engine-py --config-settings="build-args=--features poke-engine/terastallization --no-default-features"
```

On a fresh checkout, first initialize and install Showdown (Node.js 22.18+):

```bash
git submodule update --init --recursive
cd pokemon-showdown
npm ci
cd ..
```

`--start-server` starts Showdown locally on port 8000 if needed and stops that
server when finished. An existing server is reused and left running. Server
output goes to `showdown.log`. Without the flag, start Showdown yourself first.
Use only a trusted local server: `--no-security` allows rapid automated challenges.

## Save and resume a simulation

While running in an interactive terminal on Linux or macOS, press **s**, then
**y** to confirm saving progress. No Enter is needed. Press **n** or Enter to
cancel. Saving leaves the simulation running; after the saved-file message,
you can stop with **Ctrl-C** and resume later:

```bash
python attempt.py --start-server --resume simulation-progress.json
```

The checkpoint contains all battle results completed at the moment of saving,
including progress within the current pairing. A battle still in progress is
replayed on resume. Results completed after the last save are not in that
checkpoint; press **s**, then **y** again to refresh it before stopping.
Completed pairings are skipped, and challenger alternation, totals, and the
three-initial-draws shortcut continue from the saved counts. CSV results and final
standings include both saved and newly completed results.

Use `--checkpoint PATH` to choose where saves go (default:
`simulation-progress.json`). When using `--resume PATH`, saves update that file
unless `--checkpoint` specifies another path. Resume requires the same configured
sets, their order, battle count, search budget, and accuracy mode; pass the same
`--config` and `--no-accuracy-changes` options if you used them originally.
Checkpoints are written atomically and remain available after a run completes.
Keyboard saving is disabled when stdin is redirected or no terminal is attached.

## Configure sets

Edit `sets.toml`. Each entry has a unique `name` and a `team` string containing
exactly one Pokémon in Showdown's import/export format. Paste the export directly
between the triple single quotes; line breaks need no escaping. Copy a `[[sets]]`
block to add another species or another build of the same species. Specify level,
item, ability, nature, EVs, IVs, and moves there.
Showdown supplies its usual defaults for omitted fields.

```toml
[[sets]]
name = "Garchomp - Scarf"
team = '''
Garchomp @ Choice Scarf
Ability: Rough Skin
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Earthquake
- Outrage
- Stone Edge
- Iron Head
'''
```

The default configuration is `sets.toml`. Existing JSON configurations remain
supported with `--config sets.json` (JSON strings still require `\n`).

- `battles_per_pair`: number of battles for **each** pair (default 20).
- `search_time_ms`: search budget per side per decision (default 100 ms).
  Increase to 500–1000 for more exploration; the pairing timeout scales automatically.
  Among similarly supported moves with comparable average search scores, the
  adapter prefers Protect when every modeled opponent response yields net
  Leftovers recovery without giving the opponent healing, boosts, or new volatile
  effects. Consecutive-Protect failure risk and residual damage are included in
  this check; it does not force Protect over a stronger search choice.
- Battles still undecided after turn 100 (including residual effects) end in a draw.
- If the first three battles of a pairing are draws, the remaining battles are skipped
  and all configured battles for that pairing count as draws in results and standings.
  A win on turn 100 still counts as a win. Draws receive 0.5 standings points.
- `timeout_seconds`: optional minimum time limit for an entire pairing.
  The effective limit is at least `battles_per_pair × 100 × (1 + 6 × search_time_ms / 1000)`
  seconds, allowing both searches per turn, 3× search headroom, and one second
  per turn for processing. With 20 battles and 100 ms searches this is 3200 seconds
  (53 minutes 20 seconds). Larger explicit values are preserved.
- `format`: `gen9customgame`; each side receives exactly one configured Pokémon.
  Custom Game allows experimental sets; it does not enforce ranked 1v1 legality.

For N sets there are N × (N − 1) / 2 pairings. Each pairing alternates which
player sends the challenge. All battles are sequential.

```bash
python attempt.py --config sets.toml --output results.csv --start-server
```

The console and CSV report each pairing's wins and ties. `a_win_rate` is A's
wins divided by all completed battles, with ties counting as non-wins. Results
are overwritten for each run and saved after every completed pairing, so a later
timeout preserves earlier pairings. Invalid sets may cause Showdown to reject a
challenge; check console errors and the server log if a pairing times out.

Live progress is written to `simulation.log`, including battle starts, turns,
moves, damage, healing, critical hits (`|-crit|` followed by the target), Mega
Evolution (`|-mega|` and `|detailschange|` for the resulting form), status,
and results. The console prints only the result
summary for each completed matchup. Follow detailed progress during a run:

```bash
tail -f simulation.log
```

After the full simulation, `standings.csv` lists every set ordered by total
points across all opponents: one point per win and half a point per tie. Equal
scores share a rank (displayed alphabetically). The log also shows these final
standings. Use `--log-file PATH` and `--standings-output PATH` to
change their locations. The log is overwritten at the start of each run; standings
are replaced only after a successful full run, so an interrupted run can leave
standings from an earlier run. `showdown.log` remains the server diagnostic log.

## Custom mechanics

Custom accuracy rules are enabled by default for every Pokémon on both sides:

```bash
python attempt.py --start-server
```

Sky Attack, High Horsepower, Sand Tomb, Play Rough, Ruination, Drill Run,
Whirlpool, and Screech have **100% base accuracy** in both
Showdown battles and engine searches. Accuracy/evasion stages and other accuracy
modifiers still apply. Sky Attack retains its charge turn, Power Herb interaction,
critical-hit rate, and other effects. Use `--no-accuracy-changes` for standard mechanics;
`--accuracy-changes` remains available to enable the custom profile explicitly.
The CSV `mechanics` column records `standard` or `accuracy-changes`.

Rebuild the local engine after pulling this change:

```bash
python -m pip install --force-reinstall --no-deps ./vendor/poke-engine/poke-engine-py --config-settings="build-args=--features poke-engine/terastallization --no-default-features"
```

Before launching a new server, the runner installs `mechanics/custom-formats.ts`
into Showdown's `config/custom-formats.ts`. Older copies bearing this project's
installation comment are refreshed automatically, with the previous contents
saved to `custom-formats.ts.bak` (or a numbered backup if one already exists).
It refuses to overwrite unrelated custom formats files; merge the formats and
start Showdown manually if you already have one.
For an existing server, install that file and restart the server first (the normal
server startup builds it). Simulations use `gen9accuracychanges` by default or `gen9localsimulation` with
`--no-accuracy-changes`. The log records the selected profile and format.
Both formats disable Tera, so an unprepared server cannot silently run with
different rules.
The search engine's rules toggle is process-wide; configure it before searches,
and do not mix profiles in concurrent searches within the same Python process.

### Add another 100% accuracy move

Update both implementations so Showdown executes the same mechanics that the
search engine predicts. Use the normalized move ID (lowercase, without spaces
or punctuation) in TypeScript and its uppercase `Choices` variant in Rust.
For example, to add Screech:

1. In `mechanics/custom-formats.ts`, include `move.id === 'screech'` in the
   `onModifyMove` condition that sets `move.accuracy = 100`. Screech is already
   present in this file; the remaining steps are still needed for engine parity.
2. In `vendor/poke-engine/src/genx/choice_effects.rs`, add `| Choices::SCREECH`
   to the `matches!` list inside `modify_choice`, under the
   `accuracy_changes_enabled()` guard:

   ```rust
                | Choices::WHIRLPOOL
                | Choices::SCREECH
   ```

   Keep `attacker_choice.accuracy = 100.0` inside that guard so standard rules
   remain available. Do not change the move's base data or use an always-hit
   setting: accuracy/evasion modifiers should still apply.
3. Extend `tests/test_accuracy_changes.py`. For a damaging move, add its ID and
   original accuracy to `ACCURACY_CHANGES`, and add the ID to the JavaScript
   move list in the Showdown test. For a status move such as Screech (85% base
   accuracy), add a separate engine test that detects its effect instead of HP
   damage: Screech hits when the resulting `side_two.defense_boost` drops.
   Check the original hit chance with the profile disabled, 100% with it enabled,
   and 75% with it enabled at −1 accuracy; also check that disabling the profile
   restores the original chance. Add the move to the Showdown test's JavaScript
   list and expected results (`"screech": [100, 85]` for this example).
4. Update the affected-moves list above and the `--accuracy-changes` help text
   in `attempt.py` to describe the expanded profile.
5. Rebuild the engine, copy the updated format, and run the accuracy checks from
   the repository root:

   ```bash
   python -m pip install --force-reinstall --no-deps ./vendor/poke-engine/poke-engine-py --config-settings="build-args=--features poke-engine/terastallization --no-default-features"
   cp mechanics/custom-formats.ts pokemon-showdown/config/custom-formats.ts
   python -m unittest discover -s tests -p 'test_accuracy_changes.py' -v
   ```

   Restart any running Showdown server so it builds and loads the new format,
   then run simulations with `--accuracy-changes`. Changes to the Rust source
   require reinstalling the engine; restarting Python alone is insufficient.

## Battle decisions

Both sides now use [Foul Play](https://github.com/pmariglia/foul-play)'s
Monte Carlo Tree Search engine (`poke-engine`) and its upstream policy-selection
function. Foul Play's Python source is vendored at a pinned revision under
`vendor/foul-play/`; its GPL-3.0 license and source attribution are included there.
The adapter lives in `foul_play_player.py`.

Before either player chooses, the adapter synchronizes both private Showdown
requests. Each search receives both Pokémon's exact current HP, stats (including
EV/IV effects), items, abilities, full moves, PP, and disabled moves. Foul Play's
protocol handlers track boosts, status, weather, terrain, and other battle effects.
Each player searches from its own perspective without seeing the other's chosen
move. Showdown executes the resulting choices and determines the winner.

This is **known-set analysis**, rather than hidden-information ladder play. The
full Foul Play ladder client and its opponent-set prediction are not used. With
one known state per decision, we call the same engine search and upstream policy
selection directly, avoiding Foul Play's multiprocessing sampler.

Mega Evolution is an explicit search option: configure the base species with its
Mega Stone (for example, `Charizard @ Charizardite X`). The engine considers
Mega and ordinary moves for both sides, and Showdown executes the selected Mega
Evolution. Updated forms, abilities, types, and exact stats persist on later turns.
For Clefable with Clefablite, this lets the AI delay evolution to retain Unaware
or avoid new Electric, Ice, and Rock weaknesses, and evolve when the stat gains,
Ground immunity, or Magic Bounce are useful. Toxic and Screech are reflected
on the evolution turn. These tradeoffs are evaluated by search rather than a
mandatory first-turn evolution rule.
The engine currently assumes 31 IVs when calculating stats during a predicted
Mega Evolution; Showdown uses the configured IVs and subsequent searches receive
its exact stats. Tera is disabled even if a set includes a Tera Type.

Search can consider consequences such as Close Combat's defensive drops and
Mirror Armor reflecting Noble Roar (including both stat drops) or damaging
moves' secondary stat drops, along with the opponent's responses and later turns.
After updating the vendored engine, rebuild it with the local pip command above.
Ability activations (`-ability`) and stat drops (`-unboost`) are recorded in
`simulation.log`, including Mirror Armor and each reflected drop.

Mind Reader (and Lock-On) now grants guaranteed accuracy through the next turn,
so search can evaluate Articuno's Mind Reader + Sheer Cold combination alongside
its other options. Sheer Cold deals OHKO damage on a hit, ignores accuracy/evasion
stages, and fails against Ice types, higher-level targets, and Sturdy. Protect,
Substitute, Focus Sash, and the risk of fainting before the follow-up remain part
of the search. Rebuild the local engine after pulling these changes.

Search remains approximate and limited by its time budget and poke-engine's mechanics coverage. This adapter supports
Gen 9 singles with one Pokémon per side; it does not support team switching,
Dynamax, or Z-Moves. Unsupported engine choices or adapter failures stop the run
with an error; there is no heuristic or random fallback.

The CSV includes `policy` and `search_time_ms` so results identify their search
settings. Search and battle randomness remain active; runs are not seeded.

## Checks

```bash
python -m unittest discover -s tests -v
```

Tests cover exact known-set state, independent player perspectives, PP/disabled
moves, persisted defense drops, engine-generated Close Combat consequences, and
a legal MCTS decision. To check real battles quickly, use a copy of `sets.toml`
with `battles_per_pair` set to 1 and run it with `--config` and `--output`.

Both players know the opponent’s complete set before turn one, including ability,
item, moves, EVs, nature, and exact stats. Pure stat-lowering moves such as Screech
and Noble Roar are excluded against known Mirror Armor when another move is
available, unless the user can bypass it or benefit from reflected drops.
