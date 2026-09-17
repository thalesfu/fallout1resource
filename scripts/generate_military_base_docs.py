#!/usr/bin/env python3
"""Generate the complete Fallout 1 Military Base location package for Obsidian."""

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
LOCATION = "Military Base 军事基地"


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bone = import_script("military_base_boneyard_helpers", "generate_boneyard_docs.py")
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
    Region("Entrance 入口", "Entrance", "入口", "MBENT", 0, 30,
           "世界地图和城镇海报都只把玩家送到这张地表入口图。铁丝网、警戒门和基地建筑构成可见边界；超级变种人与夜行团守住入口，三名兄弟会资深游侠是支援进攻时使用的条件性对象。",
           (("无线电欺骗与安全控制", "入口无线电", "可呼叫、误导基地指挥部，并在满足条件时改变力场设定或触发警报。"),)),
    Region("Stronghold Level 1 第一区", "Stronghold Level 1", "第一区", "MBSTRG12", 0, 31,
           "入口之后的第一层要塞走廊。地图中可以看到多组力场、控制台、警报器、机器人和变种人战斗小队；中央控制计算机可以改变本层力场状态。",
           (("力场控制", "中央控制计算机", "通过计算机或与无线电配合，可尝试关闭本层全部或部分力场。"),)),
    Region("Stronghold Level 2 第二区", "Stronghold Level 2", "第二区", "MBSTRG12", 1, 31,
           "要塞第二层由宿舍、储藏间、走廊和力场分区组成。静态地图保存大量锁柜、床底锁箱、武装变种人与圆顶机器人；阿贝尔位于力场隔开的区域。"),
    Region("Vats Level 1 第三区", "Vats Level 1", "第三区", "MBVATS12", 0, 32,
           "病毒槽区第一层包含牢房、守卫区、储物柜和损坏的电梯。弗里普看守并引导俘虏，莎拉等待所谓的“浸泡”；牢房守卫的台词直接说明囚犯会在浸泡前被关在这里。"),
    Region("Vats Level 2 第四区", "Vats Level 2", "第四区", "MBVATS12", 1, 32,
           "基地最深处集中病毒槽控制室、医疗记录、FEV 技师、变种人副官及其护卫。病毒槽控制计算机保存日志、安全码与多种自毁序列；可修复的 462 号单位会前往控制室执行清理任务。",
           (("基地档案与自毁控制", "病毒槽控制计算机", "读取日志、访问医疗系统、设置警戒并在取得权限后启动不同倒计时的自毁序列。"),
            ("机器人修复", "462号单位", "修复并重新启动后，机器人会继续其控制室清理任务。"))),
    Region("Destroyed Base 毁坏基地", "Destroyed Base", "毁坏基地", "MBDEAD", 0, 48,
           "基地自毁后的替代地表地图。它与正常入口使用相同的完整画布范围，但建筑已坍塌为弹坑；导出对象中没有人物、地面物品或容器。"),
)


NAMED = {
    3860: ("Abel", "阿贝尔", "观察文字和自称都直接给出姓名；他是要塞第二层的超级变种人。"),
    2861: ("Flip", "弗里普", "观察文字与莎拉台词直接给出姓名；他负责看守和押送俘虏。"),
    3102: ("Sarah", "莎拉", "对话动作文字直接给出姓名；她自称愿意接受浸泡，并把弗里普称为爱人。"),
    2877: ("Van Haggen", "范·海根", "偷听对话直接称呼范·海根；他向大教堂来使汇报原料短缺。"),
    4045: ("Unit 462", "462号单位", "机器人自检台词直接报告编号 462；修复后继续执行控制室清理任务。"),
}


