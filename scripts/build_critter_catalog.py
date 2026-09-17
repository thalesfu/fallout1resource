#!/usr/bin/env python3
"""Build a catalog of every Fallout 1 critter prototype.

Joins: PRO critter records, PRO_CRIT/PROTO names (English + zh-CN override), AI.TXT packets,
skill formulas (workspace/output/rules/skills.json), every placed instance across the converted
MAP JSON files (with inventory and equipped slots), and existing vault notes that declare
`prototype_id` / `map` / `map_object_id` in their front matter.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fallout1resource.proto import PrototypeCatalog, load_lst, load_pro  # noqa: E402

STAT_KEYS = [
    "ST", "PE", "EN", "CH", "IN", "AG", "LK", "MAX_HP", "MAX_AP", "AC", "UNARMED_DAMAGE", "MELEE_DAMAGE",
    "CARRY_WEIGHT", "SEQUENCE", "HEALING_RATE", "CRITICAL_CHANCE", "BETTER_CRITICALS",
    "DT_NORMAL", "DT_LASER", "DT_FIRE", "DT_PLASMA", "DT_ELECTRICAL", "DT_EMP", "DT_EXPLOSION",
    "DR_NORMAL", "DR_LASER", "DR_FIRE", "DR_PLASMA", "DR_ELECTRICAL", "DR_EMP", "DR_EXPLOSION",
    "RADIATION_RESISTANCE", "POISON_RESISTANCE", "AGE", "GENDER",
]
DAMAGE_TYPES = ["normal", "laser", "fire", "plasma", "electrical", "emp", "explosion"]
BODY_TYPES = ["biped", "quadruped", "robotic"]
IN_LEFT_HAND, IN_RIGHT_HAND, WORN = 0x01000000, 0x02000000, 0x04000000


def msg(path: Path) -> dict[int, str]:
    with path.open(encoding="utf-8-sig") as fh:
        return {int(r["number"]): r["text"] for r in csv.DictReader(fh) if r["effective"] == "True"}


def parse_ai(path: Path) -> dict[int, dict]:
    packets: dict[int, dict] = {}
    current: dict | None = None
    for raw in path.read_text(encoding="latin-1").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            current = {"name": m.group(1).strip()}
            continue
        if current is not None and "=" in line:
            key, value = (t.strip() for t in line.split("=", 1))
            current[key] = int(value) if re.fullmatch(r"-?\d+", value) else value
            if key == "packet_num":
                packets[int(value)] = current
    return packets


def front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--vault-game-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    ws = args.workspace
    raw = ws / "raw/master"
    text = ws / "output/text"

    crit_en, crit_zh = msg(text / "master/TEXT/ENGLISH/GAME/PRO_CRIT.csv"), msg(text / "data/TEXT/ENGLISH/GAME/PRO_CRIT.csv")
    item_en, item_zh = msg(text / "master/TEXT/ENGLISH/GAME/PRO_ITEM.csv"), msg(text / "data/TEXT/ENGLISH/GAME/PRO_ITEM.csv")
    proto_en, proto_zh = msg(text / "master/TEXT/ENGLISH/GAME/PROTO.csv"), msg(text / "data/TEXT/ENGLISH/GAME/PROTO.csv")
    ai = parse_ai(raw / "DATA/AI.TXT")
    skills = json.loads((ws / "output/rules/skills.json").read_text())["skills"]
    scripts_lst = [e.filename for e in load_lst(raw / "SCRIPTS/SCRIPTS.LST").entries]
    catalog = PrototypeCatalog(raw / "PROTO")

    def item_info(pid: int) -> dict:
        proto, _ = catalog.resolve(pid)
        info = {"pid": pid, "name_en": item_en.get(proto.message_id), "name_zh": item_zh.get(proto.message_id),
                "type": proto.subtype_name}
        data = proto.fields.get("data", {})
        if proto.subtype_name == "weapon":
            info["weapon"] = {k: data[k] for k in ("min_damage", "max_damage", "max_range_1", "max_range_2", "min_strength",
                                                   "action_point_cost_1", "action_point_cost_2", "rounds", "ammo_capacity", "perk")}
            info["weapon"]["damage_type"] = DAMAGE_TYPES[data["damage_type"]] if 0 <= data["damage_type"] < 7 else data["damage_type"]
            info["weapon"]["animation_code"] = data["animation_code"]
        elif proto.subtype_name == "armor":
            info["armor"] = {"ac": data["armor_class"], "dt": dict(zip(DAMAGE_TYPES, data["damage_threshold"])),
                             "dr": dict(zip(DAMAGE_TYPES, data["damage_resistance"]))}
        return info

    # existing vault notes
    notes_by_instance: dict[tuple[str, int], str] = {}
    notes_by_proto: dict[int, list[str]] = defaultdict(list)
    for path in args.vault_game_root.rglob("*.md"):
        if "人物" not in path.parts and "生物" not in path.parts:
            continue
        fm = front_matter(path)
        if "prototype_id" in fm and fm["prototype_id"].isdigit():
            notes_by_proto[int(fm["prototype_id"])].append(path.stem)
            if fm.get("map") and fm.get("map_object_id", "").isdigit():
                notes_by_instance[(fm["map"].upper(), int(fm["map_object_id"]))] = path.stem

    # map instances
    instances: dict[int, list[dict]] = defaultdict(list)
    for map_json in sorted((ws / "output/maps/master/MAPS").glob("*/*.json")):
        doc = json.loads(map_json.read_text())
        map_name = map_json.stem.upper()
        for obj in doc["objects"]["entries"]:
            if (obj["pid"] >> 24) != 1:
                continue
            inv = []
            for entry in obj.get("inventory", []):
                child = entry.get("item", entry)
                pid = child["pid"]
                if (pid >> 24) != 0:
                    continue
                flags = child.get("flags", 0)
                slot = "right_hand" if flags & IN_RIGHT_HAND else "left_hand" if flags & IN_LEFT_HAND else "worn" if flags & WORN else None
                inv.append({"pid": pid, "quantity": entry.get("quantity", 1), "slot": slot})
            combat = obj.get("update_data", {}).get("combat", {})
            instances[obj["pid"] & 0xFFFFFF].append({
                "map": map_name, "elevation": obj.get("elevation_group"), "object_id": obj["object_id"],
                "tile": obj["tile"], "script": obj.get("script_filename"),
                "hp": obj.get("update_data", {}).get("hit_points"), "team": combat.get("team"), "ai_packet": combat.get("ai_packet"),
                "inventory": inv, "note": notes_by_instance.get((map_name, obj["object_id"])),
            })

    item_cache: dict[int, dict] = {}
    critters = []
    for index, entry in enumerate(load_lst(raw / "PROTO/CRITTERS/CRITTERS.LST").entries, start=1):
        if not entry.filename:
            continue
        proto = load_pro(raw / "PROTO/CRITTERS" / entry.filename.upper())
        f = proto.fields
        stats = {k: b + o for k, b, o in zip(STAT_KEYS, f["base_stats"], f["bonus_stats"])}
        skill_values = {}
        for s in skills:
            bonus = (stats[s["stat1"]] + stats[s["stat2"]]) * s["stat_multiplier"] // 2 if s["stat2"] else stats[s["stat1"]] * s["stat_multiplier"]
            skill_values[s["key"]] = s["base"] + bonus + f["skills"][s["id"]] * s["points_multiplier"]
        script = None
        if f["script_id"] != -1:
            script_index = f["script_id"] & 0xFFFFFF
            script = scripts_lst[script_index] if script_index < len(scripts_lst) else None
        inst = instances.get(index, [])
        for i in inst:
            for it in i["inventory"]:
                if it["pid"] not in item_cache:
                    item_cache[it["pid"]] = item_info(it["pid"])
        critters.append({
            "prototype_id": index, "pid": proto.pid, "file": entry.filename,
            "name_en": crit_en.get(proto.message_id), "name_zh": crit_zh.get(proto.message_id),
            "desc_en": crit_en.get(proto.message_id + 1), "desc_zh": crit_zh.get(proto.message_id + 1),
            "kill_type": f["kill_type"], "kill_type_en": proto_en.get(450 + f["kill_type"]), "kill_type_zh": proto_zh.get(450 + f["kill_type"]),
            "body_type": BODY_TYPES[f["body_type"]] if 0 <= f["body_type"] < 3 else f["body_type"],
            "experience": f["experience"], "team": f["team"], "ai_packet": f["ai_packet"],
            "ai": ai.get(f["ai_packet"]), "critter_flags": f["critter_flags"], "fid": proto.fid, "script": script,
            "base_stats": dict(zip(STAT_KEYS, f["base_stats"])), "bonus_stats": dict(zip(STAT_KEYS, f["bonus_stats"])),
            "stats": stats, "skill_points": dict(zip([s["key"] for s in skills], f["skills"])), "skill_values": skill_values,
            "instances": inst, "notes": sorted(set(notes_by_proto.get(index, []))),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"critters": critters, "items": {str(k): v for k, v in sorted(item_cache.items())}},
                                      ensure_ascii=False, indent=1) + "\n")
    print(f"{len(critters)} critter prototypes, {sum(len(c['instances']) for c in critters)} map instances, "
          f"{len(item_cache)} carried item prototypes -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
