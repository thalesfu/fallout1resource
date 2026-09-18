#!/usr/bin/env python3
"""Read the global variables out of a Fallout 1 SAVE.DAT (read-only).

Layout (fallout1-ce loadsave.cc master_save_list): 0x7563-byte header, 4-byte dude CID,
then `scr_game_save`: every game global variable as a big-endian int32, in VAULT13.GAM order.
Names come from DATA/VAULT13.GAM so the output can be diffed between saves.
"""

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

HEADER_SIZE = 0x7563
SIGNATURE = b"FALLOUT SAVE FILE"


def gvar_names(gam: Path) -> list[tuple[str, str]]:
    """Index by the explicit `(N)` in each line's comment; line order has gaps and extras."""
    named: dict[int, tuple[str, str]] = {}
    for line in gam.read_text(encoding="latin-1").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:=\s*(-?\d+)\s*;\s*//\s*\((\d+)\)(.*)$", line)
        if m:
            named[int(m.group(3))] = (m.group(1), m.group(4).strip().lstrip("/").strip())
    size = max(named) + 1
    return [named.get(i, (f"UNNAMED_{i}", "")) for i in range(size)]


def read(save: Path, gam: Path) -> tuple[str, list[tuple[int, str, int, str]]]:
    data = save.read_bytes()
    if not data.startswith(SIGNATURE):
        raise SystemExit(f"{save}: not a Fallout save")
    save_name = data[0x3D:0x3D + 30].split(b"\0")[0].decode("latin-1")
    names = gvar_names(gam)
    offset = HEADER_SIZE + 4
    values = struct.unpack_from(f">{len(names)}i", data, offset)
    return save_name, [(i, n, v, c) for i, ((n, c), v) in enumerate(zip(names, values))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("save", type=Path, help="…/DATA/SAVEGAME/SLOTnn/SAVE.DAT")
    ap.add_argument("--gam", type=Path, required=True, help="workspace/raw/master/DATA/VAULT13.GAM")
    ap.add_argument("--vars", default="", help="comma-separated indexes or names to show (default: all non-zero)")
    args = ap.parse_args()
    name, rows = read(args.save, args.gam)
    wanted = {w.strip().upper() for w in args.vars.split(",") if w.strip()}
    print(f"# {args.save} ({name})")
    for i, n, v, c in rows:
        if wanted and str(i) not in wanted and n.upper() not in wanted:
            continue
        if not wanted and v == 0:
            continue
        print(f"{i:4d} {n:28s} {v:8d}  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
