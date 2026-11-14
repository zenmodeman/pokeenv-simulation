"""Run every pair of configured single-Pokémon sets against local Showdown."""
import argparse
import asyncio
import csv
import itertools
import json
from pathlib import Path
import socket
import subprocess
import time
import tomllib

from foul_play_player import FoulPlayPlayer, KnownSetMatch

ROOT = Path(__file__).resolve().parent


def load_config(path):
    path = Path(path)
    contents = path.read_text(encoding="utf-8")
    config = tomllib.loads(contents) if path.suffix.lower() == ".toml" else json.loads(contents)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a mapping")
    if config.get("format", "gen9customgame") != "gen9customgame":
        raise ValueError("This starter supports gen9customgame only (one Pokémon per side).")
    for field, default in [("battles_per_pair", 20), ("timeout_seconds", 300), ("search_time_ms", 100)]:
        value = config.setdefault(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
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


async def simulate(config, output):
    rows = []
    for left, right in itertools.combinations(config["sets"], 2):
        players = []
        match = KnownSetMatch([left["team"], right["team"]], config["search_time_ms"])
        try:
            for index, entry in enumerate((left, right)):
                players.append(FoulPlayPlayer(
                    match=match, side_index=index,
                    battle_format="gen9customgame", team=entry["team"],
                    max_concurrent_battles=1,
                ))
            a, b = players
            # Alternate challenger to avoid consistently assigning one side.
            async def play():
                for index in range(config["battles_per_pair"]):
                    challenger, opponent = (a, b) if index % 2 == 0 else (b, a)
                    await challenger.battle_against(opponent, n_battles=1)
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
            total = a.n_finished_battles
            row = dict(policy="foul-play-mcts", search_time_ms=config["search_time_ms"], set_a=left["name"], set_b=right["name"], battles=total,
                       a_wins=a.n_won_battles, b_wins=b.n_won_battles,
                       ties=total - a.n_won_battles - b.n_won_battles,
                       a_win_rate=a.n_won_battles / total)
            rows.append(row)
            # Save after each completed pairing, preserving results on later failures.
            with Path(output).open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(rows)
            print(f"{left['name']} vs {right['name']}: "
                  f"{row['a_wins']}-{row['b_wins']}-{row['ties']} "
                  f"(A wins {row['a_win_rate']:.1%})", flush=True)
        finally:
            await asyncio.gather(*(p.ps_client.stop_listening() for p in players))
    return rows


def server_available():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sets.toml",
                        help="TOML or JSON configuration (default: sets.toml)")
    parser.add_argument("--output", type=Path, default=ROOT / "results.csv")
    parser.add_argument("--start-server", action="store_true",
                        help="Start the bundled Showdown server if port 8000 is unused")
    args = parser.parse_args()
    server = None
    try:
        config = load_config(args.config)
        if not server_available():
            if not args.start_server:
                parser.error("Start Showdown on localhost:8000 or pass --start-server")
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
        asyncio.run(simulate(config, args.output))
    except (ValueError, OSError, RuntimeError, asyncio.TimeoutError) as error:
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
