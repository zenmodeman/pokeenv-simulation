# 1v1 Pokémon simulations

Configure named Pokémon sets in `sets.toml`, then run every unique pair against
one another using Foul Play search, poke-env, and the bundled Pokémon Showdown server:

```bash
python -m pip install -r requirements.txt
python attempt.py --start-server
```

Python 3.11+ and Rust/Cargo are required to build `poke-engine` from source.
The engine is vendored at v0.0.48 under `vendor/poke-engine/` and built locally
with Gen 9 Terastallization support. A local patch includes Super Luck in
critical-hit stages: 12.5% for ordinary moves and 50% for high-crit moves such
as Sky Attack and Night Slash. Battle Armor and Shell Armor still block crits.
Re-run the install command after changing the vendored engine; an already
installed PyPI wheel does not contain this patch.
If you previously installed the same engine version with other build features,
rebuild it explicitly (pip may otherwise reuse that installation):

```bash
python -m pip install --force-reinstall --no-cache-dir poke-engine==0.0.48 --config-settings="build-args=--features poke-engine/terastallization --no-default-features"
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
  Increase to 500–1000 for more exploration; increase the pairing timeout too.
- `timeout_seconds`: time limit for an entire pairing (default 300).
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

Search can consider consequences such as Close Combat's defensive drops, along
with the opponent's responses and later turns. It remains approximate and limited
by its time budget and poke-engine's mechanics coverage. This adapter supports
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
