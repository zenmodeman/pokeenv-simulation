Vendored from https://github.com/pmariglia/poke-engine, tag v0.0.48.
See LICENSE for its GPL-3.0 license.

Local change: src/genx/generate_instructions.rs combines Super Luck and
high-critical-hit moves as critical-hit stages in both damage branching paths.
Gen 6+ stage 2 has a 50% chance; Gen 4/5 stage 2 has a 25% chance.
Other critical-hit stage sources retain upstream behavior.
The Python bindings are built locally through requirements.txt with Gen 9
Terastallization enabled.
