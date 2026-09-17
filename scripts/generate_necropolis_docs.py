#!/usr/bin/env python3
"""Generate the complete Fallout 1 Necropolis location package for Obsidian."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fallout1_character_topics import sync_tree


REPO = Path(__file__).resolve().parents[1]
LOCATION = "Necropolis 大墓地"


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bone = import_script("necropolis_boneyard_helpers", "generate_boneyard_docs.py")
bb = bone.bb


@dataclass(frozen=True)
class Region:
    directory: str
    english: str
    chinese: str
    map_name: str
    elevation: int
    map_number: int
    description: str
    services: tuple[tuple[str, str, str], ...] = ()

    @property
    def title(self) -> str:
        return f"{self.english} {self.chinese}"


REGIONS = (
    Region("Sewers under Hotel 旅馆区下水道", "Sewers under Hotel", "旅馆区下水道", "HOTEL", 0, 4,
           "旅馆区下方的下水道层。地图保存了多段狭长通道、梯子、僵尸尸体和变种老鼠；它通过梯子连接地表旅馆区，并继续接入大墓地地下通道。"),
    Region("Hotel 旅馆区", "Hotel", "旅馆区", "HOTEL", 1, 4,
           "大墓地城镇海报的东侧入口，资源名称为 Hotel。地表街区围绕废弃旅馆展开，静态对象包括大量僵尸、一名商队商人以及房间内的容器和药品。"),
    Region("Sewers under Hall 监狱区下水道", "Sewers under Hall", "监狱区下水道", "HALLDED", 0, 3,
           "监狱区下方的地下通道，也是爱好和平的地下僵尸群体所在地。地下僵尸领袖在这里说明水泵损坏、净水芯片与供水的关系，并发起修理水泵的任务。",
           (("休息", "地下僵尸领袖", "领袖明确表示玩家需要时可以在这里休息，地下居民不会主动伤害玩家。"),)),
    Region("Hall 监狱区", "Hall", "监狱区", "HALLDED", 1, 3,
           "大墓地城镇海报的中部入口，也是赛特控制的地表据点。赛特、盖瑞特、守卫和发光人分布在大厅、牢房与外围废墟中；赛特在这里发起清除供水区超级变种人的任务。"),
    Region("Sewers under Watershed 供水区下水道", "Sewers under Watershed", "供水区下水道", "WATRSHD", 0, 5,
           "供水区下方的下水道层。地图中只有变种老鼠和一件地面上的名贵垃圾；这件垃圾包含修复水泵所需的零件，是修理任务的关键目标。"),
    Region("Watershed 供水区", "Watershed", "供水区", "WATRSHD", 1, 5,
           "大墓地城镇海报的西侧入口。地表供水建筑被哈里及五名有名字的超级变种人控制，另有僵尸警卫、囚犯和大教堂成员；水泵对象与通往旧避难所的入口都位于这一任务区域。",
           (("修理水泵", "供水设施", "取得下水道中的零件后，可在此使用修理技能恢复大墓地供水。"),)),
    Region("Vault Entrance 大墓地避难所入口", "Vault Entrance", "大墓地避难所入口", "VAULTNEC", 0, 9,
           "旧避难所的入口层，从供水区通往地下设施。地图保存了入口通道、控制房间与两名发光人；本层不是城镇海报的独立热点。"),
    Region("Vault Living Quarters 大墓地避难所生活区", "Vault Living Quarters", "大墓地避难所生活区", "VAULTNEC", 1, 9,
           "旧避难所生活区。走廊和居住舱室中保存六名发光人以及一只含抗辐射药物的锁柜；它位于避难所入口与指挥中心之间。"),
    Region("Vault Command Center 大墓地避难所指挥中心", "Vault Command Center", "大墓地避难所指挥中心", "VAULTNEC", 2, 9,
           "旧避难所最深层的指挥中心。地图保存七名发光人、两只锁柜与控制设施；净水芯片的取得流程在这里完成，但“找到净水芯片”的第一个发起人属于 13 号避难所。"),
)


NAMED = {
    457: ("Sally", "赛莉", "观察文字直接给出 Sally / 赛莉。"),
    458: ("Gary", "加里", "观察文字直接给出 Gary / 加里。"),
    460: ("Barry", "巴里", "观察文字直接给出 Barry / 巴里。"),
    549: ("Harry", "哈里", "观察文字、自称和对话都直接给出 Harry / 哈里。"),
    849: ("Terry", "泰里", "观察文字直接给出 Terry / 泰里。"),
    1313: ("Larry", "拉里", "观察文字直接给出 Larry / 拉里。"),
    1474: ("Garret", "盖瑞特", "观察文字和赛特对话直接给出 Garret / 盖瑞特。"),
    1556: ("Set", "赛特", "观察文字与自我介绍直接给出 Set / 赛特。"),
}


SCRIPT_ROLES = {
    "CARVLEAD": ("Caravan Merchant", "商队商人", "地图脚本表明该对象属于经过旅馆区的商队。"),
    "DEAD": ("Ghoul Corpse", "僵尸尸体", "对象使用 `dead.int`，地图保存状态为倒地的僵尸对象。"),
    "DIRTNAP": ("Prone Glowing One", "伏地发光人", "对象脚本让发光人以伏地或假死状态参与避难所遭遇。"),
    "GANGER": ("Set Gang Guard", "赛特帮警卫", "属于赛特地表据点的武装警卫。"),
    "GHDORGRD": ("Door Guard", "大门警卫", "守在赛特大厅门口的僵尸警卫。"),
    "GHKICK": ("Ejection Guard", "驱逐警卫", "负责在赛特要求后把玩家逐出大厅。"),
    "GHRNDGRD": ("Zombie Guard", "僵尸警卫", "赛特地表据点的普通巡逻警卫。"),
    "GLOWONE": ("Glowing One", "发光人", "监狱区地表保存的发光人对象。"),
    "GROUNDR": ("Underground Ghoul", "地下僵尸", "地下和平僵尸群体成员。"),
    "GUARD2": ("Watershed Guard", "供水区警卫", "供水区内的僵尸警卫。"),
    "LEADER": ("Underground Ghoul Leader", "地下僵尸领袖", "自称被迫转入地下生活的一群人的领袖；素材没有提供个人姓名。"),
    "LOOKOUT": ("Underground Lookout", "地下哨兵", "地下僵尸群体的哨兵。"),
    "PRISONR": ("Ghoul Prisoner", "僵尸囚犯", "观察文字直接称其为僵尸囚犯。"),
    "SETGUARD": ("Set's Elite Guard", "赛特的精英警卫", "赛特身边的精英僵尸警卫。"),
    "TREAD": ("Patrolling Glowing One", "巡行发光人", "旧避难所入口的巡行发光人。"),
    "VALTGLO": ("Vault Glowing One", "避难所发光人", "旧避难所内的发光人。"),
    "CHILDMEM": ("Cathedral Member", "大教堂教徒", "供水区内的大教堂成员；原型显示为农民，不是个人姓名。"),
}


CREATURE_SCRIPTS = {"WANRATS"}
PROFILE_IDENTITIES: dict[int, tuple[str, str]] = {}

KILL_TASK = "Kill the Mutants at the Watershed 消灭供水区的超级变种人（发起人 ID 1556）"
PUMP_TASK = "Fix the Water Pump 修理大墓地的水泵（发起人 ID 3058）"


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
    oid = int(obj["object_id"])
    if oid in NAMED:
        en, zh, note = NAMED[oid]
        return en, zh, note, True
    stem = script_stem(obj)
    if stem in SCRIPT_ROLES:
        en, zh, note = SCRIPT_ROLES[stem]
        return en, zh, note, False
    if not proto_en and not proto_zh:
        proto_en, proto_zh = PROFILE_IDENTITIES[oid]
    return proto_en, proto_zh, f"人物原型分类为 {proto_en} / {proto_zh}；资源没有提供可确认的个人姓名。", False


def short_title(title: str) -> str:
    return title.removeprefix(f"{LOCATION} - ").split("（ID", 1)[0].strip()


def key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def task_association(region: Region, oid: int) -> str:
    if oid == 3058:
        return f"# 任务关联\n\n此对象是[[{PUMP_TASK}|修理大墓地的水泵]]的第一个发起人。"
    if oid == 1556:
        return f"# 任务关联\n\n赛特是[[{KILL_TASK}|消灭供水区的超级变种人]]的第一个发起人。"
    if oid == 1474:
        return f"# 任务关联\n\n盖瑞特负责[[{KILL_TASK}|消灭供水区的超级变种人]]完成后的带路与报酬发放。"
    if oid in {457, 458, 460, 549, 849, 1313}:
        return f"# 任务关联\n\n此人物属于[[{KILL_TASK}|消灭供水区的超级变种人]]在供水区的目标群体。"
    return ""


def configure_helpers() -> None:
    bone.NAMED = NAMED
    bone.SCRIPT_ROLES = SCRIPT_ROLES
    bone.identity = identity
    bone.short_title = short_title
    bone.task_association = task_association
    bb.HEADS = {"SET": "SETTT", "HARRY": "HARRY"}


def poster(output: Path) -> None:
    src = REPO / "workspace/output/images/master/ART/INTRFACE/TWNMAP05.frm/TWNMAP05.frm.frames/sequence-00/frame-000.png"
    source = Image.open(src).convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (18, 18, 16, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 22)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((700, 38), LOCATION, font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP05.FRM · 原作城镇海报与三个地表入口", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale, left, top = 1.72, 310, 92
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    draw.rounded_rectangle((left - 10, top - 10, left + scaled.width + 10, top + scaled.height + 10), radius=18, fill=(7, 7, 6), outline=(89, 70, 46), width=5)
    canvas.alpha_composite(scaled, (left, top))
    anchors = [
        ("Watershed 供水区", "WATRSHD · e1", 79, 207, 35, 280),
        ("Hall 监狱区", "HALLDED · e1", 239, 224, 45, 515),
        ("Hotel 旅馆区", "HOTEL · e1", 398, 265, 1080, 500),
    ]
    for label, meta, sx, sy, bx, by in anchors:
        px, py = left + sx * scale, top + sy * scale
        bw, bh = 275, 88
        edge_x = bx + bw if bx < 700 else bx
        draw.line((px, py, (px + edge_x) / 2, by + bh / 2, edge_x, by + bh / 2), fill=(224, 180, 91), width=3)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
        draw.text((bx + 16, by + 17), label, font=label_font, fill=(248, 232, 188))
        draw.text((bx + 16, by + 55), meta, font=meta_font, fill=(205, 185, 139))
    draw.text((700, 866), "热点坐标取自 Fallout 可执行文件的城镇地图表；下水道与旧避难所由区域内部连接", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def item_entries(region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                 item_messages: dict, note_index: dict, titles: dict) -> tuple[list[tuple], list[tuple], list[tuple]]:
    region_items, homepage_items, containers = [], [], []
    for obj in characters:
        title = titles[key(region, obj)]
        owner = f"[[{title}\\|{short_title(title)}]]"
        for entry in obj.get("inventory", []):
            kind, en, zh = bb.item_data(entry["item"], lookup, item_messages)
            record = (kind, bb.item_link(en, zh, note_index), owner, int(entry["quantity"]))
            region_items.append(record)
            homepage_items.append((*record, region.title))
    for obj in objects:
        if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0:
            continue
        kind, en, zh = bb.item_data(obj, lookup, item_messages)
        name = bb.item_link(en, zh, note_index)
        location = f"地面对象 ID {obj['object_id']}；tile {obj['tile']}"
        if obj["prototype"].get("subtype_name") == "container":
            container_name = f"{name}（对象 ID {obj['object_id']}；tile {obj['tile']}）"
            contents = []
            for entry in obj.get("inventory", []):
                ikind, ien, izh = bb.item_data(entry["item"], lookup, item_messages)
                iname = bb.item_link(ien, izh, note_index)
                quantity = int(entry["quantity"])
                contents.append(f"{iname} ×{quantity}")
                homepage_items.append((ikind, iname, container_name, quantity, region.title))
            containers.append((container_name, "<br>".join(contents) if contents else "空"))
        else:
            record = (kind, name, location, 1)
            region_items.append(record)
            homepage_items.append((*record, region.title))
    return region_items, homepage_items, containers


def character_note(vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path):
    text, title, named = bone.character_note(vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages,
                                             critter_messages, note_index, map_filename, sprite_filename, art_name, attachments)
    text = text.replace("Boneyard 晒骨场", LOCATION)
    text = text.replace("tags: [辐射1, 人物, 地点, 晒骨场]", "tags: [辐射1, 人物, 地点, 大墓地]")
    text = text.replace("[[Necropolis 大墓地\\|晒骨场]]", "[[Necropolis 大墓地\\|大墓地]]")
    text = text.replace("地点/Boneyard 晒骨场/", "地点/Necropolis 大墓地/")
    text = text.replace("\n\n## 对话头像\n\n人物脚本和人物原型没有提供可确认的独立 HEADS 对话头像。", "")
    return text, title, named


def creature_rows(creatures: list[dict], lookup: dict, critter_messages: dict) -> list[str]:
    rows = []
    for obj in sorted(creatures, key=lambda value: int(value["object_id"])):
        proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
        en, zh = critter_messages.get(int(proto["message_id"]), ("Unknown Creature", "未知生物"))
        rows.append(f"| {obj['object_id']} | {en} {zh} | `{script_stem(obj)}.INT` | {obj['tile']} |")
    return rows


def task_rows(region: Region) -> list[str]:
    rows = []
    if region.title == "Sewers under Hall 监狱区下水道":
        rows.append(f"| [[{PUMP_TASK}\\|修理大墓地的水泵]] | [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\\|地下僵尸领袖]] | [[Sewers under Hall 监狱区下水道\\|监狱区下水道]] | 在此接取任务、说明水泵零件位置，并可在取得零件后获得修理帮助。 |")
    if region.title == "Sewers under Watershed 供水区下水道":
        rows.append(f"| [[{PUMP_TASK}\\|修理大墓地的水泵]] | [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\\|地下僵尸领袖]] | [[Sewers under Hall 监狱区下水道\\|监狱区下水道]] | 在此找到含水泵零件的名贵垃圾。 |")
    if region.title == "Watershed 供水区":
        rows.append(f"| [[{PUMP_TASK}\\|修理大墓地的水泵]] | [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\\|地下僵尸领袖]] | [[Sewers under Hall 监狱区下水道\\|监狱区下水道]] | 使用零件修复地表供水设施。 |")
        rows.append(f"| [[{KILL_TASK}\\|消灭供水区的超级变种人]] | [[{LOCATION} - Set 赛特（ID 1556）\\|Set 赛特]] | [[Hall 监狱区\\|监狱区]] | 哈里及其同伴构成本区域的任务目标群体。 |")
    if region.title == "Hall 监狱区":
        rows.append(f"| [[{KILL_TASK}\\|消灭供水区的超级变种人]] | [[{LOCATION} - Set 赛特（ID 1556）\\|Set 赛特]] | [[Hall 监狱区\\|监狱区]] | 在此接取和回报；盖瑞特负责带路并发放报酬。 |")
    if region.map_name == "VAULTNEC":
        rows.append("| 找到净水芯片 | 13 号避难所监督者 | [[Vault 13 13号避难所\\|13号避难所]] | 本区域属于主线目标地点；规范任务不在大墓地包内重复建页。 |")
    return rows or ["| — | — | — | 本区域没有独立任务或主线目标环节。 |"]


def write_region_page(vault_dir: Path, region: Region, characters: list[dict], creatures: list[dict], objects: list[dict],
                      lookup: dict, critter_messages: dict, item_messages: dict, note_index: dict, titles: dict) -> None:
    named_rows, generic_rows = [], []
    for index, obj in enumerate(sorted(characters, key=lambda value: int(value["object_id"])), 1):
        oid, title = int(obj["object_id"]), titles[key(region, obj)]
        row = f"| {index} | {oid} | [[{title}\\|{short_title(title)}]] | {f'`{script_stem(obj)}.INT`' if script_stem(obj) else '无独立脚本'} |"
        (named_rows if oid in NAMED else generic_rows).append(row)
    region_items, _, containers = item_entries(region, characters, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {qty} |" for kind, name, owner, qty in sorted(region_items)]
    container_rows = [f"| {region.title} | {name} | {contents} |" for name, contents in containers]
    services = [f"| {name} | {provider} | {content} |" for name, provider, content in region.services]
    page = rf'''---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, 大墓地]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[{LOCATION}\|{LOCATION}]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

## 地图

![[{region.title}地图（人物与物品标注，完整原始画布）.png|900]]

绿色轮廓与标签表示人物或生物，黄色轮廓与标签表示地面物品和容器。附件完整保留渲染器原始画布与像素尺寸，没有按标签边界裁切或缩小；它只表达 MAP 保存的静态状态。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(services) if services else '| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |'}

## 人物

### 专名人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(named_rows) if named_rows else '| — | — | — | — |'}

### 普通人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(generic_rows) if generic_rows else '| — | — | — | — |'}

## 生物

| 地图对象 ID | 生物 | 脚本 | tile |
|---:|---|---|---:|
{chr(10).join(creature_rows(creatures, lookup, critter_messages)) if creatures else '| — | 本区域没有从人物表中剥离的生物对象。 | — | — |'}

## 物品

下表列人物随身库存和地图顶层非容器物品；容器库存只在下一节展开。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows) if item_rows else '| — | — | — | 本区域没有人物库存或地面非容器物品。 |'}

## 容器

| 区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows) if container_rows else f'| {region.title} | — | 本区域没有容器对象。 |'}

## 任务

| 任务名 | 任务链上第一个发起人 | 发起人所在区域 | 本区域中的环节 |
|---|---|---|---|
{chr(10).join(task_rows(region))}
'''
    (vault_dir / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_tasks(vault_dir: Path) -> None:
    pump_dir = vault_dir / "Sewers under Hall 监狱区下水道/任务"
    pump_dir.mkdir(parents=True, exist_ok=True)
    pump = rf'''---
title: "Fix the Water Pump 修理大墓地的水泵"
aliases: ["Fix the Water Pump", "修理大墓地的水泵"]
tags: [辐射1, 任务, 大墓地, 监狱区下水道]
quest_giver: Underground Ghoul Leader 地下僵尸领袖
quest_giver_map_object_id: 3058
---

# Fix the Water Pump 修理大墓地的水泵

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | Fix the water pump. |
| 当前中文 | 修理大墓地的水泵。 |
| Pip-Boy 消息 | `PIPBOY.MSG` 752 |

## 任务概览

[[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）|地下僵尸领袖]]说明：大墓地原先依靠供水区水泵，水泵损坏后只能依赖旧避难所的净化系统；若直接取走净水芯片而不恢复水泵，地表和地下居民都会失去水源。

## 接取条件

与地下僵尸领袖讨论水、供水区和净水芯片时，可以答应寻找水泵零件。若已经取得零件，对话会进入“你先找到了”的分支。

## 目标与完成

1. 从[[Sewers under Hall 监狱区下水道|监狱区下水道]]接受请求。
2. 前往[[Sewers under Watershed 供水区下水道|供水区下水道]]，取得地面对象 ID 1161 的[[Junk 名贵垃圾|名贵垃圾]]；物品说明明确包含水泵零件。
3. 可返回领袖处展示零件并取得修理帮助。
4. 在[[Watershed 供水区|供水区]]对水泵使用零件与修理流程，恢复供水并完成 Pip-Boy 任务。

## 接取与报酬

领袖消息 160 表示会把附近找到的几本书交给玩家，用于帮助修理；当前页面不从台词措辞推断书籍数量。任务的主要后果是恢复大墓地供水，使取走净水芯片不再必然切断居民水源。

## 人物与区域

| 人物或对象 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\|地下僵尸领袖]] | 3058 | [[Sewers under Hall 监狱区下水道\|监狱区下水道]] | 第一个发起人、零件位置说明者。 |
| [[Junk 名贵垃圾\|名贵垃圾]] | 1161 | [[Sewers under Watershed 供水区下水道\|供水区下水道]] | 保存水泵修理零件。 |
| 水泵 | — | [[Watershed 供水区\|供水区]] | 使用零件完成修理。 |

## 来源边界

任务名称来自 `PIPBOY.MSG` 752；接取、零件说明、书籍帮助和修复后的对话来自 `LEADER.INT` 与当前有效消息；物品位置来自 `WATRSHD.MAP`。静态地图上的对象不能单独证明任务已完成。
'''
    (pump_dir / f"{PUMP_TASK}.md").write_text(pump, encoding="utf-8")

    kill_dir = vault_dir / "Hall 监狱区/任务"
    kill_dir.mkdir(parents=True, exist_ok=True)
    kill = rf'''---
title: "Kill the Mutants at the Watershed 消灭供水区的超级变种人"
aliases: ["Kill the Mutants at the Watershed", "消灭供水区的超级变种人"]
tags: [辐射1, 任务, 大墓地, 监狱区]
quest_giver: Set 赛特
quest_giver_map_object_id: 1556
---

# Kill the Mutants at the Watershed 消灭供水区的超级变种人

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | Kill the mutants at the watershed. |
| 当前中文 | 消灭供水区的超级变种人。 |
| Pip-Boy 消息 | `PIPBOY.MSG` 751 |

## 任务概览

[[{LOCATION} - Set 赛特（ID 1556）|Set 赛特]]称超级变种人控制了供水区，并要求玩家清除他们，以扩展自己的地盘并削弱“主教”的影响。

## 接取条件

赛特在多条初次交谈或再次交谈分支中提出同一目标。玩家可以接受、拒绝或激怒赛特；只有实际进入接受分支后才应视为接取。

## 目标与完成

1. 在[[Hall 监狱区|监狱区]]接受赛特的要求。
2. 前往[[Watershed 供水区|供水区]]，清除哈里及其变种人同伴。
3. 返回赛特处回报。赛特会让玩家跟随[[{LOCATION} - Garret 盖瑞特（ID 1474）|盖瑞特]]领取报酬。

## 接取与报酬

盖瑞特的有效消息保存三种可见报酬组合：

- 1 把双管猎枪、10 发霰弹枪子弹、4 发闪光弹、4 瓶核子可乐和 200 瓶盖；
- 1 把双管猎枪、10 发霰弹枪子弹和 100 瓶盖；
- 4 发闪光弹、4 瓶核子可乐和 50 瓶盖。

另有追加 100 瓶盖的分支。具体得到哪一组由赛特和盖瑞特脚本中的对话状态决定，不能把全部组合视为一次性总奖励。

## 人物与区域

| 人物 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[{LOCATION} - Set 赛特（ID 1556）\|Set 赛特]] | 1556 | [[Hall 监狱区\|监狱区]] | 第一个发起人、回报对象。 |
| [[{LOCATION} - Garret 盖瑞特（ID 1474）\|Garret 盖瑞特]] | 1474 | [[Hall 监狱区\|监狱区]] | 带路并发放条件性报酬。 |
| [[{LOCATION} - Harry 哈里（ID 549）\|Harry 哈里]] | 549 | [[Watershed 供水区\|供水区]] | 供水区变种人守卫首要交互对象。 |
| Barry、Gary、Larry、Sally、Terry | 457、458、460、1313、849 | [[Watershed 供水区\|供水区]] | 哈里的变种人同伴。 |

## 来源边界

任务名称来自 `PIPBOY.MSG` 751；目标、回报与威胁来自 `SET.INT` 和当前有效消息；报酬文字来自 `GARRET.INT` 消息。地图对象清单只表达保存状态，不代替脚本完成条件。
'''
    (kill_dir / f"{KILL_TASK}.md").write_text(kill, encoding="utf-8")


def write_home(vault_dir: Path, region_people: dict, region_creatures: dict, region_objects: dict,
               titles: dict, critter_messages: dict, item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, animal_rows, item_rows, container_rows = [], [], [], [], [], []
    for region in REGIONS:
        people, creatures = region_people[region.title], region_creatures[region.title]
        kind = "地表区域" if region.elevation == 1 and region.map_name != "VAULTNEC" else "地下通道" if region.elevation == 0 and region.map_name != "VAULTNEC" else "旧避难所楼层"
        relation = "城镇海报直接入口。" if region.title in {"Hotel 旅馆区", "Hall 监狱区", "Watershed 供水区"} else "由区域内梯子、通道或楼层连接。"
        region_rows.append(f"| {kind} | [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` / e{region.elevation} | {relation} |")
        for obj in sorted(people, key=lambda value: int(value["object_id"])):
            oid, title = int(obj["object_id"]), titles[key(region, obj)]
            row = f"| [[{region.title}\\|{region.chinese}]] | {oid} | [[{title}\\|{short_title(title)}]] |"
            (named_rows if oid in NAMED else generic_rows).append(row)
        for obj in creatures:
            proto = region_objects[region.title][1][("critter", int(obj["prototype"]["list_index"]))]
            en, zh = critter_messages.get(int(proto["message_id"]), ("Unknown Creature", "未知生物"))
            animal_rows.append(f"| [[{region.title}\\|{region.chinese}]] | {obj['object_id']} | {en} {zh} | `{script_stem(obj)}.INT` |")
        objects, lookup = region_objects[region.title]
        _, home_items, containers = item_entries(region, people, objects, lookup, item_messages, note_index, titles)
        item_rows.extend(f"| {kind} | {name} | [[{region.title}]] | {owner} | {qty} |" for kind, name, owner, qty, _ in home_items)
        container_rows.extend(f"| [[{region.title}]] | {name} | {contents} |" for name, contents in containers)
    page = rf'''---
title: "{LOCATION}"
aliases: ["Necropolis", "大墓地", "Bakersfield"]
tags: [辐射1, 地点, 大墓地]
world_map_grid: "22,13"
world_map_pixel: "1125,675"
---

# {LOCATION}

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图与 Pip-Boy | Necropolis / 大墓地 |
| 战前城市 | Bakersfield / 贝克斯菲尔德 |
| 知识库标题 | {LOCATION} |
| 地表资源 | `HOTEL.MAP`、`HALLDED.MAP`、`WATRSHD.MAP` |
| 地下资源 | 三张地表 MAP 的 elevation 0，以及 `VAULTNEC.MAP` 三层 |

## 地点概览

大墓地位于世界地图网格 `(22, 13)`、像素坐标 `(1125, 675)`。原作城镇海报提供旅馆区、监狱区和供水区三个地表入口；每个地表区域各有一层下水道，供水区还通往旧避难所三层，因此本包按九个“地图 + elevation”区域展开。

提可称这里曾是贝克斯菲尔德、如今是僵尸的家；坦蒂和伊恩把它描述为“死人的城市”。这些属于人物说法。地图和脚本直接确认的核心关系是：赛特控制地表大厅，和平僵尸转入地下，超级变种人控制供水区，而旧避难所保存净水芯片目标。

## 世界地图位置

世界地图索引为 `5`，网格坐标 `(22, 13)`，地点锚点像素坐标 `(1125, 675)`；总览另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[{LOCATION}城镇地图（区域标注）.jpg|900]]

海报原图是 `TWNMAP05.FRM`。原作可执行文件的城镇地图表保存三个入口热点：旅馆区 `(398,265)`、监狱区 `(239,224)`、供水区 `(79,207)`；它们分别进入 `HOTEL.MAP`、`HALLDED.MAP` 与 `WATRSHD.MAP` 的 elevation 1。

## 城市分区

| 英文名称 | 中文名称 |
|---|---|
| [[Hotel 旅馆区\|Hotel]] | [[Hotel 旅馆区\|旅馆区]] |
| [[Hall 监狱区\|Hall]] | [[Hall 监狱区\|监狱区]] |
| [[Watershed 供水区\|Watershed]] | [[Watershed 供水区\|供水区]] |

## 区域与楼层

| 归属或入口 | 区域与楼层 | 资源身份 | 进入方式或关系 |
|---|---|---|---|
{chr(10).join(region_rows)}

## 商店和服务

| 区域 | 商店或服务 | 提供者 | 内容 |
|---|---|---|---|
| [[Sewers under Hall 监狱区下水道]] | 休息 | [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\|地下僵尸领袖]] | 明确允许玩家在地下居民处休息。 |
| [[Watershed 供水区]] | 修理水泵 | 供水设施 | 取得零件后通过修理流程恢复供水。 |

## 地图中的人物

完整对象清点得到 {sum(len(value) for value in region_people.values())} 名人物对象；同类普通人物按地图对象 ID 分页。另有 {sum(len(value) for value in region_creatures.values())} 个变种老鼠对象，单列为生物，不建立人物页。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_rows)}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows)}

### 生物对象

| 区域 | 地图对象 ID | 生物 | 脚本 |
|---|---:|---|---|
{chr(10).join(animal_rows)}

## 地图中的物品

下表汇总人物随身库存、地面物品和容器直接库存；一个单元格只表示一种物品。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(sorted(item_rows))}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 | 经过区域 |
|---|---|---|---|
| [[{KILL_TASK}\|消灭供水区的超级变种人]] | [[{LOCATION} - Set 赛特（ID 1556）\|Set 赛特]] | [[Hall 监狱区\|监狱区]] | 监狱区、供水区。 |
| [[{PUMP_TASK}\|修理大墓地的水泵]] | [[{LOCATION} - Underground Ghoul Leader 地下僵尸领袖（ID 3058）\|地下僵尸领袖]] | [[Sewers under Hall 监狱区下水道\|监狱区下水道]] | 监狱区下水道、供水区下水道、供水区。 |
| 找到净水芯片 | 13 号避难所监督者 | [[Vault 13 13号避难所\|13号避难所]] | 大墓地旧避难所三层是目标路线；因第一个发起人在 13 号避难所，本包不重复创建任务页。 |

## 来源边界

- 地点坐标、地图编号、楼层名称来自世界地图、`MAP.MSG` 和结构化 MAP；三个海报入口坐标来自游戏可执行文件中的城镇地图表。
- 人物、变种老鼠、物品与容器来自四张 MAP 的完整对象清点；人物身份、对话与任务来自对应 INT 脚本和当前有效消息。
- 区域图与人物高亮图全部保留完整渲染画布和原始像素尺寸，没有按标签框裁切或缩小。
- 提可、坦蒂和伊恩的描述保留为人物说法，不替代地图与脚本事实。
'''
    (vault_dir / f"{LOCATION}.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    configure_helpers()
    vault = args.vault_root.resolve()
    vault_dir = vault / f"地点/{LOCATION}"
    vault_dir.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        for legacy in (
            vault_dir / "Watershed 水处理房.md",
            vault_dir / "Hall 监狱区/任务/Kill the Mutants at the Watershed 消灭供水区的超级变种人（Set 赛特 ID 1556）.md",
            vault_dir / "Sewers under Hall 监狱区下水道/任务/Fix the Water Pump 修理大墓地的水泵（Underground Ghoul Leader 地下僵尸领袖 ID 3058）.md",
        ):
            legacy.unlink(missing_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    home_attachments = vault_dir / "attachments"
    home_attachments.mkdir(exist_ok=True)
    poster(home_attachments / f"{LOCATION}城镇地图（区域标注）.jpg")
    region_people, region_creatures, region_objects, titles = {}, {}, {}, {}
    evidence = {"location": "Necropolis", "source_maps": ["HOTEL.MAP", "HALLDED.MAP", "WATRSHD.MAP", "VAULTNEC.MAP"],
                "town_poster": "TWNMAP05.FRM", "world_map": {"grid": [22, 13], "pixel": [1125, 675]},
                "town_hotspots": [{"map": "HOTEL", "elevation": 1, "x": 398, "y": 265}, {"map": "HALLDED", "elevation": 1, "x": 239, "y": 224}, {"map": "WATRSHD", "elevation": 1, "x": 79, "y": 207}],
                "maps": [], "character_notes": 0, "creature_objects": 0, "task_pages": [KILL_TASK, PUMP_TASK]}
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
        creatures = [obj for obj in critters if script_stem(obj) in CREATURE_SCRIPTS]
        people = [obj for obj in critters if script_stem(obj) not in CREATURE_SCRIPTS]
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
        evidence["maps"].append({"map": region.map_name, "elevation": region.elevation, "region": region.title,
                                 "people": len(people), "named_people": sum(int(obj["object_id"]) in NAMED for obj in people),
                                 "creatures": len(creatures), "objects": len(objects), "top_level_items": len(top_items),
                                 "containers": sum(obj.get("prototype", {}).get("subtype_name") == "container" for obj in top_items),
                                 "render": str(source_map.relative_to(REPO))})
        evidence["character_notes"] += len(people)
        evidence["creature_objects"] += len(creatures)
    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        write_region_page(vault_dir, region, region_people[region.title], region_creatures[region.title], objects,
                          lookup, critter_messages, item_messages, note_index, titles)
    write_tasks(vault_dir)
    write_home(vault_dir, region_people, region_creatures, region_objects, titles, critter_messages, item_messages, note_index)
    sync_tree(vault_dir, REPO)
    evidence_path = REPO / "workspace/output/maps-knowledge/necropolis-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated Necropolis package: {len(REGIONS)} regions, {evidence['character_notes']} character notes, {evidence['creature_objects']} creature objects, 2 task pages")


if __name__ == "__main__":
    main()
