"""Battle-boundary checkpoints and nonblocking terminal save controls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile


class Progress:
    def __init__(self, config, accuracy_changes, rows=None):
        self.settings = {key: config[key] for key in
                         ("sets", "battles_per_pair", "search_time_ms")}
        self.settings["accuracy_changes"] = accuracy_changes
        self.rows = rows if rows is not None else []

    def save(self, path):
        path = Path(path)
        payload = dict(version=1, saved_at=datetime.now(timezone.utc).isoformat(),
                       settings=self.settings, rows=self.rows)
        # Replace only after the complete JSON has reached disk.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path, config, accuracy_changes):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        progress = cls(config, accuracy_changes)
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported checkpoint format")
        if payload.get("settings") != progress.settings:
            raise ValueError("Checkpoint sets, battle count, search budget, or mechanics do not match")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Checkpoint rows must be a list")
        from itertools import combinations
        pairs = list(combinations(config["sets"], 2))
        if len(rows) > len(pairs):
            raise ValueError("Checkpoint contains too many pairings")
        for index, row in enumerate(rows):
            left, right = pairs[index]
            if (not isinstance(row, dict) or row.get("set_a") != left["name"]
                    or row.get("set_b") != right["name"]):
                raise ValueError("Checkpoint pairing order does not match configuration")
            counts = [row.get(k) for k in ("battles", "a_wins", "b_wins", "ties")]
            if any(type(n) is not int or n < 0 for n in counts):
                raise ValueError("Checkpoint battle counts must be nonnegative integers")
            total, a, b, ties = counts
            if (not 0 < total <= config["battles_per_pair"] or total != a + b + ties
                    or (index < len(rows) - 1 and total != config["battles_per_pair"])):
                raise ValueError("Checkpoint battle totals are inconsistent")
            expected_mechanics = "accuracy-changes" if accuracy_changes else "standard"
            if (row.get("mechanics") != expected_mechanics
                    or row.get("policy") != "foul-play-mcts"
                    or row.get("search_time_ms") != config["search_time_ms"]
                    or row.get("a_win_rate") != a / total):
                raise ValueError("Checkpoint result metadata is inconsistent")
        progress.rows = rows
        return progress


@contextmanager
def save_controls(loop, progress, path):
    """Read single keys on POSIX terminals without blocking battles or Ctrl-C."""
    if not sys.stdin.isatty():
        yield
        return
    try:
        import termios
        import tty
    except ImportError:
        print("Interactive saving requires a POSIX terminal.", flush=True)
        yield
        return
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    pending = False

    def on_input():
        nonlocal pending
        key = os.read(fd, 1).decode(errors="ignore").lower()
        if pending:
            if key not in {"y", "n", "\r", "\n", "\x1b"}:
                return
            pending = False
            if key == "y":
                try:
                    progress.save(path)
                    print(f"\nSaved progress to {path}. You can stop with Ctrl-C and resume "
                          f"with --resume {path}. An unfinished battle will be replayed.", flush=True)
                except OSError as error:
                    print(f"\nCould not save progress: {error}", flush=True)
            else:
                print("\nSave cancelled.", flush=True)
        elif key == "s":
            pending = True
            count = sum(row["battles"] for row in progress.rows)
            print(f"\nSave progress ({count} recorded battle results) to {path}? [y/N] ",
                  end="", flush=True)

    try:
        tty.setcbreak(fd)
        loop.add_reader(fd, on_input)
        print("Press s to save progress (then y to confirm).", flush=True)
        yield
    finally:
        loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
