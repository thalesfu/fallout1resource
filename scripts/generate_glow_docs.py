#!/usr/bin/env python3
"""Generate the complete Fallout 1 The Glow location package for Obsidian."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fallout1_character_topics import sync_tree


REPO = Path(__file__).resolve().parents[1]
LOCATION = "The Glow 闪光之地"
POWER_TASK = "Turn on power for the Glow 打开闪光之地电源（发起人 ID 2263）"
BROTHERHOOD_TASK = "Become an Initiate 加入兄弟会（发起人 ID 856）"


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nec = import_script("glow_necropolis_helpers", "generate_necropolis_docs.py")
bone = nec.bone
bb = nec.bb
Region = nec.Region


REGIONS = (
    Region("Crater Surface 大弹坑地表", "Crater Surface", "大弹坑地表", "GLOWENT", 0, 27,
           "闪光之地的露天地表。完整地图以弹坑为中心，保存三具乞丐尸体和通往地下设施的入口对象；这里没有墙体对象，建筑本体位于弹坑下方。"),
    Region("Level 1 第一层", "Level 1", "第一层", "GLOW1", 0, 42,
           "弹坑下方的第一层办公与居住区。中心同样被爆炸贯穿，房间中保存八具尸体、五只锁柜和第一台电力管理终端。"),
    Region("Level 2 第二层", "Level 2", "第二层", "GLOW1", 1, 42,
           "设施第二层。地图保存六台防卫机器人、四具人员尸体、一具发光变种地鼠尸体、三只锁柜和电力终端；机器人与尸体状态均取自 MAP 保存快照。"),
    Region("Level 3 第三层", "Level 3", "第三层", "GLOW1", 2, 42,
           "设施第三层的实验、档案与储藏空间。四台防卫机器人集中在东南侧，西侧四只锁柜保存弹药、药物和医疗用品。"),
    Region("Level 4 第四层", "Level 4", "第四层", "GLOW2", 0, 43,
           "ZAX 将本层说明为研究设施，包含生物学与物理学实验区。地图保存三台防卫机器人、一具警卫尸体、八个容器以及智能计算机 ZAX。",
           (("研究档案与设施控制", "[[ZAX 扎克斯（对象 ID 2282）|ZAX 扎克斯]]", "可查询基地历史、楼层用途、FEV 研究、门禁与其他设施资料。"),)),
    Region("Level 5 第五层", "Level 5", "第五层", "GLOW2", 1, 43,
           "ZAX 将本层说明为安全测试实验室和机密研究区，并明确把其中研究与 FEV 的发展联系起来。地图保存七台机器人与十二只物资锁柜。"),
    Region("Level 6 第六层", "Level 6", "第六层", "GLOW2", 2, 43,
           "ZAX 将本层说明为军营与中央控制区。地图保存两台机器人、六具人员尸体、两台可修理发电机和一台电力管理终端；这里是恢复主电源的关键楼层。",
           (("恢复主电源", "发电机（对象 ID 2263、2473）", "修理成功后把设施发电机状态设为在线，并给予 1000 点经验值。"),)),
)


CORPSE_NAMES = {
    "Loser": ("Beggar Corpse", "乞丐尸体"),
    "Peasant": ("Peasant Corpse", "农民尸体"),
    "Person In Power Armor": ("Power-Armored Corpse", "动力装甲尸体"),
    "Woman": ("Woman's Corpse", "女性尸体"),
    "Leather Jacket Woman": ("Charred Corpse", "焦尸"),
    "Merchant": ("Skeleton Corpse", "骸骨"),
    "Guard": ("Guard Corpse", "警卫尸体"),
    "Technician": ("Technician Corpse", "技工尸体"),
    "Man": ("Man's Corpse", "男性尸体"),
    "Male Guard": ("Male Guard Corpse", "男警卫尸体"),
    "Townswoman": ("Local Woman's Corpse", "本地女居民尸体"),
    "Worker": ("Worker Corpse", "工人尸体"),
    "Vault Dweller": ("Vault Dweller Corpse", "避难所居民尸体"),
    "Townsman": ("Local Man's Corpse", "本地居民尸体"),
}
ROBOT_NAMES = {
    "Robobrain": ("Robobrain", "圆顶机器人"),
    "Floating Eye": ("Floating Eye", "浮空眼机器人"),
    "Eyeball, Mk II": ("Eyebot Mk II", "眼球机器人 Mk II"),
}
PROFILE_IDENTITIES: dict[int, tuple[str, str]] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def script_stem(obj: dict) -> str:
    return Path(obj.get("script_filename") or "").stem.upper()


def identity(obj: dict, proto_en: str, proto_zh: str) -> tuple[str, str, str, bool]:
    if not proto_en:
        proto_en, proto_zh = PROFILE_IDENTITIES[int(obj["object_id"])]
    if proto_en in ROBOT_NAMES:
        en, zh = ROBOT_NAMES[proto_en]
        return en, zh, "设施保存的通用防卫机器人；GSENROB.INT 负责感知、警戒与战斗，没有提供个人姓名。", False
    en, zh = CORPSE_NAMES.get(proto_en, (proto_en, proto_zh))
    return en, zh, "MAP 对象的战斗结果标志包含死亡状态；本页按保存状态记作尸体，不把人物原型类别误写成仍然存活的个人。", False


def short_title(title: str) -> str:
    return title.removeprefix(f"{LOCATION} - ").split("（ID", 1)[0].strip()


def key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def task_association(region: Region, oid: int) -> str:
    return ""


def configure_helpers() -> None:
    nec.LOCATION = LOCATION
    nec.REGIONS = REGIONS
    nec.NAMED = {}
    nec.PROFILE_IDENTITIES = PROFILE_IDENTITIES
    nec.identity = identity
    nec.short_title = short_title
    nec.key = key
    nec.task_association = task_association
    bone.NAMED = {}
    bone.SCRIPT_ROLES = {}
    bone.identity = identity
    bone.short_title = short_title
    bone.task_association = task_association
    bb.HEADS = {}


def poster(output: Path) -> None:
    source_path = REPO / "workspace/output/images/master/ART/INTRFACE/TWNMAP09.frm/TWNMAP09.frm.frames/sequence-00/frame-000.png"
    source = Image.open(source_path).convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (18, 18, 16, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    font_path = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    title_font = ImageFont.truetype(font_path, 34)
    label_font = ImageFont.truetype(font_path, 22)
    meta_font = ImageFont.truetype(font_path, 16)
    draw.text((700, 38), LOCATION, font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP09.FRM · 原作城镇海报与两个引擎热点", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale, left, top = 1.72, 310, 92
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    draw.rounded_rectangle((left - 10, top - 10, left + scaled.width + 10, top + scaled.height + 10), radius=18, fill=(7, 7, 6), outline=(89, 70, 46), width=5)
    canvas.alpha_composite(scaled, (left, top))
    anchors = [
        ("Crater Surface 大弹坑地表", "GLOWENT · e0 · (340,149)", 340, 149, 40, 205),
        ("Level 1 第一层", "GLOW1 · e0 · (334,195)", 334, 195, 1060, 505),
    ]
    for label, meta, sx, sy, bx, by in anchors:
        px, py = left + sx * scale, top + sy * scale
        bw, bh = 300, 96
        edge_x = bx + bw if bx < 700 else bx
        draw.line((px, py, (px + edge_x) / 2, by + bh / 2, edge_x, by + bh / 2), fill=(224, 180, 91), width=3)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
        draw.text((bx + 16, by + 17), label, font=label_font, fill=(248, 232, 188))
        draw.text((bx + 16, by + 58), meta, font=meta_font, fill=(205, 185, 139))
    draw.text((700, 866), "第二至第六层由设施内部通道连接，不是城镇海报独立热点", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def creature_rows(creatures: list[dict], lookup: dict, critter_messages: dict) -> list[str]:
    rows = []
    for obj in sorted(creatures, key=lambda value: int(value["object_id"])):
        proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
        en, zh = critter_messages.get(int(proto["message_id"]), ("Unknown Creature", "未知生物"))
        rows.append(f"| {obj['object_id']} | {en} {zh}（尸体状态） | 无独立脚本 | {obj['tile']} |")
    return rows


def task_rows(region: Region) -> list[str]:
    rows = []
    if region.title == "Crater Surface 大弹坑地表":
        rows.append(f"| [[{BROTHERHOOD_TASK}|加入兄弟会]] | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）|卡波特]] | [[Brotherhood 钢铁兄弟会|钢铁兄弟会]] | 闪光之地是取得远征证明的目标地点；任务页按最初发起人保留在兄弟会包。 |")
    if region.title in {"Level 1 第一层", "Level 2 第二层", "Level 3 第三层", "Level 4 第四层", "Level 5 第五层", "Level 6 第六层"}:
        rows.append(f"| [[{BROTHERHOOD_TASK}|加入兄弟会]] | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）|卡波特]] | [[Brotherhood 钢铁兄弟会|钢铁兄弟会]] | 本层属于寻找远征证明和技术资料的探索路线。 |")
    if region.title == "Level 6 第六层":
        rows.append(f"| [[{POWER_TASK}|打开闪光之地电源]] | 发电机（对象 ID 2263） | [[Level 6 第六层|第六层]] | 修理任一发电机使主系统上线；电力终端随后可以切换主电源或应急电源。 |")
    else:
        rows.append(f"| [[{POWER_TASK}|打开闪光之地电源]] | 发电机（对象 ID 2263） | [[Level 6 第六层|第六层]] | 本层电力终端、门禁与设施状态受发电机及主电源全局状态影响。 |")
    rows.append("| Disarm Traps for the Facility / 排除设备上的陷阱 | 无明确发起人 | — | `PIPBOY.MSG` 791 保存标题；GLOWGN.INT 为门与容器提供陷阱解除机制，但没有独立接取者或统一完成变量。 |")
    return rows


def character_note(vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path):
    text, title, named = bone.character_note(vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages,
                                             critter_messages, note_index, map_filename, sprite_filename, art_name, attachments)
    text = text.replace("Boneyard 晒骨场", LOCATION)
    text = text.replace("tags: [辐射1, 人物, 地点, 晒骨场]", "tags: [辐射1, 人物, 地点, 闪光之地]")
    text = text.replace(f"[[{LOCATION}\\|晒骨场]]", f"[[{LOCATION}\\|闪光之地]]")
    text = text.replace("地点/Boneyard 晒骨场/", f"地点/{LOCATION}/")
    text = text.replace("\n\n## 对话头像\n\n人物脚本和人物原型没有提供可确认的独立 HEADS 对话头像。", "")
    if proto_en in CORPSE_NAMES:
        text = text.replace("| 地图当前生命值 |", "| 原型基础生命值（尸体对象） |")
    return text, title, named


def write_tasks(vault_dir: Path) -> None:
    task_dir = vault_dir / "Level 6 第六层/任务"
    task_dir.mkdir(parents=True, exist_ok=True)
    page = rf'''---
title: "Turn on power for the Glow 打开闪光之地电源"
aliases: ["Turn on power for the Glow", "打开闪光之地电源"]
tags: [辐射1, 任务, 闪光之地, 第六层]
quest_giver: Generator 发电机
quest_giver_map_object_id: 2263
---

# Turn on power for the Glow 打开闪光之地电源

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | Turn on power for the Glow. |
| 当前中文 | 打开避难所的电源。 |
| Pip-Boy 消息 | `PIPBOY.MSG` 792 |

## 任务概览

这是一条由设施对象和全局电力状态驱动的任务，没有对话人物发起。文件名中的对象 ID `2263` 指第六层两台同类发电机中 MAP 源顺序靠前的一台，用来满足任务页的稳定身份规则；对象 ID `2473` 可以执行同一修复流程。

## 接取条件

Pip-Boy 保留任务标题，但现有脚本没有人物接取对话。进入闪光之地后，楼层电力终端会显示发电机、主电源与应急电源状态；因此不把“看到任务标题”扩写成某人委托。

## 目标与完成

1. 抵达[[Level 6 第六层|第六层]]的发电机区。
2. 对发电机对象 ID `2263` 或 `2473` 使用修理流程。`GLOWGEN.INT` 的技能检查使用 Repair，并在一条明确分支中比较修理技能是否高于 35。
3. 成功后脚本把全局变量 `139` 设为 `2`，显示“所有的系统都进入在线状态”，并给予 1000 点经验值。
4. 各层 `GPWRTERM.INT` 电力终端读取发电机状态；主发电机在线后可以把设施电源状态设为主电源，另有应急电源和关闭分支。

## 人物与区域

| 对象 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| 发电机 | 2263 | [[Level 6 第六层|第六层]] | 同类发电机中源顺序靠前者；修理成功可令系统上线。 |
| 发电机 | 2473 | [[Level 6 第六层|第六层]] | 执行相同的修理和上线逻辑。 |
| 电力管理终端 | 651 | [[Level 1 第一层|第一层]] | 最早楼层中的诊断与电源控制入口。 |
| 电力管理终端 | 3347、3447、621、2562 | 第二至第六层 | 读取或改变主电源、应急电源状态。 |

## 来源边界

任务标题来自 `PIPBOY.MSG` 792；发电机技能检查、全局变量 `139`、1000 经验值和成功文字来自 `GLOWGEN.INT`；电力切换与全局变量 `224` 来自 `GPWRTERM.INT`。静态 MAP 只证明对象位置，不能单独证明玩家已完成任务。
'''
    (task_dir / f"{POWER_TASK}.md").write_text(page, encoding="utf-8")


def write_zax(vault_dir: Path) -> None:
    facility_dir = vault_dir / "Level 4 第四层/设施"
    facility_dir.mkdir(parents=True, exist_ok=True)
    page = rf'''---
title: "ZAX 扎克斯（对象 ID 2282）"
aliases: ["ZAX", "扎克斯", "闪光之地智能计算机"]
tags: [辐射1, 地点, 设施, 闪光之地, 第四层]
map: GLOW2
elevation: 0
map_object_id: 2282
resource_script: ZAX.INT
---

# ZAX 扎克斯（对象 ID 2282）

## 身份

游戏观察文字称它为“控制闪光之地的智能机器”；它自称 ZAX，是一台用于研究和设备操控的智能机器。结构化地图把它保存为 `scenery` 对象而非 `critter` 人物对象，因此本页归入设施，不伪造人物原型、SPECIAL 或生命值字段。

## 地图位置

| 属性 | 值 |
|---|---|
| 地点 | [[{LOCATION}|闪光之地]] |
| 区域 | [[Level 4 第四层|第四层]] |
| 资源地图 | `GLOW2.MAP` / elevation 0 |
| 地图对象 ID | 2282 |
| 地图格 | 19098 |
| 对象类型 | scenery |
| 脚本 | `ZAX.INT` |

## 可查询内容

- 设施历史、战前研究用途与自身设计背景；ZAX 称其中枢网络由贾斯汀·李在 2053 年设计。
- 第四层是生物学与物理学研究设施；第五层是安全测试和机密研究实验室；第六层是军营与中央控制区。
- 第五层研究与 FEV 发展之间的关系。
- 门禁、钥匙卡、武器库电子锁以及设施安全状态。
- 国际象棋等非任务性互动。

## 任务与设施关系

ZAX 能解释设施和门禁，但 `ZAX.INT` 不是[[{POWER_TASK}|打开闪光之地电源]]的发起脚本。恢复电力由第六层 `GLOWGEN.INT` 发电机对象完成；ZAX 和电力终端只是设施状态与信息网络的一部分。

## 来源边界

身份、楼层用途和可查询内容来自 `ZAX.INT` 及当前有效的 `ZAX.MSG` 中文消息；对象类型、ID、楼层和格位来自 `GLOW2.MAP`。由于对象类型是场景设施，本页没有套用人物文档模板。
'''
    (facility_dir / "ZAX 扎克斯（对象 ID 2282）.md").write_text(page, encoding="utf-8")


def write_home(vault_dir: Path, region_people: dict, region_creatures: dict, region_objects: dict,
               titles: dict, critter_messages: dict, item_messages: dict, note_index: dict) -> None:
    region_rows, generic_rows, creature_list, item_rows, container_rows = [], [], [], [], []
    for region in REGIONS:
        people, creatures = region_people[region.title], region_creatures[region.title]
        direct = region.title in {"Crater Surface 大弹坑地表", "Level 1 第一层"}
        relation = "城镇海报直接热点。" if direct else "由设施内部楼梯或电梯连接。"
        region_rows.append(f"| [[{region.title}|{region.title}]] | `{region.map_name}.MAP` / e{region.elevation} | {relation} |")
        for obj in sorted(people, key=lambda value: int(value["object_id"])):
            title = titles[key(region, obj)]
            generic_rows.append(f"| [[{region.title}|{region.chinese}]] | {obj['object_id']} | [[{title}|{short_title(title)}]] |")
        for obj in creatures:
            proto = region_objects[region.title][1][("critter", int(obj["prototype"]["list_index"]))]
            en, zh = critter_messages.get(int(proto["message_id"]), ("Unknown Creature", "未知生物"))
            creature_list.append(f"| [[{region.title}|{region.chinese}]] | {obj['object_id']} | {en} {zh}（尸体状态） |")
        objects, lookup = region_objects[region.title]
        _, home_items, containers = nec.item_entries(region, people, objects, lookup, item_messages, note_index, titles)
        item_rows.extend(f"| {kind} | {name} | [[{region.title}]] | {owner} | {qty} |" for kind, name, owner, qty, _ in home_items)
        container_rows.extend(f"| [[{region.title}]] | {name} | {contents} |" for name, contents in containers)
    page = rf'''---
title: "{LOCATION}"
aliases: ["The Glow", "Glow", "闪光之地"]
tags: [辐射1, 地点, 闪光之地]
world_map_grid: "24,25"
world_map_pixel: "1225,1275"
---

# {LOCATION}

## 名称

| 使用位置 | 名称 |
|---|---|
| 知识库标题 | {LOCATION} |
| 世界地图 / Pip-Boy | Glow / 闪光之地 |
| 城镇海报 | `TWNMAP09.FRM` |
| 地图资源 | `GLOWENT.MAP`、`GLOW1.MAP`、`GLOW2.MAP` |

## 地点概览

闪光之地位于世界地图网格 `(24, 25)`、像素坐标 `(1225, 1275)`。地表是一个被爆炸贯穿的大弹坑，地下设施分六层；完整对象清点保存大量人员尸体、仍可运作的防卫机器人、研究档案、物资锁柜、ZAX 智能计算机和第六层发电机。

[[Junktown 迦克镇 - Saul 索尔|索尔]]说闪光之地在迦克镇南方，并称弟弟 Darrell 为寻宝前往后没有回来。这是索尔的个人说法；地图坐标与对象清点不能确认 Darrell 的具体去向。

## 世界地图位置

世界地图地点索引为 `9`，网格 `(24,25)`，锚点像素 `(1225,1275)`；总览另见[[World Map 世界地图|世界地图]]。

## 地图

![[{LOCATION}城镇地图（区域标注）.jpg|900]]

海报原图为 `TWNMAP09.FRM`。可执行文件中的两个热点分别是大弹坑地表 `(340,149)`，进入 `GLOWENT.MAP` elevation 0；第一层 `(334,195)`，进入 `GLOW1.MAP` elevation 0。第二至第六层由设施内部连接。

## 区域与楼层

| 区域与楼层 | 资源身份 | 进入方式或关系 |
|---|---|---|
{chr(10).join(region_rows)}

## 商店和服务

| 区域 | 商店或服务 | 提供者 | 内容 |
|---|---|---|---|
| [[Level 4 第四层]] | 研究档案与设施控制 | [[ZAX 扎克斯（对象 ID 2282）|ZAX 扎克斯]] | 查询设施历史、FEV、楼层用途、门禁与其他资料。 |
| [[Level 6 第六层]] | 恢复主电源 | 发电机（对象 ID 2263、2473） | 修理成功后使设施系统上线并获得 1000 点经验值。 |

## 地图中的人物

完整对象清点得到 {sum(len(value) for value in region_people.values())} 名人物或机器人对象，全部是普通人物分类；没有可由人物原型确认的专名人物。尸体页按 MAP 死亡状态命名，机器人页按原型类别命名。另有 {sum(len(value) for value in region_creatures.values())} 具发光变种地鼠尸体，单列为生物。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
| — | — | 当前七层 MAP 没有专名 critter 对象。ZAX 是有名字的智能设施对象，见[[ZAX 扎克斯（对象 ID 2282）]]。 |

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows)}

### 生物对象

| 区域 | 地图对象 ID | 生物 |
|---|---:|---|
{chr(10).join(creature_list)}

## 地图中的物品

下表汇总人物随身库存、地面物品和容器直接库存；一个单元格只表示一种物品。空容器不伪造内容。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(sorted(item_rows))}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 第一个发起人或驱动对象 | 接取区域 | 闪光之地中的环节 |
|---|---|---|---|
| [[{BROTHERHOOD_TASK}|加入兄弟会]] | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）|卡波特]] | [[Brotherhood 钢铁兄弟会|钢铁兄弟会]] | 闪光之地是取得远征证明的目标地点；规范任务页不在本包重复建立。 |
| [[{POWER_TASK}|打开闪光之地电源]] | 发电机（对象 ID 2263） | [[Level 6 第六层|第六层]] | 修理两台同类发电机之一，使设施系统上线。 |
| Disarm Traps for the Facility / 排除设备上的陷阱 | 无明确发起人 | — | `PIPBOY.MSG` 791 保存标题，`GLOWGN.INT` 提供门与容器的陷阱机制；没有确认统一接取或完成状态，故不建立伪任务页。 |

## 来源边界

- 地点坐标、地图编号和楼层来自世界地图、`MAP.MSG` 与三张结构化 MAP；海报热点来自 Fallout 可执行文件的城镇地图表。
- 人物、机器人、生物、物品与容器来自七个 MAP elevation 的完整对象清点；死亡状态来自对象战斗结果标志。
- 区域图和人物高亮图全部保留渲染器完整原始画布与像素尺寸，没有裁掉房间，也没有等比例缩小附件。
- ZAX 的身份、设施用途与 FEV 说明来自 `ZAX.INT` 及当前有效消息；索尔关于位置与 Darrell 的内容保留为人物说法。
'''
    (vault_dir / f"{LOCATION}.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    configure_helpers()
    nec.creature_rows = creature_rows
    nec.task_rows = task_rows
    vault = args.vault_root.resolve()
    vault_dir = vault / f"地点/{LOCATION}"
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    home_attachments = vault_dir / "attachments"
    home_attachments.mkdir(exist_ok=True)
    poster(home_attachments / f"{LOCATION}城镇地图（区域标注）.jpg")
    region_people, region_creatures, region_objects, titles = {}, {}, {}, {}
    evidence = {
        "location": "The Glow", "source_maps": ["GLOWENT.MAP", "GLOW1.MAP", "GLOW2.MAP"],
        "town_poster": "TWNMAP09.FRM", "world_map": {"grid": [24, 25], "pixel": [1225, 1275]},
        "town_hotspots": [{"map": "GLOWENT", "elevation": 0, "x": 340, "y": 149}, {"map": "GLOW1", "elevation": 0, "x": 334, "y": 195}],
        "maps": [], "character_notes": 0, "creature_objects": 0,
        "facility_pages": ["ZAX 扎克斯（对象 ID 2282）"], "task_pages": [POWER_TASK],
        "pipboy_title_without_canonical_page": "Disarm Traps for the Facility / PIPBOY.MSG 791",
    }
    for region in REGIONS:
        region_dir = vault_dir / region.directory
        attachments = region_dir / "attachments"
        people_root = region_dir / "人物"
        named_dir = people_root / "Named Characters 专名人物"
        generic_dir = people_root / "Generic Characters 普通人物"
        people_attachments = people_root / "attachments"
        for path in (attachments, named_dir, generic_dir, people_attachments):
            path.mkdir(parents=True, exist_ok=True)
        map_doc = load_json(REPO / f"workspace/output/maps/master/MAPS/{region.map_name}/{region.map_name}.json")
        lookup = bb.proto_lookup(map_doc)
        objects = [obj for obj in map_doc["objects"]["entries"] if int(obj.get("elevation_group", -1)) == region.elevation]
        critters = [obj for obj in objects if obj.get("prototype", {}).get("type") == "critter" and int(obj.get("tile", -1)) >= 0]
        creatures = [obj for obj in critters if int(obj["object_id"]) == 807]
        people = [obj for obj in critters if int(obj["object_id"]) != 807]
        for obj in people:
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            PROFILE_IDENTITIES[int(obj["object_id"])] = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
        region_people[region.title], region_creatures[region.title] = people, creatures
        region_objects[region.title] = (objects, lookup)
        render_root = REPO / "workspace/output/maps-rendered" / region.map_name
        source_map = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png"
        map_name = f"{region.title}地图（人物与物品标注，完整原始画布）.png"
        shutil.copyfile(source_map, attachments / map_name)
        maps = bone.profile_maps(region, people, people_attachments) if people else {}
        render_doc = load_json(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json")
        render_by_id = {int(obj["object_id"]): obj for obj in render_doc.get("critters", []) + render_doc.get("missing_critter_art", [])}
        for obj in people:
            oid = int(obj["object_id"])
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            proto_en, proto_zh = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
            en, zh, _, _ = identity(obj, proto_en, proto_zh)
            render_entry = render_by_id[oid]
            frm_stem = Path(render_entry["filename"]).stem.upper()
            source = bb.find_critter_frame(REPO, render_entry["filename"], int(obj["rotation"]))
            sprite_name = None
            if source:
                sprite_name = f"{en} {zh}（ID {oid}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
                shutil.copyfile(source, people_attachments / sprite_name)
            text, title, is_named = character_note(vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages,
                                                   critter_messages, note_index, maps[oid], sprite_name, f"{frm_stem}.FRM", people_attachments)
            full_title = f"{LOCATION} - {title}"
            target = (named_dir if is_named else generic_dir) / f"{full_title}.md"
            if target.exists() and not args.overwrite:
                raise FileExistsError(target)
            target.write_text(text, encoding="utf-8")
            titles[key(region, obj)] = full_title
        top_items = [obj for obj in objects if obj.get("prototype", {}).get("type") == "item" and int(obj.get("tile", -1)) >= 0]
        evidence["maps"].append({
            "map": region.map_name, "elevation": region.elevation, "region": region.title,
            "people": len(people), "creatures": len(creatures), "objects": len(objects),
            "top_level_items": len(top_items), "containers": sum(obj.get("prototype", {}).get("subtype_name") == "container" for obj in top_items),
            "render": str(source_map.relative_to(REPO)),
        })
        evidence["character_notes"] += len(people)
        evidence["creature_objects"] += len(creatures)
    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        nec.write_region_page(vault_dir, region, region_people[region.title], region_creatures[region.title], objects,
                              lookup, critter_messages, item_messages, note_index, titles)
        page_path = vault_dir / region.directory / f"{region.title}.md"
        page_path.write_text(page_path.read_text(encoding="utf-8").replace("tags: [辐射1, 地点, 大墓地]", "tags: [辐射1, 地点, 闪光之地]"), encoding="utf-8")
    write_tasks(vault_dir)
    write_zax(vault_dir)
    write_home(vault_dir, region_people, region_creatures, region_objects, titles, critter_messages, item_messages, note_index)
    for markdown in vault_dir.rglob("*.md"):
        source = markdown.read_text(encoding="utf-8")
        lines = []
        for line in source.splitlines():
            if line.startswith("|"):
                line = re.sub(r"\[\[([^]\n]*?)(?<!\\)\|", r"[[\1\\|", line)
            lines.append(line)
        markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sync_tree(vault_dir, REPO)
    evidence_path = REPO / "workspace/output/maps-knowledge/glow-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated The Glow package: {len(REGIONS)} regions, {evidence['character_notes']} character notes, {evidence['creature_objects']} creature objects, 1 task page, 1 facility page")


if __name__ == "__main__":
    main()
