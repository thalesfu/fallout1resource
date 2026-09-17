#!/usr/bin/env python3
"""Generate Obsidian item notes for items referenced by HUBOLDTN.MAP."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATEGORY_DIRS = {
    "weapon": ("Weapon 武器", "武器"),
    "ammo": ("Ammo 弹药", "弹药"),
    "armor": ("Armor 装甲", "装甲"),
    "drug": ("Drug 药品", "药品"),
    "container": ("Container 容器", "容器"),
    "key": ("Key 钥匙", "钥匙"),
    "caps": ("Caps 瓶盖", "瓶盖"),
    "misc": ("Misc 杂项", "杂项"),
}

MATERIALS = {
    0: "Glass 玻璃",
    1: "Metal 金属",
    2: "Plastic 塑料",
    3: "Wood 木材",
    4: "Dirt 泥土",
    5: "Stone 石材",
    6: "Cement 水泥",
    7: "Leather 皮革",
}

DAMAGE_TYPES = {
    0: "Normal 普通伤害",
    1: "Laser 激光伤害",
    2: "Fire 火焰伤害",
    3: "Plasma 等离子伤害",
    4: "Electrical 电击伤害",
    5: "EMP 电磁脉冲伤害",
    6: "Explosion 爆炸伤害",
}

CALIBERS = {
    0: "None 无",
    1: "Rocket 火箭",
    2: "Flamethrower Fuel 火焰喷射器燃料",
    3: "Small Energy Cell 小能源电池",
    4: "Micro Fusion Cell 微型核融合电池",
    5: ".223",
    6: "5mm",
    7: ".40",
    8: "10mm",
    9: ".44",
    10: "14mm",
    11: "12 Gauge 12号霰弹",
    12: "9mm",
    13: "BB",
}

ATTACK_MODES = {
    0: "None 无",
    1: "Punch 拳击",
    2: "Kick 踢击",
    3: "Swing 挥击",
    4: "Thrust 刺击",
    5: "Throw 投掷",
    6: "Single 单发",
    7: "Burst 连发",
    8: "Continuous 持续喷射",
}

WEAPON_ANIMATIONS = {
    0: "None 无",
    1: "Knife 刀",
    2: "Club 棍棒",
    3: "Hammer 铁锤",
    4: "Spear 长矛",
    5: "Pistol 手枪",
    6: "SMG 冲锋枪",
    7: "Shotgun 霰弹枪",
    8: "Laser Rifle 激光步枪",
    9: "Minigun 机枪",
    10: "Launcher 发射器",
}

WEAPON_PERKS = {
    -1: "无",
    58: "Long Range 远射程",
    59: "Accurate 精准",
    60: "Penetrate 穿透",
    61: "Knockback 击退",
}

STAT_NAMES = {
    0: "Strength 力量",
    1: "Perception 感知",
    2: "Endurance 耐力",
    3: "Charisma 魅力",
    4: "Intelligence 智力",
    5: "Agility 敏捷",
    6: "Luck 幸运",
    7: "Maximum Hit Points 最大生命值",
    8: "Maximum Action Points 最大行动点",
    9: "Armor Class 装甲等级",
    10: "Unarmed Damage 徒手伤害",
    11: "Melee Damage 近战伤害",
    12: "Carry Weight 负重",
    13: "Sequence 行动顺序",
    14: "Healing Rate 治疗速率",
    15: "Critical Chance 暴击率",
    16: "Better Criticals 强化暴击",
    17: "Normal Damage Threshold 普通伤害阈值",
    18: "Laser Damage Threshold 激光伤害阈值",
    19: "Fire Damage Threshold 火焰伤害阈值",
    20: "Plasma Damage Threshold 等离子伤害阈值",
    21: "Electrical Damage Threshold 电击伤害阈值",
    22: "EMP Damage Threshold 电磁脉冲伤害阈值",
    23: "Explosion Damage Threshold 爆炸伤害阈值",
    24: "Normal Damage Resistance 普通伤害抗性",
    25: "Laser Damage Resistance 激光伤害抗性",
    26: "Fire Damage Resistance 火焰伤害抗性",
    27: "Plasma Damage Resistance 等离子伤害抗性",
    28: "Electrical Damage Resistance 电击伤害抗性",
    29: "EMP Damage Resistance 电磁脉冲伤害抗性",
    30: "Explosion Damage Resistance 爆炸伤害抗性",
    31: "Radiation Resistance 辐射抗性",
    32: "Poison Resistance 毒素抗性",
    33: "Age 年龄",
    34: "Gender 性别",
    35: "Current Hit Points 当前生命值",
    36: "Poison Level 中毒程度",
    37: "Radiation Level 辐射程度",
}

WITHDRAWAL_EFFECTS = {
    53: "Nuka-Cola Addiction 核子可乐成瘾",
    54: "Buffout Addiction 壮大灵成瘾",
    55: "Mentats Addiction 曼他特成瘾",
    56: "Psycho Addiction 疯狂药成瘾",
    57: "RadAway Addiction 放射药成瘾",
}

LOCATION_PAGES = {
    "Vault 13": "Vault 13 13号避难所",
    "Vault 15": "Vault 15 15号避难所",
    "Necropolis": "Necropolis 大墓地",
    "Junktown": "Junktown 迦克镇",
    "Brotherhood": "Brotherhood 钢铁兄弟会",
    "Cathedral": "Cathedral 大教堂",
    "Shady Sands": "Shady Sands 沙荫镇",
    "Boneyard": "Boneyard 晒骨场",
    "Military Base": "Military Base 军事基地",
    "Hub": "Hub 哈勃城",
    "The Glow": "The Glow 闪光之地",
    "Glow": "The Glow 闪光之地",
    "Raiders": "Raiders 歹徒",
}

EXTERNAL_STOCK = {
    ("HUBDWNTN.MAP", 3177): "BethBox 贝斯的地图外交易库存箱",
    ("HUBDWNTN.MAP", 3297): "MitchBox 米奇的地图外交易库存箱",
    ("HUBOLDTN.MAP", 28): "JakeDesk 雅各布的地图外交易库存箱",
    ("HUBOLDTN.MAP", 163): "VanceBox 万斯的地图外交易库存箱",
}

CONTAINER_NAMES = {"Bookcase", "Bookshelf", "Fridge", "Footlocker", "Desk", "Crate"}

NOTE_ADDITIONS = {
    125: "**提可的评价**：更喜欢烈一点的啤酒，核子可乐之类的。",
}

LOCATION_ADDITIONS = {
    13: "**相关任务**：完成[[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）|从哈勃城救出新成员]]后，可将火箭发射器选为装备奖励，并向 Michael 迈克尔领取。",
    41: "**相关任务**：完成[[Find the Missing Caravans 寻找失踪的商队（发起人 ID 937）|寻找失踪的商队]]并向罗格尔出示变种人通话记录磁盘后，获得 800 瓶盖。",
    115: "**相关任务**：完成[[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）|从哈勃城救出新成员]]后，可将超级铁锤选为装备奖励，并向 Michael 迈克尔领取。",
}


@dataclass(frozen=True)
class ItemGroup:
    key: tuple[str, str]
    english: str
    chinese: str
    prototypes: tuple[dict[str, Any], ...]
    pids: tuple[int, ...]
    category: str
    title: str
    filename: str


def effective_messages(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(entry["number"]): str(entry["text"])
        for entry in payload["entries"]
        if entry.get("effective")
    }


def read_lst(path: Path) -> list[str]:
    result = []
    for raw in path.read_text(encoding="cp1252").splitlines():
        value = raw.split(";", 1)[0].strip().split(" ", 1)[0].strip()
        result.append(value)
    return result


def bilingual(english: str, chinese: str) -> str:
    english = english.strip()
    chinese = chinese.strip()
    if not english:
        return chinese or "—"
    if not chinese or english.casefold() == chinese.casefold():
        return english
    return f"{english} {chinese}"


def safe_filename(title: str) -> str:
    value = title.lstrip(".").replace("/", "／").replace(":", "：")
    return re.sub(r"[\\\x00-\x1F]", "", value).strip() + ".md"


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def table_text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")


def wikilink(target: str, display: str) -> str:
    return f"[[{target}\\|{display}]]"


def category_for(english: str, prototypes: list[dict[str, Any]]) -> str:
    pids = {int(proto["list_index"]) for proto in prototypes}
    if 41 in pids:
        return "caps"
    if english in CONTAINER_NAMES or any(proto.get("subtype_name") == "container" for proto in prototypes):
        return "container"
    return str(prototypes[0].get("subtype_name") or "misc")


def make_groups(
    map_doc: dict[str, Any],
    english_items: dict[int, str],
    chinese_items: dict[int, str],
) -> tuple[list[ItemGroup], dict[int, ItemGroup]]:
    prototypes = {
        (proto["type"], int(proto["list_index"])): proto
        for proto in map_doc["referenced_prototypes"]
    }
    target_pids: set[int] = set()

    def collect(obj: dict[str, Any]) -> None:
        prototype = obj.get("prototype", {})
        if prototype.get("type") == "item":
            target_pids.add(int(prototype["list_index"]))
        for entry in obj.get("inventory", []):
            collect(entry.get("item", entry))

    for obj in map_doc["objects"]["entries"]:
        collect(obj)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pid in sorted(target_pids):
        prototype = prototypes[("item", pid)]
        message_id = int(prototype["message_id"])
        english = english_items.get(message_id, f"Item {pid}").strip()
        chinese = chinese_items.get(message_id, english).strip()
        grouped[(english, chinese)].append(prototype)

    groups: list[ItemGroup] = []
    by_pid: dict[int, ItemGroup] = {}
    for key, values in sorted(grouped.items(), key=lambda item: item[0][0].casefold()):
        english, chinese = key
        pids = tuple(sorted(int(proto["list_index"]) for proto in values))
        category = category_for(english, values)
        title = bilingual(english, chinese)
        group = ItemGroup(
            key=key,
            english=english,
            chinese=chinese,
            prototypes=tuple(sorted(values, key=lambda proto: int(proto["list_index"]))),
            pids=pids,
            category=category,
            title=title,
            filename=safe_filename(title),
        )
        groups.append(group)
        for pid in pids:
            by_pid[pid] = group
    return groups, by_pid


def parse_old_town_people(vault: Path) -> dict[int, tuple[str, str]]:
    root = vault / "地点/Hub 哈勃城/Old Town 旧城区/人物"
    result: dict[int, tuple[str, str]] = {}
    if not root.is_dir():
        return result
    for path in root.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^map_object_id:\s*(\d+)\s*$", text, re.MULTILINE)
        heading = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
        if match:
            result[int(match.group(1))] = (path.stem, heading.group(1) if heading else path.stem)
    return result


def map_comment_names(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"^#\s*(.+?),\s*([A-Za-z0-9_]+\.MAP)\s*$", re.IGNORECASE)
    for line in path.read_text(encoding="cp1252").splitlines():
        match = pattern.match(line.strip())
        if match:
            result[match.group(2).upper()] = match.group(1).strip()
    return result


def map_metadata(
    repo: Path,
    english_map: dict[int, str],
    chinese_map: dict[int, str],
) -> dict[str, dict[str, Any]]:
    comments = map_comment_names(repo / "workspace/raw/master/TEXT/ENGLISH/GAME/MAP.MSG")
    result: dict[str, dict[str, Any]] = {}
    for number, value in english_map.items():
        upper = value.strip().upper()
        if number >= 100 or not upper.endswith(".MAP"):
            continue
        result[upper] = {
            "index": number,
            "world_en": english_map.get(100 + number, "").strip(),
            "world_zh": chinese_map.get(100 + number, "").strip(),
            "comment": comments.get(upper, upper),
            "areas_en": [english_map.get(200 + number * 3 + elevation, "").strip() for elevation in range(3)],
            "areas_zh": [chinese_map.get(200 + number * 3 + elevation, "").strip() for elevation in range(3)],
        }
    return result


def critter_name_config(repo: Path) -> dict[str, dict[str, str]]:
    """Load the verified Hub naming overrides used by the map renderer.

    SCRNAME.MSG is not indexed by SCRIPTS.LST, so joining those two resources
    produces unrelated names.  The renderer configs contain the script-name
    overrides that were checked against the extracted dialogue resources.
    """
    result = {"prototype_names": {}, "script_names": {}, "bilingual_names": {}}
    for filename in ("huboldtn-critter-names.zh-CN.json", "hub-critter-names.zh-CN.json"):
        path = repo / "config" / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in result:
            result[key].update(
                {str(name).casefold(): str(value) for name, value in payload.get(key, {}).items()}
            )
    return result


def prototype_display(
    prototype: dict[str, Any],
    english_critters: dict[int, str],
    chinese_critters: dict[int, str],
    english_items: dict[int, str],
    chinese_items: dict[int, str],
) -> str:
    message_id = int(prototype.get("message_id", int(prototype.get("list_index", 0)) * 100))
    if prototype.get("type") == "critter":
        return bilingual(english_critters.get(message_id, ""), chinese_critters.get(message_id, ""))
    if prototype.get("type") == "item":
        return bilingual(english_items.get(message_id, ""), chinese_items.get(message_id, ""))
    return prototype.get("type", "对象")


def holder_display(
    map_name: str,
    parent: dict[str, Any],
    parent_prototype: dict[str, Any],
    critter_names: dict[str, dict[str, str]],
    english_critters: dict[int, str],
    chinese_critters: dict[int, str],
    english_items: dict[int, str],
    chinese_items: dict[int, str],
) -> str:
    direct = prototype_display(
        parent_prototype,
        english_critters,
        chinese_critters,
        english_items,
        chinese_items,
    )
    if parent_prototype.get("type") != "critter" or not map_name.startswith("HUB"):
        return direct

    script_filename = str(parent.get("script_filename") or "")
    script_key = script_filename.casefold()
    script_stem = Path(script_filename).stem.casefold()
    translated = critter_names["script_names"].get(script_key)
    if translated:
        english = critter_names["bilingual_names"].get(script_stem)
        return bilingual(english or "", translated)

    english = english_critters.get(int(parent_prototype.get("message_id", 0)), "")
    translated = critter_names["prototype_names"].get(english.casefold())
    if translated:
        named = critter_names["bilingual_names"].get(english.casefold())
        return bilingual(named or "", translated)
    return direct


def scan_occurrences(
    repo: Path,
    by_pid: dict[int, ItemGroup],
    map_info: dict[str, dict[str, Any]],
    old_town_people: dict[int, tuple[str, str]],
    critter_names: dict[str, dict[str, str]],
    english_critters: dict[int, str],
    chinese_critters: dict[int, str],
    english_items: dict[int, str],
    chinese_items: dict[int, str],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    maps_root = repo / "workspace/output/maps/master/MAPS"

    for path in sorted(maps_root.glob("*/*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        map_name = str(document.get("header", {}).get("name") or path.parent.name).upper()
        metadata = map_info.get(map_name, {})
        if not metadata:
            # Converted development/demo maps not registered in MAP.MSG are not
            # reachable locations in the released game.
            continue
        prototype_lookup = {
            (prototype.get("type"), int(prototype.get("list_index", -1))): prototype
            for prototype in document.get("referenced_prototypes", [])
        }

        def walk(obj: dict[str, Any], parent: dict[str, Any] | None = None, quantity: int = 1) -> None:
            prototype = obj.get("prototype", {})
            if prototype.get("type") == "item":
                pid = int(prototype.get("list_index", -1))
                group = by_pid.get(pid)
                if group is not None:
                    elevation = int((parent or obj).get("elevation_group", obj.get("elevation_group", 0)) or 0)
                    world_en = str(metadata.get("world_en") or "").strip()
                    world_zh = str(metadata.get("world_zh") or world_en).strip()
                    area_en_values = metadata.get("areas_en") or []
                    area_zh_values = metadata.get("areas_zh") or []
                    area_en = area_en_values[elevation] if elevation < len(area_en_values) else ""
                    area_zh = area_zh_values[elevation] if elevation < len(area_zh_values) else ""
                    area = bilingual(area_en, area_zh) if area_en or area_zh else str(metadata.get("comment") or map_name)

                    unavailable = False
                    if parent is None:
                        holder = "地面"
                        note = "地图对象。" if prototype.get("subtype_name") == "container" else "位于地面。"
                        external_label = EXTERNAL_STOCK.get((map_name, int(obj.get("object_id", -1))))
                        if external_label:
                            unavailable = True
                            holder = f"⚠ {external_label}"
                            note = "地图外交易库存箱，不能直接取得。"
                    else:
                        parent_id = int(parent.get("object_id", -1))
                        parent_proto_ref = parent.get("prototype", {})
                        parent_proto = prototype_lookup.get(
                            (parent_proto_ref.get("type"), int(parent_proto_ref.get("list_index", -1))),
                            parent_proto_ref,
                        )
                        external_label = EXTERNAL_STOCK.get((map_name, parent_id))
                        if external_label:
                            unavailable = True
                            base = prototype_display(parent_proto, english_critters, chinese_critters, english_items, chinese_items)
                            holder = f"⚠ {base}（{external_label}，ID {parent_id}）"
                            note = "地图外交易库存，不能直接取得。"
                        elif map_name == "HUBOLDTN.MAP" and parent_id in old_town_people:
                            target, display = old_town_people[parent_id]
                            holder = f"{wikilink(target, display)}（ID {parent_id}）"
                            note = "人物携带。"
                        else:
                            display = holder_display(
                                map_name,
                                parent,
                                parent_proto,
                                critter_names,
                                english_critters,
                                chinese_critters,
                                english_items,
                                chinese_items,
                            )
                            holder = f"{display}（ID {parent_id}）"
                            note = "人物携带。" if parent_proto.get("type") == "critter" else "位于容器内。"

                    if map_name == "HUBOLDTN.MAP" and area_en == "Thieves Circle":
                        location = wikilink("Hub 哈勃城#区域与楼层", "Thieves Circle 贼窝")
                    elif map_name == "HUBOLDTN.MAP":
                        location = wikilink("Old Town 旧城区", "哈勃城旧城区")
                    elif world_en in LOCATION_PAGES:
                        location = wikilink(LOCATION_PAGES[world_en], world_zh or world_en)
                    else:
                        location = bilingual(world_en, world_zh) if world_en or world_zh else str(metadata.get("comment") or map_name)

                    occurrences[group.key].append(
                        {
                            "location": location,
                            "area": area,
                            "holder": holder,
                            "object_id": int(obj.get("object_id", -1)),
                            "quantity": quantity,
                            "note": note,
                            "unavailable": unavailable,
                            "map": map_name,
                        }
                    )

            for entry in obj.get("inventory", []):
                walk(entry.get("item", entry), obj, int(entry.get("quantity", 1)))

        for top_level in document.get("objects", {}).get("entries", []):
            walk(top_level)

    for rows in occurrences.values():
        rows.sort(
            key=lambda row: (
                bool(row["unavailable"]),
                row["location"].casefold(),
                row["area"].casefold(),
                row["map"],
                row["object_id"],
            )
        )
    return occurrences


def png_width(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return 0
    return int(struct.unpack(">I", header[16:20])[0])


def art_frames(repo: Path) -> tuple[list[str], list[str], dict[str, Path], dict[str, Path]]:
    item_lst = read_lst(repo / "workspace/raw/master/ART/ITEMS/ITEMS.LST")
    inven_lst = read_lst(repo / "workspace/raw/master/ART/INVEN/INVEN.LST")
    item_root = repo / "workspace/output/images/master/ART/ITEMS"
    inven_root = repo / "workspace/output/images/master/ART/INVEN"
    item_dirs = {path.name.casefold(): path for path in item_root.iterdir() if path.is_dir()}
    inven_dirs = {path.name.casefold(): path for path in inven_root.iterdir() if path.is_dir()}
    return item_lst, inven_lst, item_dirs, inven_dirs


def resolve_art_frame(
    fid: int,
    lst: list[str],
    directories: dict[str, Path],
) -> Path | None:
    if fid < 0:
        return None
    index = fid & 0xFFF
    if index >= len(lst):
        return None
    filename = lst[index].strip()
    directory = directories.get(filename.casefold())
    if directory is None:
        return None
    frames = sorted(directory.glob("*.frames/sequence-00/frame-000.png"))
    return frames[0] if frames else None


def copy_images(
    repo: Path,
    group: ItemGroup,
    category_root: Path,
    overwrite: bool,
    dry_run: bool,
    art_index: tuple[list[str], list[str], dict[str, Path], dict[str, Path]],
) -> str:
    item_lst, inven_lst, item_dirs, inven_dirs = art_index
    inventory_sources: dict[Path, list[int]] = defaultdict(list)
    ground_sources: dict[Path, list[int]] = defaultdict(list)
    for proto in group.prototypes:
        pid = int(proto["list_index"])
        fields = proto["fields"]
        inventory = resolve_art_frame(int(fields.get("inventory_fid", -1)), inven_lst, inven_dirs)
        ground = resolve_art_frame(int(proto.get("fid", -1)), item_lst, item_dirs)
        if inventory:
            inventory_sources[inventory].append(pid)
        if ground:
            ground_sources[ground].append(pid)

    attachments = category_root / "attachments"
    if not dry_run:
        attachments.mkdir(parents=True, exist_ok=True)

    def install(sources: dict[Path, list[int]], label: str) -> list[tuple[str, list[int], int]]:
        installed = []
        multiple = len(sources) > 1
        for source, pids in sorted(sources.items(), key=lambda item: item[1]):
            suffix = f" - PID {'-'.join(str(pid) for pid in pids)}" if multiple else ""
            name = f"{Path(group.filename).stem} - {label}{suffix}.png"
            target = attachments / name
            if not dry_run and (overwrite or not target.exists()):
                shutil.copy2(source, target)
            installed.append((name, pids, png_width(source)))
        return installed

    inventory = install(inventory_sources, "物品栏")
    ground = install(ground_sources, "地面")
    if not inventory and not ground:
        return "素材没有为这些物品原型配置可用的物品栏或地面精灵。"

    rows = ["| 适用原型 ID | 物品栏形象 | 地面形象 |", "| --- | --- | --- |"]
    variants = sorted(set(tuple(pids) for _, pids, _ in inventory + ground))
    if len(variants) <= 1:
        inv_text = "素材未配置" if not inventory else f"![[{inventory[0][0]}\\|{min(max(inventory[0][2] * 2, inventory[0][2]), 360)}]]"
        ground_text = "素材未配置" if not ground else f"![[{ground[0][0]}\\|{min(max(ground[0][2] * 4, ground[0][2]), 320)}]]"
        rows.append(f"| {', '.join(str(pid) for pid in group.pids)} | {inv_text} | {ground_text} |")
        return "\n".join(rows)

    for variant in variants:
        inv = next((item for item in inventory if tuple(item[1]) == variant), None)
        grd = next((item for item in ground if tuple(item[1]) == variant), None)
        inv_text = "素材未配置" if inv is None else f"![[{inv[0]}\\|{min(max(inv[2] * 2, inv[2]), 360)}]]"
        ground_text = "素材未配置" if grd is None else f"![[{grd[0]}\\|{min(max(grd[2] * 4, grd[2]), 320)}]]"
        rows.append(f"| {', '.join(str(pid) for pid in variant)} | {inv_text} | {ground_text} |")
    return "\n".join(rows)


def weapon_skill(data: dict[str, Any], extended_flags: int) -> str:
    mode = extended_flags & 0xF
    if mode in (1, 2):
        return "Unarmed 徒手"
    if mode in (3, 4):
        return "Melee Weapons 近战武器"
    if mode == 5:
        return "Throwing 投掷"
    if extended_flags & 0x100:
        return "Big Guns 重型武器"
    if int(data.get("damage_type", 0)) in (1, 3, 4):
        return "Energy Weapons 能量武器"
    return "Small Guns 轻型武器"


def format_time(minutes: int) -> str:
    if minutes == 0:
        return "0 分钟"
    if minutes % 1440 == 0:
        return f"{minutes} 分钟（{minutes // 1440} 天）"
    if minutes % 60 == 0:
        return f"{minutes} 分钟（{minutes // 60} 小时）"
    return f"{minutes} 分钟"


def effect_text(stats: list[int], amounts: list[int]) -> str:
    effects: list[str] = []
    index = 0
    while index < len(stats):
        stat = int(stats[index])
        if stat == -2 and index + 1 < len(stats) and int(stats[index + 1]) >= 0:
            name = STAT_NAMES.get(int(stats[index + 1]), f"属性 {stats[index + 1]}")
            low, high = int(amounts[index]), int(amounts[index + 1])
            effects.append(f"{name} {low:+d} 至 {high:+d}")
            index += 2
            continue
        if stat >= 0:
            name = STAT_NAMES.get(stat, f"属性 {stat}")
            effects.append(f"{name} {int(amounts[index]):+d}")
        index += 1
    return "；".join(effects) if effects else "无"


def general_rows(proto: dict[str, Any], category_label: str) -> list[tuple[str, str]]:
    fields = proto["fields"]
    return [
        ("物品原型 ID", f"{proto['list_index']}（`{proto['pid_hex']}`）"),
        ("类型", category_label),
        ("材质", MATERIALS.get(int(fields.get("material", -1)), str(fields.get("material", "—")))),
        ("重量", str(fields.get("weight", "—"))),
        ("体积", str(fields.get("size", "—"))),
        ("基础价值", f"{fields.get('cost', '—')} 瓶盖"),
    ]


def game_data(group: ItemGroup, by_pid: dict[int, ItemGroup]) -> str:
    _, category_label = CATEGORY_DIRS[group.category]
    if len(group.prototypes) > 1:
        lines = [
            "同一显示名对应多个地图物品原型；各原型的直接数据如下。",
            "",
            "| 原型 ID | 资源类型 | 材质 | 重量 | 体积 | 基础价值 | 容量 |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for proto in group.prototypes:
            fields = proto["fields"]
            capacity = fields.get("data", {}).get("max_size", "—")
            lines.append(
                f"| {proto['list_index']} | {proto.get('subtype_name') or 'misc'} | "
                f"{MATERIALS.get(int(fields.get('material', -1)), fields.get('material', '—'))} | "
                f"{fields.get('weight', '—')} | {fields.get('size', '—')} | {fields.get('cost', '—')} | {capacity} |"
            )
        return "\n".join(lines)

    proto = group.prototypes[0]
    fields = proto["fields"]
    data = fields.get("data", {})
    rows = general_rows(proto, category_label)
    extra = ""

    if group.category == "weapon":
        extended = int(fields.get("extended_flags", 0))
        primary = extended & 0xF
        secondary = (extended >> 4) & 0xF
        ammo_pid = int(data.get("ammo_type_pid", -1))
        ammo_group = by_pid.get(ammo_pid)
        ammo = "无" if ammo_pid == -1 else f"{ammo_group.title}（ID {ammo_pid}）" if ammo_group else f"PID {ammo_pid}"
        projectile = int(data.get("projectile_pid", -1))
        rows.extend(
            [
                ("使用技能", weapon_skill(data, extended)),
                ("持握方式", "双手" if extended & 0x200 else "单手"),
                ("基础伤害", f"{data.get('min_damage')}–{data.get('max_damage')}"),
                ("伤害类型", DAMAGE_TYPES.get(int(data.get("damage_type", -1)), str(data.get("damage_type")))),
                ("主要攻击", ATTACK_MODES.get(primary, str(primary))),
                ("主要攻击行动点", str(data.get("action_point_cost_1"))),
                ("主要攻击射程", f"{data.get('max_range_1')} 格"),
                ("次要攻击", ATTACK_MODES.get(secondary, str(secondary))),
                ("次要攻击行动点", str(data.get("action_point_cost_2"))),
                ("次要攻击射程", f"{data.get('max_range_2')} 格"),
                ("最低力量", str(data.get("min_strength"))),
                ("武器特性", WEAPON_PERKS.get(int(data.get("perk", -1)), f"Perk ID {data.get('perk')}")),
                ("武器动画", WEAPON_ANIMATIONS.get(int(data.get("animation_code", -1)), str(data.get("animation_code")))),
                ("弹药", ammo),
                ("弹容量", str(data.get("ammo_capacity"))),
                ("每次攻击弹数", str(data.get("rounds"))),
                ("射弹", "无" if projectile == -1 else f"PID `{projectile & 0xFFFFFFFF:#010x}`"),
                ("武器脚本", "无" if int(fields.get("script_id", -1)) == -1 else f"SID {fields.get('script_id')}"),
                ("严重失败表 ID", str(data.get("critical_failure_type"))),
            ]
        )
    elif group.category == "ammo":
        rows.extend(
            [
                ("口径", CALIBERS.get(int(data.get("caliber", -1)), str(data.get("caliber")))),
                ("每盒数量", str(data.get("quantity"))),
                ("装甲等级修正", f"{int(data.get('armor_class_modifier', 0)):+d}"),
                ("伤害抗性修正", f"{int(data.get('damage_resistance_modifier', 0)):+d}%"),
                ("伤害倍率", f"×{data.get('damage_multiplier')} ÷{data.get('damage_divisor')}"),
            ]
        )
    elif group.category == "armor":
        rows.extend(
            [
                ("装甲等级", str(data.get("armor_class"))),
                ("装甲特性", WEAPON_PERKS.get(int(data.get("perk", -1)), f"Perk ID {data.get('perk')}")),
            ]
        )
        resistance = data.get("damage_resistance", [])
        threshold = data.get("damage_threshold", [])
        extra_lines = [
            "",
            "| 伤害类型 | 伤害阈值 | 伤害抗性 |",
            "| --- | ---: | ---: |",
        ]
        for index in range(min(len(resistance), len(threshold))):
            extra_lines.append(f"| {DAMAGE_TYPES.get(index, index)} | {threshold[index]} | {resistance[index]}% |")
        extra = "\n".join(extra_lines)
    elif group.category == "drug":
        chance = int(data.get("addiction_chance", 0))
        withdrawal = int(data.get("withdrawal_effect", -1))
        rows.extend(
            [
                ("成瘾概率", f"{chance}%"),
                ("戒断效果", "无" if chance == 0 or withdrawal == -1 else WITHDRAWAL_EFFECTS.get(withdrawal, f"Perk ID {withdrawal}")),
                ("戒断开始时间", "—" if chance == 0 else format_time(int(data.get("withdrawal_onset", 0)))),
            ]
        )
        extra_lines = [
            "",
            "| 阶段 | 时间 | 属性变化 |",
            "| --- | --- | --- |",
            f"| 立即生效 | 使用时 | {effect_text(data.get('stats', []), data.get('amount', []))} |",
            f"| 第一阶段 | {format_time(int(data.get('duration_1', 0)))}后 | {effect_text(data.get('stats', []), data.get('amount_1', []))} |",
            f"| 第二阶段 | {format_time(int(data.get('duration_2', 0)))}后 | {effect_text(data.get('stats', []), data.get('amount_2', []))} |",
        ]
        extra = "\n".join(extra_lines)
    elif group.category == "container":
        if proto.get("subtype_name") == "container":
            rows.extend(
                [
                    ("容量", str(data.get("max_size"))),
                    ("开启标志", str(data.get("open_flags"))),
                ]
            )
        else:
            rows.append(("资源类型", str(proto.get("subtype_name") or "misc")))
    elif group.category == "caps":
        rows.extend([("单枚价值", "1 瓶盖"), ("充能次数", str(data.get("charges", 0)))])
    elif group.category == "misc":
        power_pid = int(data.get("power_type_pid", -1))
        rows.extend(
            [
                ("能源物品 PID", "无" if power_pid == -1 else str(power_pid)),
                ("能源类型", str(data.get("power_type", 0))),
                ("充能次数", str(data.get("charges", 0))),
            ]
        )

    lines = ["| 项目 | 数据 |", "| --- | --- |"]
    lines.extend(f"| {table_text(name)} | {table_text(value)} |" for name, value in rows)
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def aliases_for(group: ItemGroup, alternate_names: dict[str, str]) -> list[str]:
    values = [group.english, group.chinese]
    alternate = alternate_names.get(group.english)
    if alternate:
        values.append(alternate)
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if clean and clean.casefold() not in seen:
            result.append(clean)
            seen.add(clean.casefold())
    return result


def render_note(
    group: ItemGroup,
    english_items: dict[int, str],
    chinese_items: dict[int, str],
    alternate_names: dict[str, str],
    shape: str,
    data: str,
    rows: list[dict[str, Any]],
) -> str:
    aliases = aliases_for(group, alternate_names)
    frontmatter = ["---", f"title: {yaml_quote(group.title)}", "aliases:"]
    frontmatter.extend(f"  - {yaml_quote(alias)}" for alias in aliases)
    frontmatter.extend(["tags:", f"  - {yaml_quote('辐射1/物品/' + CATEGORY_DIRS[group.category][1])}"])
    if len(group.pids) == 1:
        frontmatter.append(f"prototype_id: {group.pids[0]}")
    else:
        frontmatter.append("prototype_ids:")
        frontmatter.extend(f"  - {pid}" for pid in group.pids)
    frontmatter.append("---")

    first = group.prototypes[0]
    message_id = int(first["message_id"])
    english_description = english_items.get(message_id + 1, "")
    chinese_description = chinese_items.get(message_id + 1, "")
    additions = [NOTE_ADDITIONS[pid] for pid in group.pids if pid in NOTE_ADDITIONS]
    description_addition = "\n\n" + "\n\n".join(additions) if additions else ""
    locations = [
        "# 出现位置",
        "",
    ]
    location_additions = [LOCATION_ADDITIONS[pid] for pid in group.pids if pid in LOCATION_ADDITIONS]
    if location_additions:
        locations.extend(["\n\n".join(location_additions), ""])
    locations.extend(
        [
            f"静态地图资料中共有 {len(rows)} 个{group.chinese or group.english}对象，初始数量合计 {sum(int(row['quantity']) for row in rows)}。人物所携物品能否取得，取决于该人物是否开放交易、能否被偷窃，或被击败后能否搜取；容器和地面对象是否能够取得，则取决于玩家能否抵达并操作对应对象。",
            "",
            "| 地点 | 区域 | 持有者或容器 | 物品对象 ID | 数量 | 说明 |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        cells = [
            row["location"],
            table_text(row["area"]),
            row["holder"],
            str(row["object_id"]),
            str(row["quantity"]),
            row["note"],
        ]
        if row["unavailable"]:
            cells = [f"~~{cell}~~" for cell in cells]
        locations.append("| " + " | ".join(cells) + " |")

    sections = [
        "\n".join(frontmatter),
        "# 名称和描述\n\n"
        "| 语言 | 名称 | 描述 |\n"
        "| --- | --- | --- |\n"
        f"| 英文 | {table_text(group.english)} | {table_text(english_description)} |\n"
        f"| 中文 | {table_text(group.chinese)} | {table_text(chinese_description)} |"
        f"{description_addition}",
        f"# 形象\n\n{shape}",
        f"# 游戏数据\n\n{data}",
        "\n".join(locations),
    ]
    return "\n\n".join(sections).rstrip() + "\n"


def load_alternate_names(repo: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for filename in ("huboldtn-item-names.zh-CN.json", "hub-item-names.zh-CN.json"):
        path = repo / "config" / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        result.update({str(key): str(value) for key, value in payload.get("prototype_names", {}).items()})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-pid", type=int, action="append", default=[])
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    vault = args.vault.resolve()
    workspace = repo / "workspace"
    game_master = workspace / "output/text/master/TEXT/ENGLISH/GAME"
    game_data_dir = workspace / "output/text/data/TEXT/ENGLISH/GAME"
    english_items = effective_messages(game_master / "PRO_ITEM.json")
    chinese_items = effective_messages(game_data_dir / "PRO_ITEM.json")
    english_critters = effective_messages(game_master / "PRO_CRIT.json")
    chinese_critters = effective_messages(game_data_dir / "PRO_CRIT.json")
    english_map = effective_messages(game_master / "MAP.json")
    chinese_map = effective_messages(game_data_dir / "MAP.json")
    old_town = json.loads(
        (workspace / "output/maps/master/MAPS/HUBOLDTN/HUBOLDTN.json").read_text(encoding="utf-8")
    )
    groups, by_pid = make_groups(old_town, english_items, chinese_items)
    critter_names = critter_name_config(repo)
    maps = map_metadata(repo, english_map, chinese_map)
    people = parse_old_town_people(vault)
    occurrences = scan_occurrences(
        repo,
        by_pid,
        maps,
        people,
        critter_names,
        english_critters,
        chinese_critters,
        english_items,
        chinese_items,
    )
    alternates = load_alternate_names(repo)
    art_index = art_frames(repo)

    written = 0
    skipped = 0
    for group in groups:
        if any(pid in args.skip_pid for pid in group.pids):
            skipped += 1
            print(f"skip\t{group.pids}\t{group.title}")
            continue
        category_dir, _ = CATEGORY_DIRS[group.category]
        category_root = vault / "物品" / category_dir
        target = category_root / group.filename
        if target.exists() and not args.overwrite:
            skipped += 1
            print(f"exists\t{group.pids}\t{target}")
            continue
        shape = copy_images(repo, group, category_root, args.overwrite, args.dry_run, art_index)
        data = game_data(group, by_pid)
        note = render_note(
            group,
            english_items,
            chinese_items,
            alternates,
            shape,
            data,
            occurrences.get(group.key, []),
        )
        print(f"write\t{group.pids}\t{target}")
        if not args.dry_run:
            category_root.mkdir(parents=True, exist_ok=True)
            target.write_text(note, encoding="utf-8")
        written += 1

    print(f"summary\tgroups={len(groups)}\twritten={written}\tskipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
