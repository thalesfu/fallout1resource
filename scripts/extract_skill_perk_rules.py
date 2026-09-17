#!/usr/bin/env python3
"""Extract Fallout 1 skill and perk rule tables.

Numbers come from the fallout1-ce reimplementation (`src/game/skill.cc`, `perk.cc`),
names/descriptions from the extracted MSG conversions (English DAT + loose zh-CN override).
The CE checkout is read-only input; its commit hash is recorded in the output.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

PRIMARY = ["ST", "PE", "EN", "CH", "IN", "AG", "LK"]
STATS = [
    "ST", "PE", "EN", "CH", "IN", "AG", "LK",
    "MAX_HP", "MAX_AP", "AC", "UNARMED_DAMAGE", "MELEE_DAMAGE", "CARRY_WEIGHT",
    "SEQUENCE", "HEALING_RATE", "CRITICAL_CHANCE", "BETTER_CRITICALS",
    "DT", "DT_LASER", "DT_FIRE", "DT_PLASMA", "DT_ELECTRICAL", "DT_EMP", "DT_EXPLOSION",
    "DR", "DR_LASER", "DR_FIRE", "DR_PLASMA", "DR_ELECTRICAL", "DR_EMP", "DR_EXPLOSION",
    "RADIATION_RESISTANCE", "POISON_RESISTANCE", "AGE", "GENDER",
]
SKILL_KEYS = [
    "SMALL_GUNS", "BIG_GUNS", "ENERGY_WEAPONS", "UNARMED", "MELEE_WEAPONS", "THROWING",
    "FIRST_AID", "DOCTOR", "SNEAK", "LOCKPICK", "STEAL", "TRAPS", "SCIENCE", "REPAIR",
    "SPEECH", "BARTER", "GAMBLING", "OUTDOORSMAN",
]


def enum_names(header: Path, enum: str, prefix: str) -> list[str]:
    text = header.read_text()
    body = re.search(r"typedef enum %s \{(.*?)\} %s;" % (enum, enum), text, re.S).group(1)
    names = re.findall(prefix + r"([A-Z0-9_]+),", body)
    return [n for n in names if n != "COUNT"]


def c_table(source: Path, name: str) -> list[list[str]]:
    text = source.read_text()
    body = re.search(name + r"\[[A-Z_]+\] = \{(.*?)\n\};", text, re.S).group(1)
    rows = []
    for m in re.finditer(r"\{ NULL, NULL,(.*?)\},?\s*$", body, re.M):
        rows.append([t.strip() for t in m.group(1).replace("{", "").replace("}", "").split(",") if t.strip() and t.strip() != "NULL"])
    return rows


def msg(path: Path) -> dict[int, str]:
    with path.open(encoding="utf-8-sig") as fh:
        return {int(r["number"]): r["text"] for r in csv.DictReader(fh) if r["effective"] == "True"}


def stat_ref(token: str) -> str | None:
    if token in ("-1", "STAT_INVALID"):
        return None
    if token.startswith("STAT_"):
        return {"STRENGTH": "ST", "PERCEPTION": "PE", "ENDURANCE": "EN", "CHARISMA": "CH",
                "INTELLIGENCE": "IN", "AGILITY": "AG", "LUCK": "LK"}[token[5:]]
    return STATS[int(token)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ce-root", type=Path, required=True)
    ap.add_argument("--text-root", type=Path, required=True, help="workspace/output/text")
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    game = args.ce_root / "src/game"
    commit = subprocess.run(["git", "-C", str(args.ce_root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    en = lambda n: msg(args.text_root / f"master/TEXT/ENGLISH/GAME/{n}.csv")  # noqa: E731
    zh = lambda n: msg(args.text_root / f"data/TEXT/ENGLISH/GAME/{n}.csv")  # noqa: E731
    skill_en, skill_zh, perk_en, perk_zh = en("SKILL"), zh("SKILL"), en("PERK"), zh("PERK")

    skills = []
    for i, row in enumerate(c_table(game / "skill.cc", "skill_data")):
        art, base, mult, s1, s2, pts, xp, xp_bonus = row
        skills.append({
            "id": i, "key": SKILL_KEYS[i],
            "name_en": skill_en[100 + i], "name_zh": skill_zh[100 + i],
            "desc_en": skill_en[200 + i], "desc_zh": skill_zh[200 + i],
            "formula_msg": skill_en[300 + i],
            "base": int(base), "stat_multiplier": int(mult),
            "stat1": stat_ref(s1), "stat2": stat_ref(s2),
            "points_multiplier": int(pts), "use_experience": int(xp),
            "experience_bonus_from_difficulty": bool(int(xp_bonus)), "skilldex_art": int(art),
        })

    perk_keys = enum_names(game / "perk_defs.h", "Perk", "PERK_")
    perks = []
    for i, row in enumerate(c_table(game / "perk.cc", "perk_data")):
        max_rank, min_level, stat, stat_mod, req_skill, req_skill_level, *req = map(int, row)
        perks.append({
            "id": i, "key": perk_keys[i],
            "name_en": perk_en[101 + i], "name_zh": perk_zh[101 + i],
            "desc_en": perk_en[201 + i], "desc_zh": perk_zh[201 + i],
            "selectable": max_rank != -1, "max_rank": max_rank, "min_level": min_level,
            "stat_bonus": {"stat": STATS[stat], "per_rank": stat_mod} if stat != -1 else None,
            "required_skill": {"skill": SKILL_KEYS[req_skill], "level": req_skill_level} if req_skill != -1 else None,
            # For selectable perks these are minimums; for max_rank -1 perks they are applied stat deltas.
            "primary_stats": {k: v for k, v in zip(PRIMARY, req) if v},
        })

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = {"source": "alexbatalov/fallout1-ce", "commit": commit, "engine_version": "1.1 (fallout1-re)"}
    for name, rows in (("skills", skills), ("perks", perks)):
        (out / f"{name}.json").write_text(json.dumps({"meta": meta, name: rows}, ensure_ascii=False, indent=2) + "\n")
        with (out / f"{name}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()})
    print(f"{len(skills)} skills, {len(perks)} perks -> {out} (ce {commit[:10]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
