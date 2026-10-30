"""Read-only diagnostics for player data and target filtering."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import TextIO

from .memory import DeadlockMemory


def report_players(
    mem: DeadlockMemory, output: TextIO, *, slots: int = 15, show_unreadable: bool = True
) -> None:
    """Inspect bounded target slots without writing memory or sending input."""
    if not 1 <= slots <= 2048:
        raise ValueError("slots must be between 1 and 2048")
    print("Read-only report; matching data does not validate offsets.", file=output)
    try:
        local = mem.read_entity(0)
    except (OSError, OverflowError, ValueError) as exc:
        print(f"Local player unavailable: {exc}", file=output)
        local = None
    else:
        print(
            f"Local: hero={local['hero'].name} team={local['team']} health={local['health']}",
            file=output,
        )

    counts: Counter[str] = Counter()
    for index in range(1, slots + 1):
        try:
            player = mem.read_entity(index)
        except (OSError, OverflowError, ValueError) as exc:
            counts["unreadable"] += 1
            if show_unreadable or counts["unreadable"] <= 3:
                print(f"Slot {index}: unreadable ({exc})", file=output)
            continue
        if local is None:
            status = "local unavailable"
        elif player["team"] == local["team"]:
            status = "same team"
        elif player["health"] <= 0:
            status = "non-positive health"
        elif index > 15:
            status = "candidate outside default scan"
        else:
            status = "candidate"
        counts[status] += 1
        print(
            f"Slot {index}: hero={player['hero'].name} team={player['team']} "
            f"health={player['health']} -> {status}",
            file=output,
        )
    if not show_unreadable and counts["unreadable"] > 3:
        print(f"Additional unreadable slots omitted: {counts['unreadable'] - 3}", file=output)
    print(
        "Summary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
        file=output,
    )
    print(
        "Candidate means only team/health filters passed; it does not verify camera, "
        "bone, or memory-write offsets.",
        file=output,
    )


def main(argv: list[str] | None = None) -> int:
    """Run a one-shot diagnostic using an OS-level read-only process handle."""
    parser = argparse.ArgumentParser(description="Inspect Deadlock player slots without writing")
    parser.add_argument("--pid", type=int, help="game process PID (overrides DEADUNLOCK_PID)")
    parser.add_argument(
        "--slots", type=int, default=15,
        help="number of entity slots to inspect (1–2048; the aimbot uses 15)",
    )
    parser.add_argument(
        "--show-unreadable", action="store_true", help="print every unreadable slot"
    )
    args = parser.parse_args(argv)
    if args.pid is not None and args.pid <= 0:
        parser.error("--pid must be positive")
    if not 1 <= args.slots <= 2048:
        parser.error("--slots must be between 1 and 2048")
    print(
        f"Session: XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', '(unset)')} "
        f"DISPLAY={os.environ.get('DISPLAY', '(unset)')} "
        f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '(unset)')}"
    )
    try:
        mem = DeadlockMemory(read_only=True, pid=args.pid)
        try:
            report_players(
                mem, sys.stdout, slots=args.slots,
                show_unreadable=args.show_unreadable or args.slots <= 15,
            )
        finally:
            mem.pm.close()
    except (RuntimeError, OSError, OverflowError, ValueError) as exc:
        print(f"Diagnostics failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
