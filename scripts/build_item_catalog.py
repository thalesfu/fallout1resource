#!/usr/bin/env python3
"""Build a catalog of every Fallout 1 item prototype and where each one is placed.

Joins: item PRO records (weapon/ammo/armor/drug/misc fields), PRO_ITEM names and descriptions
(English DAT + loose zh-CN override), every placement across the converted MAP JSON files
(top-level, inside containers, and carried by critters), and a map→region name table derived from
the vault's character notes (their front matter carries `map`/`elevation`, their folder path the
Chinese location and region names).
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
from fallout1resource.proto import load_lst, load_pro  # noqa: E402

DAMAGE_TYPES = ["normal", "laser", "fire", "plasma", "electrical", "emp", "explosion"]
ATTACK_MODES = {0: "无", 1: "拳击", 2: "踢击", 3: "挥击", 4: "突刺", 5: "投掷", 6: "单发", 7: "连发", 8: "连续"}
ANIMATION_CODE = {0: "徒手／无持械动画", 1: "刀", 2: "棍棒", 3: "大锤", 4: "长柄", 5: "手枪", 6: "冲锋枪",
                  7: "步枪", 8: "大型枪械", 9: "多管／加特林", 10: "火箭筒"}


def msg(path: Path) -> dict[int, str]:
    with path.open(encoding="utf-8-sig") as fh:
        return {int(r["number"]): r["text"] for r in csv.DictReader(fh) if r["effective"] == "True"}


MAP_FALLBACK = {
    "CAVES": ("Shady Sands 沙荫镇", "Caves 洞穴"),
    "V13ENT": ("Vault 13 13号避难所", "Entrance 入口"),
    "VAULTBUR": ("Vault 15 15号避难所", "Buried Vault 废弃避难所"),
    "WATRSHD": ("Necropolis 大墓地", "Watershed 供水区"),
    "LARIPPER": ("Boneyard 晒骨场", "Rippers 剃刀帮"),
    "MSTRLR12": ("Cathedral 大教堂", "Master's Lair 大师巢穴 1–2 层"),
    "MSTRLR34": ("Cathedral 大教堂", "Master's Lair 大师巢穴 3–4 层"),
    "VIPERS": ("Random Encounter 随机遭遇", "Vipers 毒蛇帮"),
    "USEDCAR": ("Special Encounter 特殊遭遇", "Used Car Lot 二手车场"),
    "FOOT": ("Special Encounter 特殊遭遇", "Footprints 神秘脚印"),
    "TALKCOW": ("Special Encounter 特殊遭遇", "Talking Cow 会说话的牛"),
    "COLATRUK": ("Special Encounter 特殊遭遇", "Nuka-Cola Truck 可乐卡车"),
    "TARDIS": ("Special Encounter 特殊遭遇", "TARDIS 蓝盒子"),
    "FSAUSER": ("Special Encounter 特殊遭遇", "Crashed Spaceship 坠毁飞船"),
    "JUNKDEMO": ("Demo Map 演示地图", "不在正式流程中"),
}


def region_table(vault_root: Path) -> dict[tuple[str, int], tuple[str, str]]:
    """(MAP, elevation) -> (location, region), taken from existing character notes."""
    table: dict[tuple[str, int], tuple[str, str]] = {}
    for path in vault_root.rglob("*.md"):
        if "人物" not in path.parts or "地点" not in path.parts:
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:600]
        m = re.search(r"^map:\s*(\S+)\s*$", head, re.M)
        e = re.search(r"^elevation:\s*(\d+)\s*$", head, re.M)
        if not m or not e:
            continue
        parts = path.parts
        i = parts.index("地点")
        location = parts[i + 1] if len(parts) > i + 1 else ""
        region = parts[i + 2] if len(parts) > i + 2 and parts[i + 2] != "人物" else ""
        table.setdefault((m.group(1).upper(), int(e.group(1))), (location, region))
    return table


def walk_inventory(obj: dict, owner: dict | None, out: list, depth: int = 0) -> None:
    for entry in obj.get("inventory", []):
        child = entry.get("item", entry)
        out.append((child, entry.get("quantity", 1), owner or obj))
        walk_inventory(child, owner or obj, out, depth + 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--vault-game-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    ws, raw, text = args.workspace, args.workspace / "raw/master", args.workspace / "output/text"

    en, zh = msg(text / "master/TEXT/ENGLISH/GAME/PRO_ITEM.csv"), msg(text / "data/TEXT/ENGLISH/GAME/PRO_ITEM.csv")
    crit_en, crit_zh = msg(text / "master/TEXT/ENGLISH/GAME/PRO_CRIT.csv"), msg(text / "data/TEXT/ENGLISH/GAME/PRO_CRIT.csv")
    scen_zh = msg(text / "data/TEXT/ENGLISH/GAME/PRO_SCEN.csv")
    regions = region_table(args.vault_game_root)

    items: dict[int, dict] = {}
    root = raw / "PROTO/ITEMS"
    for index, entry in enumerate(load_lst(root / "ITEMS.LST").entries, start=1):
        if not entry.filename:
            continue
        proto = load_pro(root / entry.filename.upper())
        f, data = proto.fields, proto.fields.get("data", {})
        rec = {
            "prototype_id": index, "pid": proto.pid, "file": entry.filename, "type": proto.subtype_name,
            "name_en": en.get(proto.message_id), "name_zh": zh.get(proto.message_id),
            "desc_en": en.get(proto.message_id + 1), "desc_zh": zh.get(proto.message_id + 1),
            "weight": f.get("weight"), "size": f.get("size"), "cost": f.get("cost"),
            "extended_flags": f.get("extended_flags", 0), "data": data,
        }
        if proto.subtype_name == "weapon":
            rec["weapon"] = {
                "min_damage": data["min_damage"], "max_damage": data["max_damage"],
                "damage_type": DAMAGE_TYPES[data["damage_type"]] if 0 <= data["damage_type"] < 7 else data["damage_type"],
                "range_primary": data["max_range_1"], "range_secondary": data["max_range_2"],
                "ap_primary": data["action_point_cost_1"], "ap_secondary": data["action_point_cost_2"],
                "min_strength": data["min_strength"], "rounds": data["rounds"],
                "caliber": data["caliber"], "ammo_type_pid": data["ammo_type_pid"], "ammo_capacity": data["ammo_capacity"],
                "perk": data["perk"], "animation_code": data["animation_code"],
                "animation_zh": ANIMATION_CODE.get(data["animation_code"], data["animation_code"]),
                "critical_failure_type": data["critical_failure_type"], "projectile_pid": data["projectile_pid"],
                "two_handed": bool(f.get("extended_flags", 0) & 0x00000200),
                "attack_primary": ATTACK_MODES.get(f.get("extended_flags", 0) & 0xF, "?"),
                "attack_secondary": ATTACK_MODES.get((f.get("extended_flags", 0) >> 4) & 0xF, "?"),
            }
        elif proto.subtype_name == "ammo":
            rec["ammo"] = {"caliber": data["caliber"], "quantity": data["quantity"],
                           "ac_modifier": data["armor_class_modifier"], "dr_modifier": data["damage_resistance_modifier"],
                           "damage_multiplier": data["damage_multiplier"], "damage_divisor": data["damage_divisor"]}
        elif proto.subtype_name == "armor":
            rec["armor"] = {"ac": data["armor_class"], "perk": data["perk"],
                            "dt": dict(zip(DAMAGE_TYPES, data["damage_threshold"])),
                            "dr": dict(zip(DAMAGE_TYPES, data["damage_resistance"]))}
        items[index] = rec

    placements: dict[int, list] = defaultdict(list)
    for map_json in sorted((ws / "output/maps/master/MAPS").glob("*/*.json")):
        doc = json.loads(map_json.read_text())
        map_name = map_json.stem.upper()
        for obj in doc["objects"]["entries"]:
            nested: list = []
            walk_inventory(obj, None, nested)
            if (obj["pid"] >> 24) == 0:
                placements[obj["pid"] & 0xFFFFFF].append({
                    "map": map_name, "elevation": obj.get("elevation_group"), "object_id": obj["object_id"],
                    "quantity": 1, "holder": None, "holder_kind": "ground", "tile": obj["tile"],
                })
            for child, quantity, owner in nested:
                if (child["pid"] >> 24) != 0:
                    continue
                kind = {1: "critter", 0: "container", 2: "scenery"}.get(owner["pid"] >> 24, "other")
                proto_index = owner["pid"] & 0xFFFFFF
                placements[child["pid"] & 0xFFFFFF].append({
                    "map": map_name, "elevation": owner.get("elevation_group"), "object_id": child["object_id"],
                    "quantity": quantity, "holder": {"object_id": owner["object_id"], "pid_index": proto_index,
                                                     "kind": kind, "name": None},
                    "holder_kind": kind, "tile": owner["tile"],
                })

    # resolve holder names: critters from PRO_CRIT, containers/scenery from PRO_ITEM / PRO_SCEN
    crit_names = {}
    crit_root = raw / "PROTO/CRITTERS"
    for index, entry in enumerate(load_lst(crit_root / "CRITTERS.LST").entries, start=1):
        if entry.filename:
            proto = load_pro(crit_root / entry.filename.upper())
            crit_names[index] = crit_zh.get(proto.message_id) or crit_en.get(proto.message_id)
    scen_names = {}
    scen_root = raw / "PROTO/SCENERY"
    for index, entry in enumerate(load_lst(scen_root / "SCENERY.LST").entries, start=1):
        if entry.filename:
            proto = load_pro(scen_root / entry.filename.upper())
            scen_names[index] = scen_zh.get(proto.message_id)
    for rows in placements.values():
        for row in rows:
            h = row["holder"]
            if not h:
                continue
            h["name"] = ({"critter": crit_names, "container": {i: v["name_zh"] or v["name_en"] for i, v in items.items()},
                          "scenery": scen_names}.get(h["kind"], {})).get(h["pid_index"])
        for row in rows:
            loc = regions.get((row["map"], row["elevation"] or 0)) or MAP_FALLBACK.get(row["map"])
            row["location"], row["region"] = loc if loc else (None, None)

    for index, rec in items.items():
        rec["placements"] = placements.get(index, [])
        rec["total_quantity"] = sum(p["quantity"] for p in rec["placements"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"items": list(items.values()),
                                       "region_table": {f"{k[0]}:{k[1]}": v for k, v in sorted(regions.items())}},
                                      ensure_ascii=False, indent=1) + "\n")
    kinds = defaultdict(int)
    for rec in items.values():
        kinds[rec["type"]] += 1
    print(f"{len(items)} 个物品原型 {dict(kinds)}，放置 {sum(len(v) for v in placements.values())} 处，"
          f"地图区域映射 {len(regions)} 条 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
