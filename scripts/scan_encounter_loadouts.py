#!/usr/bin/env python3
"""Scan INT disassembly for critters spawned by scripts and the items put into their inventory.

Heuristic: walk each script's instruction stream; `create_object_sid` (0x80B7) takes its PID from
the nearest preceding literal `push_int`. Creating an item PID and then calling `add_obj_to_inven`
(0x80D8) or `add_mult_objs_to_inven` (0x8116) within a short window associates that item with the
most recently created critter in the same script. Control flow is ignored, so pairs are candidates,
not proof: verify against the map catalog or in game before treating them as fact.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

INSTRUCTION = re.compile(r"^([0-9A-F]{8})\s+([0-9A-F]{4})\s+(\S+)(?:\s+(-?\d+))?")
CREATE, ADD_INVEN, ADD_MULT = "op_80b7", "op_80d8", "op_8116"
CRITTER, ITEM = 1, 0
LOOKBACK, WINDOW = 12, 14


def ops(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = INSTRUCTION.match(line.strip())
        if m:
            out.append((m.group(3), int(m.group(4)) if m.group(4) is not None else None))
    return out


def literal_pid(stream, index: int) -> int | None:
    """create_object_sid(pid, tile, elevation, sid): the PID is pushed first, so with four literal
    arguments it is the fourth-from-last push_int before the call."""
    literals = [arg for op, arg in stream[max(0, index - LOOKBACK):index]
                if op == "push_int" and arg is not None and arg >= 0]
    if len(literals) >= 4:
        pid = literals[-4]
        if (pid >> 24) in (ITEM, CRITTER) and (pid & 0xFFFFFF) > 0:
            return pid
    return None


def scan(root: Path):
    pairs = []
    for path in sorted(root.rglob("*.disasm.txt")):
        stream = ops(path)
        script = path.name.removesuffix(".disasm.txt")
        source = path.relative_to(root).parts[0]
        last_critter: int | None = None
        pending: list[tuple[int, int]] = []  # (item pid, instruction index)
        for i, (op, _) in enumerate(stream):
            if op == CREATE:
                pid = literal_pid(stream, i)
                if pid is None:
                    continue
                if (pid >> 24) == CRITTER:
                    last_critter, pending = pid, []
                else:
                    pending.append((pid, i))
            elif op in (ADD_INVEN, ADD_MULT) and last_critter is not None:
                for pid, index in list(pending):
                    if i - index <= WINDOW:
                        pairs.append((source, script, last_critter, pid))
                        pending.remove((pid, index))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    pairs = sorted(set(scan(args.scripts_root)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "script", "critter_pid", "critter_prototype_id", "item_pid"])
        for source, script, critter, item in pairs:
            w.writerow([source, script, critter, critter & 0xFFFFFF, item])
    by_critter = defaultdict(set)
    for _, _, critter, item in pairs:
        by_critter[critter].add(item)
    print(f"{len(pairs)} candidate pairs across {len({p[1] for p in pairs})} scripts, "
          f"{len(by_critter)} spawned critter prototypes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
