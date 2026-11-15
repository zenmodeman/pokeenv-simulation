"""Run every pair of configured single-Pokémon sets against local Showdown."""
import argparse
import asyncio
import csv
import itertools
import json
import logging
import math
from pathlib import Path
import socket
import subprocess
import time
import tomllib

from foul_play_player import FoulPlayPlayer, KnownSetMatch
from simulation_progress import Progress, save_controls

ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("simulation")


def standings(rows):
    totals = {}
    for row in rows:
        for side, other in (("a", "b"), ("b", "a")):
            name = row[f"set_{side}"]
            entry = totals.setdefault(name, dict(team=name, battles=0, wins=0, losses=0, ties=0, points=0))
            entry["battles"] += row["battles"]
            entry["wins"] += row[f"{side}_wins"]
            entry["losses"] += row[f"{other}_wins"]
            entry["ties"] += row["ties"]
            entry["points"] += row[f"{side}_wins"] + row["ties"] / 2
    return sorted(totals.values(), key=lambda entry: (-entry["points"], entry["team"]))


def write_standings(rows, output):
    ranked = standings(rows)
    with Path(output).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "team", "battles", "wins", "losses", "ties", "points"])
        writer.writeheader()
        rank = 0
        previous = None
        for index, entry in enumerate(ranked, 1):
            if entry["points"] != previous:
                rank = index
            previous = entry["points"]
            writer.writerow(dict(rank=rank, **entry))
            LOGGER.info("Rank %d: %s — %g points (%d wins, %d losses, %d ties)",
                        rank, entry["team"], entry["points"], entry["wins"], entry["losses"], entry["ties"])


