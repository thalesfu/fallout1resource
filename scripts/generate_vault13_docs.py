#!/usr/bin/env python3
"""Generate the complete Fallout 1 Vault 13 location package for Obsidian."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fallout1_character_topics import sync_tree, topic_records


REPO = Path(__file__).resolve().parents[1]
LOCATION = "Vault 13 13号避难所"


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bone = import_script("vault13_boneyard_helpers", "generate_boneyard_docs.py")
bb = bone.bb
ORIGINAL_ITEM_LINK = bb.item_link


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
    Region(
        "Cave Entrance 山洞通道", "Cave Entrance", "山洞通道", "V13ENT", 0, 35,
        "13 号避难所外部的天然洞穴通道。地图保存二十只变种地鼠、通向荒地的出口、通往避难所入口层的连接，以及一具带有刀和 10mm AP 弹药的尸骨。",
    ),
    Region(
        "Entrance 避难所入口", "Entrance", "避难所入口", "VAULT13", 0, 6,
        "避难所巨门内侧的入口层。洞穴与金属走廊在本层衔接，医疗室和配给锁柜也位于这里；地图脚本的出口对象把它与山洞通道连接。",
        (("医疗与辐射治疗", "Vault 13 Doctor 避难所医生", "医生脚本可治疗伤势与辐射，并说明墙边医疗箱中的治疗针按配给提供。"),),
    ),
    Region(
        "Living Quarters 避难所生活区", "Living Quarters", "避难所生活区", "VAULT13", 1, 6,
        "避难所居民的生活层。特蕾莎、辛迪、莱尔和多名普通居民位于本层；不安居民围绕是否离开避难所形成争论，偷水事件的居民证词也集中在这里。",
    ),
    Region(
        "Command Center 避难所指挥中心", "Command Center", "避难所指挥中心", "VAULT13", 2, 6,
        "避难所管理、图书馆、水资源与储藏设施所在的最深层。监督者在这里发起净水芯片及两项变种人主线任务；水务警卫在配给区域提供偷水事件的直接线索。",
        (("水配给与有限补给", "Water Guard 水务警卫", "水务警卫说明早晨按定额分水；玩家执行重要任务时，可从附近补给中有限取用。"),),
    ),
)


NAMED = {
    1202: ("Theresa", "特蕾莎", "观察文字直接给出 Theresa / 特蕾莎。"),
    3318: ("Cindy", "辛迪", "观察文字直接给出 Cindy / 辛迪。"),
    3403: ("Lyle", "莱尔", "观察文字直接给出 Lyle / 莱尔。"),
}


SCRIPT_ROLES = {
    "GENVAULT": ("Vault Dweller", "避难所居民", "使用避难所居民共用脚本，素材没有提供个人姓名。"),
    "MEDIC": ("Vault 13 Doctor", "避难所医生", "观察文字直接称其为 13 号避难所医生；这是职务，不是个人姓名。"),
    "OVER": ("Overseer", "监督者", "观察文字只称其为所长；游戏素材没有提供可确认的个人姓名。"),
    "REBEL": ("Restless Vault Dweller", "不安的避难所居民", "脚本观察文字称其为沮丧或普通避难所居民；这是任务群体身份。"),
    "VALTCTZN": ("Vault Dweller", "避难所居民", "使用避难所居民共用脚本，素材没有提供个人姓名。"),
    "WTRGRD": ("Water Guard", "水务警卫", "观察文字称其为负责分发水的警卫；这是职务。"),
    "WTRTHIEF": ("Water Thief", "偷水贼", "脚本状态确认其是偷取避难所储备水的人；素材没有提供个人姓名。"),
}


CREATURE_SCRIPTS = {"WANRATS"}

TASKS = (
    {
        "filename": "Calm rebel faction 让不安的居民平静下来（发起人 ID 1202）",
        "en": "Calm rebel faction", "zh": "让不安的居民平静下来", "giver_id": 1202,
        "giver": "Theresa 特蕾莎", "region": "Living Quarters 避难所生活区",
        "overview": "特蕾莎主张带领一部分居民离开避难所。玩家可以在净水危机期间与她辩论外界风险、监督者动机和等待净水芯片的必要性，并通过和平说服使不安派系暂缓行动。",
        "steps": "1. 在生活区与特蕾莎交谈，了解她对监督者控制和避难所长期生存的质疑。\n2. 在可达对话分支中反驳立即离开的方案，并争取更多寻找净水芯片的时间。\n3. 特蕾莎接受暂缓行动后，脚本显示和平说服派系并授予 750 点经验值。",
        "reward": "和平说服成功时获得 750 点经验值。",
        "boundary": "Pip-Boy 标题称其为“Calm rebel faction”；任务没有独立的委托仪式。本文以特蕾莎作为派系领袖和实际交互起点，不把普通不安居民误写为发起人。",
    },
    {
        "filename": "Destroy the Mutant leader 消灭变种人首领（发起人 ID 2209）",
        "en": "Destroy the Mutant leader", "zh": "消灭变种人首领", "giver_id": 2209,
        "giver": "Overseer 监督者", "region": "Command Center 避难所指挥中心",
        "overview": "净水芯片归还后，监督者根据玩家的外界报告判断敌对变种人数量异常，并要求消除威胁。Pip-Boy 把消灭变种人领袖与毁灭其来源分成两项目标。",
        "steps": "1. 归还净水芯片并向监督者报告外界情况。\n2. 调查变种人组织，找到其领袖。\n3. 在大教堂地下巢穴击败变种人领袖；返回监督者时，他还会继续核对制造变种人的实验室是否已被摧毁。",
        "reward": "脚本把两项变种人目标作为后续主线共同核对；本页不把最终结局奖励拆成未经证实的单项数值。",
        "boundary": "目标阶段位于[[Cathedral 大教堂|大教堂]]，但任务最初由 13 号避难所监督者发起，因此规范页保存在本包。",
    },
    {
        "filename": "Destroy the source of the Mutants 毁灭变种人的源头（发起人 ID 2209）",
        "en": "Destroy the source of the Mutants", "zh": "毁灭变种人的源头", "giver_id": 2209,
        "giver": "Overseer 监督者", "region": "Command Center 避难所指挥中心",
        "overview": "监督者根据变种人数量与增长速度推断有人在持续制造新的敌对变种人，并要求玩家找到实验室并将其摧毁。",
        "steps": "1. 在归还净水芯片后的报告阶段听取监督者的计算与判断。\n2. 向西调查变种人聚集地，进入[[Military Base 军事基地|军事基地]]。\n3. 破坏变种人生产设施；基地脚本可通过病毒槽控制计算机启动自毁。\n4. 返回监督者时，他会分别核对实验室与领袖两项目标。",
        "reward": "监督者对两项后续威胁进行联合结算；本文不虚构单独物品奖励。",
        "boundary": "目标阶段位于军事基地；各基地区域页只记录本地环节，规范任务页按第一个发起人归入本包。",
    },
    {
        "filename": "Find the Water Chip 找到净水芯片（发起人 ID 2209）",
        "en": "Find the Water Chip", "zh": "找到净水芯片", "giver_id": 2209,
        "giver": "Overseer 监督者", "region": "Command Center 避难所指挥中心",
        "overview": "监督者说明净水系统控制芯片损坏，避难所储水将在限定时间内耗尽，并把寻找替代芯片的任务交给玩家。",
        "steps": "1. 从监督者处接受寻找替代净水芯片的任务；初始期限为三个月。\n2. 按地图线索先调查 15 号避难所，并继续在外界寻找可用芯片。\n3. 在[[Necropolis 大墓地|大墓地]]旧避难所指挥中心取得净水芯片。\n4. 把芯片交给监督者；脚本确认芯片通过自检并恢复供水。",
        "reward": "成功归还净水芯片并拯救避难所时获得 7500 点经验值。",
        "boundary": "大墓地是任务目标地点，不是第一个发起地点；任务规范页因此只在本包创建一次。",
    },
    {
        "filename": "Find the Water Thief 查出偷水的人（发起人 ID 2409）",
        "en": "Find the Water Thief", "zh": "查出偷水的人", "giver_id": 2409,
        "giver": "Water Guard 水务警卫", "region": "Command Center 避难所指挥中心",
        "overview": "水务警卫说明自己在深夜检查库房时被人用大管子击昏，事件发生在避难所已经开始担忧水资源之后。玩家据此调查居民并寻找偷水者。",
        "steps": "1. 向水务警卫询问伤势和偷水经过，并表示愿意调查。\n2. 在生活区向辛迪、莱尔等居民了解偷水造成的恐慌。\n3. 在夜间或脚本条件满足后识别携带撬棍的偷水者。\n4. 可将其逮住，或在冲突中杀死；脚本分别记录不同结算。",
        "reward": "成功逮住偷水贼获得 1000 点经验值；杀死威胁储备水的小偷获得 500 点经验值。",
        "boundary": "偷水者是任务目标，不是发起人；辛迪和莱尔是生活区的证词与反馈节点。",
    },
)


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
    return proto_en, proto_zh, f"人物原型分类为 {proto_en} / {proto_zh}；素材没有提供个人姓名。", False


def short_title(title: str) -> str:
    return title.removeprefix(f"{LOCATION} - ").split("（ID", 1)[0].strip()


def key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def task_association(region: Region, oid: int) -> str:
    names = []
    if oid == 1202:
        names.append(TASKS[0]["filename"])
    if oid == 2209:
        names.extend(task["filename"] for task in TASKS[1:4])
    if oid == 2409:
        names.append(TASKS[4]["filename"])
    if oid in {2779, 3318, 3403}:
        names.append(TASKS[4]["filename"])
    if not names:
        return ""
    return "# 任务关联\n\n" + "\n".join(f"- [[{name}|{name.split('（', 1)[0]}]]" for name in names)


def item_link(en: str, zh: str, note_index: dict[str, str]) -> str:
    value = ORIGINAL_ITEM_LINK(en, zh, note_index)
    if en == zh:
        value = value.replace(f"{en} {zh}", en)
    return value


def configure_helpers() -> None:
    bone.NAMED = NAMED
    bone.SCRIPT_ROLES = SCRIPT_ROLES
    bone.identity = identity
    bone.short_title = short_title
    bone.task_association = task_association
    bb.item_link = item_link
    bb.HEADS = {"OVER": "OVRSR"}


def poster(output: Path) -> None:
    source = Image.open(REPO / "workspace/output/images/master/ART/INTRFACE/TWNMAP00.frm/TWNMAP00.frm.frames/sequence-00/frame-000.png").convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (18, 18, 16, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 22)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((700, 38), LOCATION, font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP00.FRM · 原作海报与四个区域视觉锚点", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale, left, top = 1.72, 310, 92
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    draw.rounded_rectangle((left - 10, top - 10, left + scaled.width + 10, top + scaled.height + 10), radius=18, fill=(7, 7, 6), outline=(89, 70, 46), width=5)
    canvas.alpha_composite(scaled, (left, top))
    anchors = (
        ("Cave Entrance 山洞通道", "V13ENT · e0", 352, 264, 40, 600),
        ("Entrance 避难所入口", "VAULT13 · e0", 315, 311, 1060, 655),
        ("Living Quarters 生活区", "VAULT13 · e1", 296, 263, 1060, 430),
        ("Command Center 指挥中心", "VAULT13 · e2", 280, 214, 40, 330),
    )
    for label, meta, sx, sy, bx, by in anchors:
        px, py = left + sx * scale, top + sy * scale
        bw, bh = 300, 86
        edge_x = bx + bw if bx < 700 else bx
        draw.line((px, py, (px + edge_x) / 2, by + bh / 2, edge_x, by + bh / 2), fill=(224, 180, 91), width=3)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
        draw.text((bx + 14, by + 16), label, font=label_font, fill=(248, 232, 188))
        draw.text((bx + 14, by + 54), meta, font=meta_font, fill=(205, 185, 139))
    draw.text((700, 866), "锚点只帮助理解洞穴与三层避难所的关系，不冒充引擎按钮坐标", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def task_rows(region: Region) -> list[str]:
    rows = []
    for task in TASKS:
        if task["region"] == region.title:
            rows.append(f"| [[{task['filename']}\\|{task['en']} {task['zh']}]] | {task['giver']}（ID {task['giver_id']}） | [[{region.title}\\|{region.chinese}]] | 本区域发起或完成结算。 |")
        elif region.title == "Living Quarters 避难所生活区" and task["en"] == "Find the Water Thief":
            rows.append(f"| [[{task['filename']}\\|{task['en']} {task['zh']}]] | {task['giver']}（ID {task['giver_id']}） | [[Command Center 避难所指挥中心\\|指挥中心]] | 本层提供居民证词，并保存偷水者对象。 |")
    return rows or ["| — | — | — | 本区域没有独立任务发起或目标环节。 |"]


def creature_rows(creatures: list[dict]) -> list[str]:
    return [f"| {obj['object_id']} | Cave Rat 变种地鼠 | `{script_stem(obj)}.INT` | {obj['tile']} |" for obj in sorted(creatures, key=lambda value: int(value["object_id"]))]


def write_region_page(vault_dir: Path, region: Region, people: list[dict], creatures: list[dict], objects: list[dict], lookup: dict,
                      item_messages: dict, note_index: dict, titles: dict[tuple[str, int, int], str]) -> None:
    named_rows, generic_rows = [], []
    for index, obj in enumerate(sorted(people, key=lambda value: int(value["object_id"])), 1):
        oid, title = int(obj["object_id"]), titles[key(region, obj)]
        row = f"| {index} | {oid} | [[{title}\\|{short_title(title)}]] | `{script_stem(obj)}.INT` |"
        (named_rows if oid in NAMED else generic_rows).append(row)
    items, containers = bone.item_records(region, people, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {qty} |" for kind, name, _, owner, qty in sorted(items)] or ["| — | — | — | 0 |"]
    container_rows = [f"| {name} | {contents} |" for _, name, contents in containers] or ["| — | 本区域没有容器。 |"]
    services = [f"| {service} | {provider} | {detail} |" for service, provider, detail in region.services] or ["| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |"]
    biology = ""
    if creatures:
        biology = f"""\n## 生物\n\n| 地图对象 ID | 生物 | 脚本 | 地图格 |\n|---:|---|---|---:|\n{chr(10).join(creature_rows(creatures))}\n"""
    page = f"""---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, 13号避难所]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文名称 | {region.chinese} |
| 世界地图地点 | [[Vault 13 13号避难所\\|Vault 13 13号避难所]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

## 地图

![[{region.title}地图（人物与物品标注，完整原始画布）.png|900]]

绿色轮廓与标签表示人物或生物，黄色轮廓与标签表示地面物品和容器。图片保留渲染器完整原始画布与原始像素尺寸，没有按标签边界裁图，也没有缩小；它只表达 MAP 保存的静态状态。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(services)}

## 人物

### 专名人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(named_rows) if named_rows else '| — | — | 完整对象清点没有发现专名人物。 | — |'}

### 普通人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(generic_rows) if generic_rows else '| — | — | 完整对象清点没有发现普通人物。 | — |'}
{biology}
## 物品

人物随身库存与地面物品列在这里；容器直接库存只在下一节展开。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 容器名 | 物品列表 |
|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 任务链上第一个发起人 | 发起人所在区域 | 本区域中的环节 |
|---|---|---|---|
{chr(10).join(task_rows(region))}

## 来源边界

- 区域、人物、生物、物品与容器来自 `{region.map_name}.MAP` elevation {region.elevation} 的完整对象清点。
- 服务与任务环节来自相应人物脚本和当前有效中文消息；地图只表示保存状态，不表示任意剧情时刻。
"""
    (vault_dir / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_tasks(vault_dir: Path) -> None:
    people_links = {
        1202: "[[Vault 13 13号避难所 - Theresa 特蕾莎（ID 1202）|Theresa 特蕾莎]]",
        2209: "[[Vault 13 13号避难所 - Overseer 监督者（ID 2209）|Overseer 监督者]]",
        2409: "[[Vault 13 13号避难所 - Water Guard 水务警卫（ID 2409）|Water Guard 水务警卫]]",
    }
    for task in TASKS:
        task_dir = vault_dir / task["region"] / "任务"
        task_dir.mkdir(parents=True, exist_ok=True)
        related = ""
        if task["en"] == "Find the Water Thief":
            related = "\n| 目标 | 2779 | [[Entrance 避难所入口\\|避难所入口]] | [[Vault 13 13号避难所 - Water Thief 偷水贼（ID 2779）\\|Water Thief 偷水贼]] |\n| 证词 | 3318 | [[Living Quarters 避难所生活区\\|生活区]] | [[Vault 13 13号避难所 - Cindy 辛迪（ID 3318）\\|Cindy 辛迪]] |\n| 证词 | 3403 | [[Living Quarters 避难所生活区\\|生活区]] | [[Vault 13 13号避难所 - Lyle 莱尔（ID 3403）\\|Lyle 莱尔]] |"
        page = f"""---
title: "{task['en']} {task['zh']}"
aliases: ["{task['en']}", "{task['zh']}"]
tags: [辐射1, 任务, 13号避难所]
quest_giver: "{task['giver']}"
quest_giver_map_object_id: {task['giver_id']}
---

# 名称

| 属性 | 内容 |
|---|---|
| 英文任务名 | {task['en']} |
| 中文任务名 | {task['zh']} |
| Pip-Boy 分组 | Vault 13 / 13号避难所 |
| 任务链上第一个发起人 | {people_links[task['giver_id']]}（地图对象 ID {task['giver_id']}） |

# 任务概览

{task['overview']}

# 目标与完成

{task['steps']}

# 报酬

{task['reward']}

# 人物与区域

| 角色 | 地图对象 ID | 区域 | 人物 |
|---|---:|---|---|
| 第一个发起人 | {task['giver_id']} | [[{task['region']}\\|{task['region']}]] | {people_links[task['giver_id']]} |{related}

# 来源边界

{task['boundary']}

任务标题来自 `PIPBOY.MSG` 的 Vault 13 分组；条件、可见台词与经验值来自发起人、目标或结算人物的 INT 脚本消息关联表。
"""
        (task_dir / f"{task['filename']}.md").write_text(page, encoding="utf-8")


def write_home(vault_dir: Path, region_people: dict[str, list[dict]], region_creatures: dict[str, list[dict]],
               region_objects: dict[str, tuple[list[dict], dict]], titles: dict[tuple[str, int, int], str],
               item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, creature_lines, all_items, all_containers = [], [], [], [], [], []
    for region in REGIONS:
        people, creatures = region_people[region.title], region_creatures[region.title]
        relation = "独立洞穴地图；出口连接避难所入口层" if region.map_name == "V13ENT" else "避难所内部楼层；通过楼梯和电梯与相邻层连接"
        region_rows.append(f"| {region.english} | [[{region.title}\\|{region.chinese}]] | {'独立地图' if region.map_name == 'V13ENT' else '地下层'} | {relation} |")
        for obj in sorted(people, key=lambda value: int(value["object_id"])):
            oid, title = int(obj["object_id"]), titles[key(region, obj)]
            row = f"| [[{region.title}\\|{region.chinese}]] | {oid} | [[{title}\\|{short_title(title)}]] |"
            (named_rows if oid in NAMED else generic_rows).append(row)
        for obj in creatures:
            creature_lines.append(f"| [[{region.title}\\|{region.chinese}]] | {obj['object_id']} | Cave Rat 变种地鼠 |")
        objects, lookup = region_objects[region.title]
        items, containers = bone.item_records(region, people, objects, lookup, item_messages, note_index, titles)
        all_items.extend(items)
        all_containers.extend(containers)
        for obj in objects:
            if obj.get("prototype", {}).get("type") != "item" or obj.get("prototype", {}).get("subtype_name") != "container" or int(obj.get("tile", -1)) < 0:
                continue
            _, container_en, container_zh = bb.item_data(obj, lookup, item_messages)
            container_name = f"{bb.item_link(container_en, container_zh, note_index)}（对象 ID {obj['object_id']}；tile {obj['tile']}）"
            for entry in obj.get("inventory", []):
                kind, en, zh = bb.item_data(entry["item"], lookup, item_messages)
                all_items.append((kind, bb.item_link(en, zh, note_index), region.title, container_name, int(entry["quantity"])))
    item_rows = [f"| {kind} | {name} | [[{region}]] | {owner} | {qty} |" for kind, name, region, owner, qty in sorted(all_items)]
    container_rows = [f"| [[{region}]] | {name} | {contents} |" for region, name, contents in all_containers]
    task_lines = [f"| [[{task['filename']}\\|{task['en']} {task['zh']}]] | {task['giver']}（ID {task['giver_id']}） | [[{task['region']}]] | {task['overview'].split('。')[0]}。 |" for task in TASKS]
    page = f"""---
title: "Vault 13 13号避难所"
aliases: ["Vault 13", "Vault13", "13号避难所", "１３号避难所"]
tags: [辐射1, 地点, 避难所]
world_map_grid: "16,1"
world_map_pixel: "825,75"
---

# Vault 13 13号避难所

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图 | Vault 13 / 13号避难所 |
| Pip-Boy 任务分组 | Vault 13 / １３号避难所 |
| 资源地图 | `V13ENT.MAP`、`VAULT13.MAP` |
| 知识库标题 | Vault 13 13号避难所 |

## 世界地图位置

13 号避难所位于世界地图网格 `(16, 1)`，地点中心像素坐标约为 `(825, 75)`，发现变量为 `67`。总览另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[Vault 13 13号避难所城镇海报（区域标注）.jpg|900]]

原作提供 `TWNMAP00.FRM` 海报。本图标出山洞通道、避难所入口、生活区与指挥中心的视觉关系；本地资源没有保存可复核的 Vault 13 引擎按钮表，因此标注点明确作为视觉锚点，不冒充精确点击坐标。

## 城市分区

| 英文名称 | 中文名称 |
|---|---|
| [[Cave Entrance 山洞通道\\|Cave Entrance]] | [[Cave Entrance 山洞通道\\|山洞通道]] |
| [[Entrance 避难所入口\\|Entrance]] | [[Entrance 避难所入口\\|避难所入口]] |
| [[Living Quarters 避难所生活区\\|Living Quarters]] | [[Living Quarters 避难所生活区\\|避难所生活区]] |
| [[Command Center 避难所指挥中心\\|Command Center]] | [[Command Center 避难所指挥中心\\|避难所指挥中心]] |

## 区域与楼层

| 归属或入口 | 区域与楼层 | 类型 | 进入方式或关系 |
|---|---|---|---|
{chr(10).join(region_rows)}

## 地图中的人物

完整对象清点得到 {sum(len(v) for v in region_people.values())} 名人物；另有 {sum(len(v) for v in region_creatures.values())} 只变种地鼠，作为生物单列。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_rows)}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows)}

### 生物

| 区域 | 地图对象 ID | 生物 |
|---|---:|---|
{chr(10).join(creature_lines)}

## 地图中的物品

下表汇总人物随身库存与地图地面物品，并把容器直接库存拆成独立行。数据只表示 MAP 保存状态。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows)}

## Pip-Boy 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 | 简短目标 |
|---|---|---|---|
{chr(10).join(task_lines)}

## 来源边界

- 区域、人物、生物、物品、容器与出口来自 `V13ENT.MAP`、`VAULT13.MAP` 的结构化导出。
- 人物身份、服务、任务标题、条件与奖励来自当前有效消息和对应 INT 脚本；没有把监督者的后世姓名写成原作事实。
- 所有区域总图和人物位置图保留完整渲染画布与原始像素尺寸，没有按标签框裁切，也没有等比例缩小。
- 提可“听过那些地下避难所，但是知道不多”的说法属于人物评价，不作为地图结构来源。
"""
    (vault_dir / f"{LOCATION}.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    configure_helpers()
    vault = args.vault_root.resolve()
    vault_dir = vault / "地点" / LOCATION
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    homepage_attachments = vault_dir / "attachments"
    homepage_attachments.mkdir(exist_ok=True)
    poster(homepage_attachments / "Vault 13 13号避难所城镇海报（区域标注）.jpg")
    region_people, region_creatures, region_objects, titles = {}, {}, {}, {}
    evidence = {
        "location": "Vault 13", "source_maps": ["V13ENT.MAP", "VAULT13.MAP"],
        "town_poster": "TWNMAP00.FRM", "poster_label_basis": "visual anchors, not engine hotspot coordinates",
        "world_map": {"grid": [16, 1], "pixel": [825, 75], "discovery_variable": 67},
        "maps": [], "character_notes": 0, "creature_objects": 0,
        "character_topic_notes": 0, "character_topic_rows": 0,
        "task_pages": [task["filename"] for task in TASKS],
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
        creatures = [obj for obj in critters if script_stem(obj) in CREATURE_SCRIPTS]
        people = [obj for obj in critters if script_stem(obj) not in CREATURE_SCRIPTS]
        region_people[region.title], region_creatures[region.title], region_objects[region.title] = people, creatures, (objects, lookup)
        render_root = REPO / "workspace/output/maps-rendered" / region.map_name
        src_map = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png"
        target_map = attachments / f"{region.title}地图（人物与物品标注，完整原始画布）.png"
        shutil.copyfile(src_map, target_map)
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
            text, title, named = bone.character_note(vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages,
                                                      critter_messages, note_index, maps[oid], sprite_name, f"{frm_stem}.FRM", people_attachments)
            text = text.replace("Boneyard 晒骨场", LOCATION).replace("tags: [辐射1, 人物, 地点, 晒骨场]", "tags: [辐射1, 人物, 地点, 13号避难所]")
            text = text.replace("地点/Boneyard 晒骨场/", "地点/Vault 13 13号避难所/")
            text = text.replace("[[Vault 13 13号避难所\\|晒骨场]]", "[[Vault 13 13号避难所\\|13号避难所]]")
            text = text.replace("\n\n## 对话头像\n\n人物脚本和人物原型没有提供可确认的独立 HEADS 对话头像。", "")
            topics = topic_records(REPO, script_stem(obj))
            if topics:
                evidence["character_topic_notes"] += 1
                evidence["character_topic_rows"] += len(topics)
            full_title = f"{LOCATION} - {title}"
            target = (named_dir if named else generic_dir) / f"{full_title}.md"
            if target.exists() and not args.overwrite:
                raise FileExistsError(target)
            target.write_text(text, encoding="utf-8")
            titles[key(region, obj)] = full_title
        top_items = [obj for obj in objects if obj.get("prototype", {}).get("type") == "item" and int(obj.get("tile", -1)) >= 0]
        evidence["maps"].append({
            "map": region.map_name, "elevation": region.elevation, "region": region.title,
            "canvas": [Image.open(src_map).width, Image.open(src_map).height], "range_strategy": "full render canvas",
            "people": len(people), "named_people": sum(int(obj["object_id"]) in NAMED for obj in people),
            "generic_people": sum(int(obj["object_id"]) not in NAMED for obj in people), "creatures": len(creatures),
            "objects": len(objects), "top_level_items": len(top_items),
            "containers": sum(obj.get("prototype", {}).get("subtype_name") == "container" for obj in top_items),
            "render": str(src_map.relative_to(REPO)),
        })
        evidence["character_notes"] += len(people)
        evidence["creature_objects"] += len(creatures)
    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        write_region_page(vault_dir, region, region_people[region.title], region_creatures[region.title], objects,
                          lookup, item_messages, note_index, titles)
    write_tasks(vault_dir)
    write_home(vault_dir, region_people, region_creatures, region_objects, titles, item_messages, note_index)
    for markdown in vault_dir.rglob("*.md"):
        lines = markdown.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.startswith("|"):
                lines[index] = re.sub(r"\[\[([^]\n]*?)(?<!\\)\|", r"[[\1\\|", line)
        markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sync_tree(vault_dir, REPO)
    evidence_path = REPO / "workspace/output/maps-knowledge/vault13-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated Vault 13 package: {len(REGIONS)} regions, {evidence['character_notes']} character notes, {evidence['creature_objects']} creature objects, {len(TASKS)} task pages")


if __name__ == "__main__":
    main()
