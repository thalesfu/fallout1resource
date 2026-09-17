#!/usr/bin/env python3
"""Scan INT disassembly for has_trait(type, obj, id) calls and list perk/trait checks per script.

has_trait type: 0 = perk, 1 = object flag, 2 = trait (Fallout 1 engine, intextra.cc).
Only calls whose type and id are literal push_int instructions are resolved.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r"^([0-9A-F]{8})\s+[0-9A-F]{4}\s+(\S+)(?:\s+(.*))?$")


def scan(root: Path):
    hits = []
    for path in sorted(root.rglob("*.disasm.txt")):
        ops = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINE.match(raw.strip())
            if not m:
                continue
            ops.append((m.group(2), m.group(3)))
            if m.group(2) != "has_trait" or len(ops) < 4:
                continue
            (t_op, t_arg), _obj, (i_op, i_arg) = ops[-4], ops[-3], ops[-2]
            if t_op == "push_int" and i_op == "push_int":
                obj = _obj[0]
                hits.append((path.relative_to(root).as_posix(), int(t_arg), obj, int(i_arg)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    hits = scan(args.scripts_root)
    agg = defaultdict(set)
    for script, kind, obj, ident in hits:
        agg[(kind, ident)].add((script.split("/")[0], Path(script).name.removesuffix(".disasm.txt"), obj))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "id", "source", "script", "object_expr"])
        for (kind, ident), rows in sorted(agg.items()):
            for source, script, obj in sorted(rows):
                w.writerow([kind, ident, source, script, obj])
    print(f"{len(hits)} has_trait calls, {len(agg)} distinct (type,id)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
