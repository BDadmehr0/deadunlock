"""Read-only probe of experimental named skeleton offsets and animated poses."""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from .memory import DeadlockMemory
from .skeleton import (
    MAX_BONES, MODEL_COUNT, MODEL_HANDLE, MODEL_NAMES, MODEL_STATE, POSE_ARRAY,
    SkeletonReader, SkeletonUnavailable,
)


def report_skeleton(
    mem: DeadlockMemory, slot: int, output: TextIO, *, dump_names: bool = False
) -> bool:
    """Print candidate model/bones without changing memory or sending input."""
    player = mem.read_entity(slot)
    centre = player["position"]
    origin = (centre[0], centre[1], centre[2] - 70)
    print(f"Slot {slot}: hero={player['hero'].name} scene={player['node']:#x} "
          f"origin={origin}", file=output)
    print("Read-only candidate layout; plausible positions do NOT verify offsets or hitboxes.",
          file=output)
    reader = SkeletonReader(mem)
    try:
        state = player["node"] + MODEL_STATE
        pose = reader._pointer(mem.read_longlong(state + POSE_ARRAY), "pose")
        handle = reader._pointer(mem.read_longlong(state + MODEL_HANDLE), "model handle")
        model = reader._pointer(mem.read_longlong(handle), "model")
        names = reader._pointer(mem.read_longlong(model + MODEL_NAMES), "name array")
        count = mem.read_uint(model + MODEL_COUNT)
        print(f"Candidates: pose={pose:#x} handle={handle:#x} model={model:#x} "
              f"names={names:#x} count={count}", file=output)
        if dump_names:
            if not 1 <= count <= MAX_BONES:
                raise SkeletonUnavailable("invalid bone count")
            shown = min(count, 128)
            for index in range(shown):
                try:
                    pointer = mem.read_longlong(names + index * 8)
                    name = reader._name(pointer)
                    print(f"  [{index}] {name}", file=output)
                except (OSError, OverflowError, SkeletonUnavailable) as exc:
                    print(f"  [{index}] unreadable ({exc})", file=output)
            if shown < count:
                print(f"  ... {count - shown} more names omitted", file=output)
    except (OSError, OverflowError, SkeletonUnavailable) as exc:
        print(f"Candidate pointer chain unavailable ({exc})", file=output)
    success = False
    for zone in ("head", "body", "legs"):
        try:
            result = reader.read(player, zone)
        except SkeletonUnavailable as exc:
            print(f"{zone}: unavailable ({exc})", file=output)
            continue
        success = True
        name = result.selected_name
        print(f"{zone}: model={result.model:#x} bones={result.count} "
              f"{name}[{result.indices[name]}]={result.positions['selected']} "
              f"pelvis={result.positions['pelvis']} head={result.positions['head']}", file=output)
    return success


def main(argv: list[str] | None = None) -> int:
    """Run a bounded one-player probe with an OS-level read-only handle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="game PID (overrides DEADUNLOCK_PID)")
    parser.add_argument("--slot", type=int, default=0, help="player slot 0–2048 (0 is local)")
    parser.add_argument("--dump-names", action="store_true",
                        help="also print up to 128 candidate bone names")
    args = parser.parse_args(argv)
    if args.pid is not None and args.pid <= 0:
        parser.error("--pid must be positive")
    if not 0 <= args.slot <= 2048:
        parser.error("--slot must be between 0 and 2048")
    try:
        mem = DeadlockMemory(read_only=True, pid=args.pid)
        try:
            return 0 if report_skeleton(mem, args.slot, sys.stdout,
                                        dump_names=args.dump_names) else 1
        finally:
            mem.pm.close()
    except (RuntimeError, OSError, OverflowError, ValueError) as exc:
        print(f"Skeleton diagnostics failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
