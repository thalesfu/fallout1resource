#!/usr/bin/env python3
"""Dump a readable dialogue/logic outline of one INT script from its disassembly.

For every procedure it prints, in bytecode order: conditions (the expression ops feeding each
`if`, compacted), NPC replies/messages, player options with their target procedure, procedure
calls, and global/map variable writes. Message text is taken from the inline MSG annotations the
disassembler already produced. This is an outline for reading quest logic, not a decompiler:
jump targets are not resolved into structured blocks.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

INS = re.compile(r"^([0-9A-F]{8})\s+[0-9A-F]{4}\s+(\S+)(?:\s+(-?\d+))?")
MSG = re.compile(r";\s*(?:message_lookup|intelligence_option|option|reply|message):\s*list=(\d+),\s*message=(\d+)\s*\|\s*(.*?),\s*status=")
PROC = re.compile(r"^\.procedure\s+(\d+)\s+(\S+)")
NOISE = {"push_base", "pop_base", "pop_to_base", "pop_return", "d_to_a", "a_to_d", "swapa", "pop", "jump"}


def parse(path: Path):
    procs: list[tuple[int, str, list]] = []
    current = None
    last = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        pm = PROC.match(line.strip())
        if pm:
            current = (int(pm.group(1)), pm.group(2), [])
            procs.append(current)
            continue
        if current is None:
            continue
        mm = MSG.search(line)
        if mm and last is not None:
            last["text"] = mm.group(3)
            continue
        im = INS.match(line.strip())
        if im:
            last = {"op": im.group(2), "arg": int(im.group(3)) if im.group(3) is not None else None}
            current[2].append(last)
    return procs


def outline(procs, names: dict[int, str], show_all: bool) -> list[str]:
    out = []
    for index, name, ops in procs:
        lines = []
        for i, op in enumerate(ops):
            o = op["op"]
            lits = [x["arg"] for x in ops[max(0, i - 6):i] if x["op"] == "push_int"]
            if o == "if":
                cond = []
                for x in reversed(ops[max(0, i - 14):i]):
                    if x["op"] in ("if", "set_global_var", "gsay_reply", "gsay_option", "giq_option", "call") or x["op"] in NOISE and x["op"] != "jump":
                        break
                    cond.append(x)
                cond.reverse()
                cond = [c for c in cond if not (c["op"] == "push_int" and c is cond[0])]  # drop jump target
                expr = " ".join(f"{c['op']}({c['arg']})" if c["arg"] is not None else c["op"] for c in cond)
                expr = re.sub(r"push_int\((-?\d+)\) global_var", r"G[\1]", expr)
                expr = re.sub(r"push_int\((-?\d+)\) local_var", r"L[\1]", expr)
                expr = re.sub(r"push_int\((-?\d+)\) op_80c3", r"M[\1]", expr)
                expr = re.sub(r"push_int\((-?\d+)\)", r"\1", expr)
                lines.append(f"  如果 {expr}")
            elif o in ("gsay_reply", "gsay_message", "display_msg", "float_msg") and op is not None:
                text = next((x.get("text") for x in reversed(ops[max(0, i - 4):i + 1]) if x.get("text")), None)
                if text:
                    lines.append(f"  NPC：{text}")
            elif o in ("giq_option", "gsay_option"):
                text = next((x.get("text") for x in reversed(ops[max(0, i - 6):i + 1]) if x.get("text")), "?")
                target = lits[-2] if len(lits) >= 2 else None
                iq = lits[-5] if o == "giq_option" and len(lits) >= 5 else None
                tag = f"（智力≥{iq}）" if iq not in (None, 4, -3) and iq and iq > 0 else ("（低智力）" if iq and iq < 0 else "")
                lines.append(f"  选项{tag}：{text} → {names.get(target, target)}")
            elif o == "call" and len(lits) >= 1:
                lines.append(f"  调用 {names.get(lits[-1], lits[-1])}")
            elif o in ("set_global_var", "op_80c4", "set_local_var") and len(lits) >= 2:
                kind = {"set_global_var": "G", "op_80c4": "M", "set_local_var": "L"}[o]
                lines.append(f"  设置 {kind}[{lits[-2]}] = {lits[-1]}")
            elif show_all and o not in NOISE and o != "push_int":
                lines.append(f"  · {o}")
        if lines:
            out.append(f"## {index} {name}")
            out.extend(lines)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("disasm", type=Path)
    ap.add_argument("--all-ops", action="store_true")
    args = ap.parse_args()
    procs = parse(args.disasm)
    names = {i: n for i, n, _ in procs}
    print("\n".join(outline(procs, names, args.all_ops)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