def load_config(path):
    path = Path(path)
    contents = path.read_text(encoding="utf-8")
    config = tomllib.loads(contents) if path.suffix.lower() == ".toml" else json.loads(contents)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a mapping")
    if config.get("format", "gen9customgame") != "gen9customgame":
        raise ValueError("This starter supports gen9customgame only (one Pokémon per side).")
    for field, default in [("battles_per_pair", 20), ("search_time_ms", 100)]:
        value = config.setdefault(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    # Budget both searches per turn, with 3x headroom and one second of
    # protocol/processing overhead per turn. Explicit values remain a floor.
    minimum_timeout = math.ceil(
        config["battles_per_pair"] * 100 * (6 * config["search_time_ms"] / 1000 + 1)
    )
    configured_timeout = config.get("timeout_seconds", minimum_timeout)
    if (isinstance(configured_timeout, bool)
            or not isinstance(configured_timeout, int) or configured_timeout <= 0):
        raise ValueError("timeout_seconds must be a positive integer")
    config["timeout_seconds"] = max(configured_timeout, minimum_timeout)
    sets = config.get("sets", [])
    if not isinstance(sets, list) or len(sets) < 2:
        raise ValueError("Configure at least two sets")
    names = set()
    for entry in sets:
        if not isinstance(entry, dict) or not isinstance(entry.get("team"), str):
            raise ValueError("Each set must be an object with a Showdown team string")
        name = entry.get("name")
        team = entry.get("team", "").strip()
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Each set needs a unique, nonempty name")
        names.add(name)
        # Blank lines separate Pokémon in Showdown's import format.
        if not team or any(not line.strip() for line in team.splitlines()):
            raise ValueError(f"{name}: team must contain exactly one Showdown set")
        moves = [line for line in team.splitlines() if line.startswith("- ")]
        if not 1 <= len(moves) <= 4:
            raise ValueError(f"{name}: provide one to four moves")
        entry["team"] = team
    return config


def install_local_formats():
    source = ROOT / "mechanics" / "custom-formats.ts"
    target = ROOT / "pokemon-showdown" / "config" / "custom-formats.ts"
    contents = source.read_text(encoding="utf-8")
    if target.exists():
        installed = target.read_text(encoding="utf-8")
        if installed == contents:
            return
        if not installed.startswith("// Installed by attempt.py before starting the local Showdown server.\n"):
            raise ValueError(f"{target} already contains custom formats; merge {source} into it manually")
        # Preserve edits to an older generated copy before refreshing it.
        backup = target.with_name(target.name + ".bak")
        index = 1
        while backup.exists():
            backup = target.with_name(f"{target.name}.bak.{index}")
            index += 1
        backup.write_text(installed, encoding="utf-8")
        LOGGER.info("Saved previous local formats to %s", backup)
    target.write_text(contents, encoding="utf-8")


async def simulate(config, output, accuracy_changes=True, progress=None):
    import poke_engine
    configure = getattr(poke_engine, "set_accuracy_changes", None)
    if configure is None and accuracy_changes:
        raise RuntimeError("Rebuild the local poke-engine to use --accuracy-changes (see README.md)")
    if configure is not None:
        configure(accuracy_changes)
    battle_format = "gen9accuracychanges" if accuracy_changes else "gen9localsimulation"
    LOGGER.info("Mechanics: %s; format: %s; knowledge: both complete sets",
                "accuracy-changes" if accuracy_changes else "standard", battle_format)
    progress = progress if progress is not None else Progress(config, accuracy_changes)
    rows = progress.rows
    for pair_index, (left, right) in enumerate(itertools.combinations(config["sets"], 2)):
        previous = rows[pair_index] if pair_index < len(rows) else None
        completed = previous["battles"] if previous else 0
        if completed == config["battles_per_pair"]:
            continue
        prior_a = previous["a_wins"] if previous else 0
        prior_b = previous["b_wins"] if previous else 0
        LOGGER.info("Pairing: %s vs %s", left["name"], right["name"])
        players = []
        match = KnownSetMatch([left["team"], right["team"]], config["search_time_ms"])
        try:
            for index, entry in enumerate((left, right)):
                players.append(FoulPlayPlayer(
                    match=match, side_index=index,
                    battle_format=battle_format, team=entry["team"],
                    max_concurrent_battles=1,
                ))
            a, b = players
            def record_result(total):
                a_wins = prior_a + a.n_won_battles
                b_wins = prior_b + b.n_won_battles
                row = dict(mechanics="accuracy-changes" if accuracy_changes else "standard",
                           policy="foul-play-mcts", search_time_ms=config["search_time_ms"],
                           set_a=left["name"], set_b=right["name"], battles=total,
                           a_wins=a_wins, b_wins=b_wins, ties=total - a_wins - b_wins,
                           a_win_rate=a_wins / total)
                if pair_index < len(rows):
                    rows[pair_index] = row
                else:
                    rows.append(row)

            # Alternate challenger to avoid consistently assigning one side.
            async def play():
                for index in range(completed, config["battles_per_pair"]):
                    LOGGER.info("Battle %d/%d starting: %s vs %s", index + 1,
                                config["battles_per_pair"], left["name"], right["name"])
                    challenger, opponent = (a, b) if index % 2 == 0 else (b, a)
                    await challenger.battle_against(opponent, n_battles=1)
                    record_result(index + 1)
                    LOGGER.info("Battle %d/%d finished; cumulative %s vs %s: %d-%d-%d",
                                index + 1, config["battles_per_pair"], left["name"], right["name"],
                                rows[pair_index]["a_wins"], rows[pair_index]["b_wins"],
                                rows[pair_index]["ties"])
                    if index == 2 and rows[pair_index]["a_wins"] == rows[pair_index]["b_wins"] == 0:
                        LOGGER.info("First three battles were draws; counting all %d battles "
                                    "in this pairing as draws", config["battles_per_pair"])
                        record_result(config["battles_per_pair"])
                        break
            async def watch_errors():
                while True:
                    for player in players:
                        if player.search_error is not None:
                            raise RuntimeError(f"Foul Play decision failed: {player.search_error}") from player.search_error
                    await asyncio.sleep(0.05)

            play_task = asyncio.create_task(play())
            error_task = asyncio.create_task(watch_errors())
            try:
                done, _ = await asyncio.wait(
                    [play_task, error_task], timeout=config["timeout_seconds"],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise TimeoutError("pairing timed out; check sets and showdown.log")
                for task in done:
                    task.result()
                for player in players:
                    if player.search_error is not None:
                        raise RuntimeError(f"Foul Play decision failed: {player.search_error}")
            finally:
                play_task.cancel()
                error_task.cancel()
                await asyncio.gather(play_task, error_task, return_exceptions=True)
            row = rows[pair_index]
            # Save after each completed pairing, preserving results on later failures.
            with Path(output).open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(rows)
            summary = (f"{left['name']} vs {right['name']}: "
                       f"{row['a_wins']}-{row['b_wins']}-{row['ties']} "
                       f"(A wins {row['a_win_rate']:.1%})")
            LOGGER.info(summary)
            print(summary, flush=True)
        finally:
            await asyncio.gather(*(p.stop() for p in players))
    # Also regenerate the CSV when resuming an already complete checkpoint.
    if rows:
        with Path(output).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return rows


async def run_simulation(config, args, progress):
    with save_controls(asyncio.get_running_loop(), progress, args.checkpoint):
        return await simulate(config, args.output, args.accuracy_changes, progress)


def server_available():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return True
    except OSError:
        return False


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sets.toml",
                        help="TOML or JSON configuration (default: sets.toml)")
    parser.add_argument("--output", type=Path, default=ROOT / "results.csv")
    parser.add_argument("--log-file", type=Path, default=ROOT / "simulation.log")
    parser.add_argument("--standings-output", type=Path, default=ROOT / "standings.csv")
    parser.add_argument("--checkpoint", type=Path, default=None,
                        help="Where s saves progress (default: simulation-progress.json, or --resume path)")
    parser.add_argument("--resume", type=Path,
                        help="Resume completed battles from a saved checkpoint")
    parser.add_argument("--start-server", action="store_true",
                        help="Start the bundled Showdown server if port 8000 is unused")
    parser.add_argument("--accuracy-changes", action=argparse.BooleanOptionalAction, default=True,
                        help="Use custom 100%% base accuracy on both sides (default: enabled)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.checkpoint = args.checkpoint or args.resume or ROOT / "simulation-progress.json"
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler = logging.FileHandler(args.log_file, mode="w")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    server = None
    try:
        config = load_config(args.config)
        progress = (Progress.load(args.resume, config, args.accuracy_changes)
                    if args.resume else Progress(config, args.accuracy_changes))
        if args.resume:
            print(f"Resuming {sum(row['battles'] for row in progress.rows)} saved results "
                  f"from {args.resume}", flush=True)
        LOGGER.info("Pairing timeout: %d seconds for %d battles (100-turn limit per battle)",
                    config["timeout_seconds"], config["battles_per_pair"])
        if not server_available():
            if not args.start_server:
                parser.error("Start Showdown on localhost:8000 or pass --start-server")
            install_local_formats()
            with (ROOT / "showdown.log").open("w") as log:
                server = subprocess.Popen(
                    ["node", "pokemon-showdown", "start", "--no-security"],
                    cwd=ROOT / "pokemon-showdown", stdout=log, stderr=log,
                )
            deadline = time.monotonic() + 60
            while not server_available():
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Showdown failed to start; see showdown.log")
                time.sleep(0.2)
        rows = asyncio.run(run_simulation(config, args, progress))
        LOGGER.info("Simulation complete. Final standings (win = 1 point, tie = 0.5):")
        write_standings(rows, args.standings_output)
    except KeyboardInterrupt:
        print("\nSimulation stopped. Resume from your last saved checkpoint with --resume PATH.")
    except (ValueError, OSError, RuntimeError, asyncio.TimeoutError) as error:
        LOGGER.error("Simulation failed: %s", error)
        parser.exit(1, f"Simulation failed: {error or 'pairing timed out; check sets and showdown.log'}\n")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