SCRIPT_ROLES = {
    "VFENCEMT": ("Perimeter Guard", "外围栅栏守卫", "入口外围的超级变种人守卫。"),
    "VPLOTMUT": ("Parking-Lot Nightkin", "停车场夜行团", "入口停车场的夜行团守卫。"),
    "VDOORMUT": ("Entrance Door Guard", "入口门卫", "基地入口门旁的夜行团守卫。"),
    "VGATEMUT": ("Entrance Gate Guard", "入口栅门守卫", "基地外栅门的超级变种人守卫。"),
    "BROINVAD": ("Brotherhood Assault Paladin", "兄弟会突击游侠", "兄弟会支援进攻时使用的条件性资深游侠对象。"),
    "CHOCTECH": ("Cathedral Technician", "大教堂教徒技师", "在病毒槽区工作的普通大教堂教徒技师。"),
    "KRUPPER": ("Cell Guard", "牢房守卫", "负责病毒槽牢房；脚本文件名不是可见姓名，因此归入普通人物。"),
    "LT": ("Lieutenant", "副官", "主宰军队的副官；素材只确认职务，没有提供个人姓名。"),
    "LTGUARD": ("Lieutenant's Guard", "副官护卫", "负责副官身边警戒的夜行团护卫。"),
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
    oid = int(obj["object_id"])
    if oid in NAMED:
        en, zh, note = NAMED[oid]
        return en, zh, note, True
    stem = script_stem(obj)
    if stem in SCRIPT_ROLES:
        en, zh, note = SCRIPT_ROLES[stem]
        return en, zh, note, False
    if not proto_en and not proto_zh:
        proto_en, proto_zh = PROFILE_IDENTITIES[int(obj["object_id"])]
    role = {
        "MRHANDYA": "基地防御或维护用圆顶机器人。",
        "MRHANDYB": "基地防御或维护用圆顶机器人。",
        "POWERMUT": "把守动力控制区域的超级变种人。",
        "COMPTROL": "把守控制室的夜行团。",
        "GENSUPR": "基地内部的超级变种人警卫。",
    }.get(stem, "基地静态地图保存的武装成员；个人姓名未由素材确认。")
    return proto_en, proto_zh, role, False


def short_title(title: str) -> str:
    return title.removeprefix(f"{LOCATION} - ").split("（ID", 1)[0].strip()


def key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def task_association(region: Region, oid: int) -> str:
    if oid == 2883:
        return "# 任务关联\n\n副官是“毁灭变种人的源头”在基地内的主要对抗与情报节点；最初发起人是[[Vault 13 13号避难所|13号避难所]]监督者，不在本地点包内。"
    if oid == 2877:
        return "# 任务关联\n\n范·海根与大教堂来使的谈话会泄露针对 13 号避难所的计划，是主线威胁的情报节点；他不是该任务的发起人。"
    if oid == 4045:
        return "# 任务关联\n\n修复 462 号单位可让它前往病毒槽控制室执行清理；这是基地内部支线互动，不是独立 Pip-Boy 任务。"
    return ""


def configure_helpers() -> None:
    bone.NAMED = NAMED
    bone.SCRIPT_ROLES = SCRIPT_ROLES
    bone.identity = identity
    bone.short_title = short_title
    bone.task_association = task_association
    bb.HEADS = {"LT": "LIEUT"}


def poster(output: Path) -> None:
    source_path = REPO / "workspace/output/images/master/ART/INTRFACE/TWNMAP08.frm/TWNMAP08.frm.frames/sequence-00/frame-000.png"
    source = Image.open(source_path).convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (18, 18, 16, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 22)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((700, 38), LOCATION, font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP08.FRM · 原作蓝图与唯一城镇热点", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale = 1.72
    left, top = 310, 92
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    draw.rounded_rectangle((left - 10, top - 10, left + scaled.width + 10, top + scaled.height + 10), radius=18, fill=(7, 7, 6), outline=(89, 70, 46), width=5)
    canvas.alpha_composite(scaled, (left, top))
    px, py = left + 197 * scale, top + 83 * scale
    bx, by, bw, bh = 45, 180, 260, 104
    draw.line((px, py, (px + bx + bw) / 2, by + bh / 2, bx + bw, by + bh / 2), fill=(224, 180, 91), width=3)
    draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
    draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
    draw.text((bx + 16, by + 17), "Entrance 入口", font=label_font, fill=(248, 232, 188))
    draw.text((bx + 16, by + 55), "MBENT · e0", font=meta_font, fill=(205, 185, 139))
    draw.text((bx + 16, by + 78), "引擎热点 (197, 83)", font=meta_font, fill=(205, 185, 139))
    notes = ["内部楼层（非城镇热点）", "Stronghold Level 1 / 第一区", "Stronghold Level 2 / 第二区", "Vats Level 1 / 第三区", "Vats Level 2 / 第四区"]
    draw.rounded_rectangle((1065, 210, 1370, 405), radius=12, fill=(38, 30, 23, 240), outline=(111, 91, 55), width=2)
    for index, line in enumerate(notes):
        draw.text((1085, 230 + index * 36), line, font=label_font if index == 0 else meta_font, fill=(248, 232, 188) if index == 0 else (205, 185, 139))
    draw.text((700, 866), "城镇选择界面仅入口可点击；其他楼层由基地内部通道连接", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def item_entries(region: Region, people: list[dict], objects: list[dict], lookup: dict,
                 item_messages: dict, note_index: dict, titles: dict) -> tuple[list[tuple], list[tuple], list[tuple]]:
    region_items, homepage_items, containers = [], [], []
    for obj in people:
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
    text = text.replace("tags: [辐射1, 人物, 地点, 晒骨场]", "tags: [辐射1, 人物, 地点, 军事基地]")
    text = text.replace("[[Military Base 军事基地\\|晒骨场]]", "[[Military Base 军事基地\\|军事基地]]")
    text = text.replace("\n\n## 对话头像\n\n人物脚本和人物原型没有提供可确认的独立 HEADS 对话头像。", "")
    return text, title, named


def write_region_page(vault_dir: Path, region: Region, people: list[dict], objects: list[dict], lookup: dict,
                      item_messages: dict, note_index: dict, titles: dict) -> None:
    named_rows, generic_rows = [], []
    for index, obj in enumerate(sorted(people, key=lambda o: int(o["object_id"])), 1):
        oid = int(obj["object_id"])
        title = titles[key(region, obj)]
        _, _, role, named = identity(obj, "", "")
        row = f"| {index} | {oid} | [[{title}\\|{short_title(title)}]] | {role} |"
        (named_rows if named else generic_rows).append(row)
    region_items, _, containers = item_entries(region, people, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {qty} |" for kind, name, owner, qty in sorted(region_items)]
    container_rows = [f"| {region.title} | {name} | {contents} |" for name, contents in containers]
    service_rows = [f"| {service} | {provider} | {content} |" for service, provider, content in region.services]
    task_note = ("这是 Pip-Boy 任务“毁灭变种人的源头”的目标地点；任务最初由 13 号避难所监督者发起。启动病毒槽控制计算机的自毁序列并逃离基地，可使世界地图切换到毁坏状态。"
                 if region.map_name != "MBDEAD" else "这里是“毁灭变种人的源头”完成后的地点状态，不是新的任务发起区域。")
    page = rf'''---
title: "{region.title}"
aliases:
  - "{region.english}"
  - "{region.chinese}"
tags: [辐射1, 地点, 军事基地]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[Military Base 军事基地\|Military Base 军事基地]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

## 地图

![[{region.title}地图（人物与物品标注，完整原始画布）.png|900]]

绿色轮廓与标签表示人物，黄色轮廓与标签表示地面物品和容器。图片保留渲染器完整原始画布及原始像素尺寸，不按人物标签裁切，也不缩放；它是 MAP 保存状态的静态快照。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(service_rows) if service_rows else '| — | — | 完整脚本与对象清点没有确认面向玩家开放的交易或常规服务。 |'}

## 人物

### 专名人物

| 序号 | 地图对象 ID | 人物 | 身份或作用 |
|---:|---:|---|---|
{chr(10).join(named_rows) if named_rows else '| — | — | — | 本区域没有由素材确认个人姓名的地图人物。 |'}

### 普通人物

| 序号 | 地图对象 ID | 人物 | 身份或作用 |
|---:|---:|---|---|
{chr(10).join(generic_rows) if generic_rows else '| — | — | — | 本区域没有普通人物对象。 |'}

## 物品

下表只列人物随身库存和地图地面物品；容器及其直接库存单列。静态库存不等同于任意剧情时刻的实时状态。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows) if item_rows else '| — | — | — | 本区域没有人物库存或地面物品。 |'}

## 容器

| 区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows) if container_rows else f'| {region.title} | — | 本区域没有容器对象。 |'}

## 任务

| 任务名 | 任务链上第一个发起人 | 发起人所在区域 | 本区域中的环节 |
|---|---|---|---|
| 毁灭变种人的源头 | 13号避难所监督者 | [[Vault 13 13号避难所\|13号避难所]] | {task_note} |
'''
    (vault_dir / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_home(vault_dir: Path, region_people: dict, region_objects: dict, titles: dict,
               item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, item_rows, container_rows = [], [], [], [], []
    total_people = 0
    for region in REGIONS:
        people = region_people[region.title]
        total_people += len(people)
        region_rows.append(f"| [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` / e{region.elevation} | {'替代状态图' if region.map_name == 'MBDEAD' else '地表区域' if region.map_name == 'MBENT' else '地下层'} | {len(people)} | {region.description.split('。')[0]}。 |")
        for obj in sorted(people, key=lambda o: int(o["object_id"])):
            oid, title = int(obj["object_id"]), titles[key(region, obj)]
            _, _, _, named = identity(obj, "", "")
            row = f"| [[{region.title}\\|{region.chinese}]] | {oid} | [[{title}\\|{short_title(title)}]] |"
            (named_rows if named else generic_rows).append(row)
        objects, lookup = region_objects[region.title]
        _, home_items, containers = item_entries(region, people, objects, lookup, item_messages, note_index, titles)
        item_rows.extend(f"| {kind} | {name} | [[{region.title}]] | {owner} | {qty} |" for kind, name, owner, qty, _ in home_items)
        container_rows.extend(f"| [[{region.title}]] | {name} | {contents} |" for name, contents in containers)
    page = rf'''---
title: "Military Base 军事基地"
aliases:
  - "Military Base"
  - "Mariposa Military Base"
  - "Mariposa Military Base 迈瑞普斯军事基地"
  - "迈瑞普斯军事基地"
  - "军事基地"
tags: [辐射1, 地点, 军事基地]
world_map_grid: "3,1"
world_map_pixel: "175,75"
---

# Military Base 军事基地

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图与 Pip-Boy 地点分类 | Military Base / 军事基地 |
| Pip-Boy 历史资料 | Mariposa Military Base / 迈瑞普斯军事基地 |
| 城镇海报 | 军事设施蓝图；资源为 `TWNMAP08.FRM` |
| 知识库标题 | Military Base 军事基地 |
| 资源地图组 | `MBENT.MAP`、`MBSTRG12.MAP`、`MBVATS12.MAP`、`MBDEAD.MAP` |

## 地点概览

军事基地位于世界地图西北部，是超级变种人生产与集结设施。正常状态由地表入口、两层要塞和两层病毒槽区组成；基地自毁后，世界地图访问会改载独立的 `MBDEAD.MAP` 弹坑状态。`MSTRLR12` 与 `MSTRLR34` 的 “Lair Level” 属于大教堂下方主宰巢穴，不在本地点包内。

[[Hub 哈勃城 - Harold 哈罗德（ID 1633）|哈罗德]]称他的队伍曾找到西北方的一座旧军事基地，并把其中的大量变种人视作来源线索。日记中的提可只说军方有秘密基地散布各地且不知道具体位置；这条人物说法保留其不确定性，不单独用来指认本基地。

## 世界地图位置

引擎城镇坐标表把军事基地放在网格 `(3, 1)`；知识库世界地图对应像素锚点约为 `(175, 75)`。总览另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[Military Base 军事基地城镇地图（入口热点标注）.jpg|900]]

海报原图是 `TWNMAP08.FRM`。引擎城镇热点表只提供入口一个按钮，坐标为 `(197, 83)`，进入 `MBENT.MAP`；第一区至第四区通过基地内部通道到达，不是四个额外城镇热点。

## 城市分区

| 英文名称 | 中文名称 |
|---|---|
| [[Entrance 入口\|Entrance]] | [[Entrance 入口\|入口]] |
| [[Stronghold Level 1 第一区\|Stronghold Level 1]] | [[Stronghold Level 1 第一区\|第一区]] |
| [[Stronghold Level 2 第二区\|Stronghold Level 2]] | [[Stronghold Level 2 第二区\|第二区]] |
| [[Vats Level 1 第三区\|Vats Level 1]] | [[Vats Level 1 第三区\|第三区]] |
| [[Vats Level 2 第四区\|Vats Level 2]] | [[Vats Level 2 第四区\|第四区]] |
| [[Destroyed Base 毁坏基地\|Destroyed Base]] | [[Destroyed Base 毁坏基地\|毁坏基地]] |

## 区域与楼层

| 区域与楼层 | 资源地图 / elevation | 类型 | 人物数 | 进入方式或关系 |
|---|---|---|---:|---|
{chr(10).join(region_rows)}

## 商店和服务

基地没有正常商店。可操作设施包括入口无线电、第一区力场控制计算机、第四区病毒槽控制计算机，以及可修复的[[{titles.get(('MBVATS12', 1, 4045), 'Military Base 军事基地 - Unit 462 462号单位（ID 4045）')}|462号单位]]；具体条件在对应区域页和人物页展开。

## 地图中的人物

完整静态对象清点得到 {total_people} 名人物或机器人对象。超级变种人、夜行团、教徒、兄弟会条件性突击队员与具有脚本互动的机器人均按人物对象逐一建页；本地点没有需要从人物表中另行剥离的动物或非人物生物。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_rows)}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows)}

## 地图中的物品

下表汇总人物随身库存、地面物品和容器直接库存；每行只表示一种物品。数据来自 MAP 保存状态，不等同于任意剧情时刻的实时库存。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(sorted(item_rows))}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 | 经过区域 | 简短目标 |
|---|---|---|---|---|
| 毁灭变种人的源头 | 13号避难所监督者 | [[Vault 13 13号避难所\|13号避难所]] | 入口、第一区、第二区、第三区、第四区 | 找到变种人生产设施并毁灭其源头；基地内可通过病毒槽控制计算机启动自毁。 |

任务标题来自 `PIPBOY.MSG` 的 703 号有效消息。由于最初发起人在 13 号避难所，本包不把任务页错误地放到军事基地某一层；基地各区域页只记录本地环节。

## 来源边界

- 地点坐标、热点、地图编号和区域名称来自引擎城镇表、`MAP.MSG`、`WORLDMAP.MSG` 与结构化 MAP。
- 人物、物品、容器和楼层来自四张 MAP 的完整对象清点；人物身份与设施功能来自对应 INT 脚本和当前中文消息资源。
- 所有区域总图与人物位置图保留完整渲染画布和原始像素尺寸；没有按标签框裁切，也没有缩放。
- `MBDEAD.MAP` 是基地自毁后的替代状态；它不是第五层，也不与正常入口对象合并统计。
'''
    (vault_dir / f"{LOCATION}.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    configure_helpers()
    vault = args.vault_root.resolve()
    vault_dir = vault / f"地点/{LOCATION}"
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    homepage_attachments = vault_dir / "attachments"
    homepage_attachments.mkdir(exist_ok=True)
    poster(homepage_attachments / "Military Base 军事基地城镇地图（入口热点标注）.jpg")
    region_people, region_objects, titles = {}, {}, {}
    evidence = {"location": "Military Base", "source_maps": ["MBENT.MAP", "MBSTRG12.MAP", "MBVATS12.MAP", "MBDEAD.MAP"],
                "town_poster": "TWNMAP08.FRM", "world_map": {"grid": [3, 1], "pixel": [175, 75]},
                "maps": [], "character_notes": 0, "task_pages": [], "quest_target": "PIPBOY.MSG 703"}
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
        objects = [o for o in map_doc["objects"]["entries"] if int(o.get("elevation_group", -1)) == region.elevation]
        people = [o for o in objects if o.get("prototype", {}).get("type") == "critter" and int(o.get("tile", -1)) >= 0]
        for obj in people:
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            PROFILE_IDENTITIES[int(obj["object_id"])] = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
        region_people[region.title] = people
        region_objects[region.title] = (objects, lookup)
        render_root = REPO / "workspace/output/maps-rendered" / region.map_name
        if people:
            src_map = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png"
        else:
            src_map = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items.png"
        map_name = f"{region.title}地图（人物与物品标注，完整原始画布）.png"
        shutil.copyfile(src_map, attachments / map_name)
        maps = bone.profile_maps(region, people, people_attachments) if people else {}
        for obj in people:
            stale = people_attachments / f"{region.title}地图（人物标注，  ID {obj['object_id']}高亮，完整原始画布）.png"
            if stale.exists():
                stale.unlink()
        render_doc = (load_json(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json") if people else {})
        render_by_id = {int(o["object_id"]): o for o in render_doc.get("critters", []) + render_doc.get("missing_critter_art", [])}
        for obj in people:
            oid = int(obj["object_id"])
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            proto_en, proto_zh = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
            en, zh, _, named = identity(obj, proto_en, proto_zh)
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
        top_items = [o for o in objects if o.get("prototype", {}).get("type") == "item" and int(o.get("tile", -1)) >= 0]
        evidence["maps"].append({"map": region.map_name, "elevation": region.elevation, "region": region.title,
                                 "people": len(people), "named_people": sum(int(o["object_id"]) in NAMED for o in people),
                                 "objects": len(objects), "top_level_items": len(top_items),
                                 "containers": sum(o.get("prototype", {}).get("subtype_name") == "container" for o in top_items),
                                 "render": str(src_map.relative_to(REPO))})
        evidence["character_notes"] += len(people)
    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        write_region_page(vault_dir, region, region_people[region.title], objects, lookup, item_messages, note_index, titles)
    write_home(vault_dir, region_people, region_objects, titles, item_messages, note_index)
    sync_tree(vault_dir, REPO)
    evidence_path = REPO / "workspace/output/maps-knowledge/military-base-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated Military Base package: {len(REGIONS)} regions, {evidence['character_notes']} character notes")


if __name__ == "__main__":
    main()
