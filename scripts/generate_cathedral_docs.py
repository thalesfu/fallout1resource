#!/usr/bin/env python3
"""Generate the complete Fallout 1 Cathedral location package for Obsidian."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import sys
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from fallout1_character_topics import render_topic_section, sync_tree, topic_records


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("brotherhood_helpers", REPO / "scripts/generate_brotherhood_docs.py")
bb = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = bb
SPEC.loader.exec_module(bb)

GREEN = (101, 231, 101, 255)
ORANGE = (255, 126, 48, 255)


Region = bb.Region
REGIONS = (
    Region(
        "Entrance 入口", "Entrance", "入口", "CHILDRN1", 0, 17,
        "大教堂入口涵盖教堂前广场、废墟街道与正门外侧。卡尔德、扎克、传教者及条件性突袭队对象分布在这里；楼内入口通向塔楼一层。",
    ),
    Region(
        "Tower Level 1 塔楼一层", "Tower Level 1", "塔楼一层", "CHILDRN1", 1, 17,
        "塔楼一层是大教堂公开活动的核心区域，包含礼拜空间、诊疗房间、交易点、居住区和通往上层的楼梯。拉舍尔神父、劳拉、吴医生及多名教徒在此。",
        (("物资交易", "Cathedral Shopkeeper 大教堂店主", "提供脚本控制的以物易物；敌对、持械或偷窃状态会改变接待。"),
         ("诊疗与药物", "Doctor Wu 吴医生", "提供带有欺骗和风险分支的诊疗互动，不能视为可靠医院服务。"),
         ("内部引导", "Laura 劳拉", "在相关调查状态下介绍大教堂并协助接近上层。")),
    ),
    Region(
        "Tower Level 2 塔楼二层", "Tower Level 2", "塔楼二层", "CHILDRN2", 0, 18,
        "塔楼二层是一段狭长的上层通道。达恩和两名夜行者守卫驻留于此，楼梯继续通往更高楼层。",
    ),
    Region(
        "Tower Level 3 塔楼三层", "Tower Level 3", "塔楼三层", "CHILDRN2", 1, 18,
        "塔楼三层由夜行者守卫、寝具和多个储物容器构成，是进入顶层前的守卫区。",
    ),
    Region(
        "Tower Level 4 塔楼四层", "Tower Level 4", "塔楼四层", "CHILDRN2", 2, 18,
        "塔楼四层是墨菲斯的房间。三名强化夜行者守卫围绕顶层活动；墨菲斯掌握进入大教堂地下设施的关键线索。",
    ),
    Region(
        "Destroyed Cathedral 毁坏大教堂", "Destroyed Cathedral", "毁坏大教堂", "CHILDEAD", 0, 47,
        "毁坏大教堂是核爆后使用的替代地图状态。导出资源只保留地面、弹坑与少量残墙，没有人物、地面物品、容器、门或可见场景物件。",
    ),
)


NAMED = {
    1327: ("Calder", "卡尔德", "少年卡尔德；其对话围绕大教堂毁灭后的幸存与复仇，因此属于脚本条件控制的特殊对象。"),
    1522: ("Zark", "扎克", "大教堂入口的暴徒扎克；脚本直接使用 Zark 作为人物名。"),
    118: ("Sasha", "萨舍", "塔楼一层人物；姓名直接来自人物原型，地图对象没有独立人物脚本。"),
    416: ("Father Lasher", "拉舍尔神父", "大教堂神职人员，负责公开教务并看守上层通行。"),
    561: ("Sister Francis", "弗朗西斯修女", "在塔楼一层祈祷的大教堂修女。"),
    566: ("Barracus", "贝瑞卡斯", "体格高大的大教堂教徒；人物原型和脚本名为 Barracus，中文观察文字称其为“唐”。"),
    1301: ("Doctor Wu", "吴医生", "大教堂内的医生；诊疗脚本包含欺骗、毒药与真实治疗等不同分支。"),
    1527: ("Laura", "劳拉", "渗透大教堂的天启追随者成员；在相关调查状态下提供内部引导。"),
    1975: ("Viola", "维奥拉", "塔楼一层的女性教徒；姓名来自人物脚本。"),
    543: ("Dane", "达恩", "塔楼二层的高大男子，精神状态混乱；脚本自称达恩。"),
    673: ("Morpheus", "墨菲斯", "大教堂领袖之一，位于塔楼顶层，并与主宰的地下设施相连。"),
}


SCRIPT_ROLES = {
    "FOLINVAD": ("Followers Strike Team", "天启追随者突袭队", "由天启追随者支援条件控制的突袭队员，不是大教堂常驻教徒。"),
    "CHANTER": ("Cathedral Preacher", "大教堂牧师", "在入口或礼拜区宣讲主教教义的牧师。"),
    "SLUMMER": ("Strange Preacher", "怪异传教士", "入口附近的传教者；资源没有提供可确认的个人姓名。"),
    "CHIDGAB": ("Hostile Cathedral Follower", "脾气恶劣的教徒", "态度敌对的大教堂教徒。"),
    "BROINVAD": ("Brotherhood Paladin", "钢铁兄弟会游侠", "由钢铁兄弟会支援条件控制的突袭队员，不是大教堂常驻人物。"),
    "CHIDNITE": ("Nightkin Guard", "夜行者守卫", "负责塔楼上层警戒的夜行者。"),
    "CATHSHOP": ("Cathedral Shopkeeper", "大教堂店主", "塔楼一层交易点的店主；资源没有提供个人姓名。"),
    "GENCHANT": ("Cathedral Chanter", "大教堂吟诵者", "塔楼一层的吟诵者；资源没有提供个人姓名。"),
}


bb.HEADS = {"LAURA": "LAURA", "MORPH": "MORPH"}


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
    return proto_en, proto_zh, f"人物原型分类为 {proto_en} / {proto_zh}；资源没有提供可确认的个人姓名。", False


def short_title(title: str) -> str:
    return title.removeprefix("Cathedral 大教堂 - ").split("（ID", 1)[0].strip()


def region_for(map_name: str, elevation: int) -> Region:
    return next(r for r in REGIONS if r.map_name == map_name and r.elevation == elevation)


def reachable_dialogue(repo: Path, obj: dict) -> str:
    stem = script_stem(obj)
    csv_path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{stem}.messages.csv"
    json_path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{stem}.json"
    if not stem or not csv_path.exists() or not json_path.exists():
        return ""
    script_doc = load_json(json_path)
    procedures = script_doc.get("procedures", [])
    by_index = {int(p["index"]): p for p in procedures}
    by_name = {p["name"].casefold(): int(p["index"]) for p in procedures}
    entry_label = "talk_p_proc"
    start = by_name.get(entry_label)
    if start is None:
        entry_label = "do_dialogue"
        start = by_name.get(entry_label)
    if start is None:
        # Several early Fallout scripts dispatch every script action from a
        # single `start` procedure instead of exporting talk_p_proc by name.
        entry_label = "start"
        start = by_name.get(entry_label)
    if start is None:
        return ""
    graph: dict[int, set[int]] = defaultdict(set)
    for proc in procedures:
        instructions = proc.get("instructions", [])
        for index, instruction in enumerate(instructions):
            if instruction.get("mnemonic") != "call":
                continue
            for previous in reversed(instructions[max(0, index - 12):index]):
                if previous.get("mnemonic") == "push_int":
                    target = previous.get("argument")
                    if isinstance(target, int) and target in by_index:
                        graph[int(proc["index"])].add(target)
                    break
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    # Player options are dynamic procedure edges encoded in the message-link
    # table rather than ordinary VM `call` instructions.
    for row in rows:
        source = by_name.get(row.get("procedure_name", "").casefold())
        target = by_name.get(row.get("target_procedure_name", "").casefold())
        if source is not None and target is not None:
            graph[source].add(target)
    reachable, queue = {start}, deque([start])
    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    visible_by_proc: dict[str, list[dict]] = defaultdict(list)
    proc_order = []
    for row in rows:
        name = row["procedure_name"]
        index = by_name.get(name.casefold())
        if not row.get("msg_text"):
            continue
        if index in reachable and name not in visible_by_proc:
            proc_order.append(name)
        if index in reachable:
            visible_by_proc[name].append(row)
    orphan_names = []
    for row in rows:
        name = row["procedure_name"]
        index = by_name.get(name.casefold())
        if row.get("msg_text") and index not in reachable and name not in {"start", "look_at_p_proc", "description_p_proc"} and name not in orphan_names:
            orphan_names.append(name)
    if not proc_order:
        return ""
    heading_names = {name.casefold() for name in proc_order}
    lines = [
        "# 对话", "",
        f"以下从 `{stem}.INT` 的交谈分派入口 `{entry_label}` 出发，按过程调用与玩家选项目标追踪可达分支。实际进入哪条路线仍由剧情变量、反应值、性别、智力、装备与战斗状态决定。",
    ]
    for name in proc_order:
        current = visible_by_proc[name]
        npc, options = [], []
        for row in current:
            text = bb.md(row["msg_text"])
            if row["call"] in {"reply", "message", "message_lookup"} and text not in npc:
                npc.append(text)
            elif row["call"] in {"intelligence_option", "option"}:
                requirement = f"智力 {row['intelligence']}" if row.get("intelligence") else "选项"
                target = row.get("target_procedure_name") or "结束对话"
                target_display = f"[[#{target}]]" if target.casefold() in heading_names else f"`{target}`"
                options.append(f"`{requirement}`：{text} → {target_display}")
        title = npc[0][:36] + ("……" if npc and len(npc[0]) > 36 else "") if npc else f"过程 {name}"
        lines.extend(["", f"## {name}", "", f"> [!quote]- {title}"])
        if npc:
            lines.extend(["> **人物台词**", ">"] + [f"> - {text}" for text in npc])
        if options:
            lines.extend([">", "> **玩家选项与下一过程**", ">"] + [f"> - {text}" for text in options])
        else:
            lines.extend([">", "> **流程说明**", ">", "> - 本过程没有列出玩家选项，后续由脚本状态或控制过程处理。"])
    if orphan_names:
        lines.extend([
            "", f"## 未由 {entry_label} 触达的可见过程（审计）", "",
            f"下列过程在脚本消息关联表中带有可见文字，但当前静态调用图没有从 `{entry_label}` 追踪到它们；它们不并入上面的正常对话正文：",
            "", ", ".join(f"`{name}`" for name in orphan_names) + "。",
        ])
    return "\n".join(lines)


def character_observation(repo: Path, obj: dict, proto: dict, critter_messages: dict) -> str:
    """Read both standard look_at_p_proc and legacy start-procedure look text."""
    stem = script_stem(obj)
    path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{stem}.messages.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        standard = next((row["msg_text"] for row in rows
                         if row["procedure_name"] in {"look_at_p_proc", "description_p_proc"} and row.get("msg_text")), None)
        if standard:
            return standard
        legacy = next((row["msg_text"] for row in rows
                       if row["procedure_name"] == "start" and row.get("message_number") == "100" and row.get("msg_text")), None)
        if legacy:
            return legacy
    return bb.observation(repo, obj, proto, critter_messages)


def profile_maps(repo: Path, region: Region, characters: list[dict], attachments: Path) -> dict[int, str]:
    render_root = repo / "workspace/output/maps-rendered" / region.map_name
    prefix = f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters"
    render_doc = load_json(render_root / f"{prefix}.json")
    labels = render_doc["critter_name_labels"]["labels"]
    composite = Image.open(render_root / f"{prefix}.png").convert("RGBA")
    critters = Image.open(render_root / f"elevation-{region.elevation}-critters.png").convert("RGBA")
    alpha = critters.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(5))
    base = Image.composite(Image.new("RGBA", composite.size, GREEN), composite, ImageChops.subtract(expanded, alpha))
    crop_doc = load_json(render_root / f"elevation-{region.elevation}-cathedral-region-cropped.json")
    crop_box = tuple(int(v) for v in crop_doc["crop_box"])
    scale = float(crop_doc.get("scale", 1.0))
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 28)
    output = {}
    for obj in characters:
        oid = int(obj["object_id"])
        own = next(label for label in labels if int(label["object_id"]) == oid)
        canvas = base.copy()
        target = tuple(int(v) for v in own["target_canvas"])
        if not own.get("missing_art"):
            component = bb.nearest_component(alpha, target)
            if component is not None:
                outline = ImageChops.subtract(component.filter(ImageFilter.MaxFilter(7)), component)
                canvas = Image.composite(Image.new("RGBA", canvas.size, ORANGE), canvas, outline)
        draw = ImageDraw.Draw(canvas, "RGBA")
        for label in labels:
            current = int(label["object_id"])
            color = ORANGE if current == oid else GREEN
            tx, ty = (int(v) for v in label["target_canvas"])
            left, top, right, bottom = (int(v) for v in label["label_box_canvas"])
            draw.line((tx, ty, (left + right) // 2, bottom if bottom <= ty else top), fill=color, width=1)
            draw.rectangle((left, top, right, bottom), fill=(0, 0, 0, 218), outline=color, width=1)
            value = label["display_name"]
            box = draw.textbbox((0, 0), value, font=font, stroke_width=1)
            x = left + max(4, (right - left - (box[2] - box[0])) // 2)
            y = top + max(2, (bottom - top - (box[3] - box[1])) // 2) - box[1]
            draw.text((x, y), value, font=font, fill="white", stroke_width=1, stroke_fill="black")
        en, zh, _, _ = identity(obj, "", "")
        filename = f"{region.title}地图（人物标注，{en} {zh} ID {oid}高亮，活动区域裁切）.png"
        cropped = canvas.crop(crop_box)
        if scale != 1.0:
            cropped = cropped.resize((round(cropped.width * scale), round(cropped.height * scale)), Image.Resampling.LANCZOS)
        cropped.save(attachments / filename, format="PNG", compress_level=9)
        output[oid] = filename
    return output


def poster(repo: Path, output: Path) -> None:
    source = Image.open(repo / "workspace/output/images/master/ART/INTRFACE/TWNMAP11.frm/TWNMAP11.frm.frames/sequence-00/frame-000.png").convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (21, 18, 15, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 23)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((700, 38), "Cathedral 大教堂", font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP11.FRM · 正常状态五个区域的视觉定位", font=meta_font, fill=(189, 169, 124), anchor="mm")
    draw.rounded_rectangle((328, 90, 1072, 818), radius=18, fill=(8, 7, 6), outline=(89, 70, 46), width=5)
    scaled = source.resize((725, 710), Image.Resampling.NEAREST)
    canvas.alpha_composite(scaled, (338, 99))
    anchors = [
        ("Entrance 入口", "CHILDRN1 · elevation 0", 165, 328, 48, 650),
        ("Tower Level 1 塔楼一层", "CHILDRN1 · elevation 1", 171, 263, 48, 478),
        ("Tower Level 2 塔楼二层", "CHILDRN2 · elevation 0", 177, 213, 1082, 493),
        ("Tower Level 3 塔楼三层", "CHILDRN2 · elevation 1", 181, 166, 48, 265),
        ("Tower Level 4 塔楼四层", "CHILDRN2 · elevation 2", 184, 116, 1082, 252),
    ]
    for label, meta, sx, sy, bx, by in anchors:
        px = 338 + sx * 1.6
        py = 99 + sy * 1.6
        bw, bh = 270, 92
        edge_x = bx + bw if bx < 700 else bx
        mid_y = by + bh / 2
        draw.line((px, py, (px + edge_x) / 2, mid_y, edge_x, mid_y), fill=(224, 180, 91), width=3, joint="curve")
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
        draw.text((bx + 18, by + 19), label, font=label_font, fill=(248, 232, 188))
        draw.text((bx + 18, by + 57), meta, font=meta_font, fill=(205, 185, 139))
    draw.text((700, 861), "标注点是海报视觉锚点，不宣称为引擎按钮坐标；毁坏状态 CHILDEAD 不另占区域选择项", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def character_note(repo: Path, vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path) -> tuple[str, str, bool]:
    oid = int(obj["object_id"])
    en, zh, situation, named = identity(obj, proto_en, proto_zh)
    title = f"{en} {zh}（ID {oid}）"
    script = script_stem(obj)
    resource_line = f"resource_script: {script}.INT\n" if script else ""
    aliases = [f"Cathedral 大教堂 - {en} {zh}", f"{en} {zh}"]
    alias_lines = "\n".join(f"  - \"{value}\"" for value in aliases)
    if sprite_filename:
        sprite = f"""## 地图人物精灵

![[{sprite_filename}|160]]

该图取自 `{art_name}`，使用地图对象记录的方向 {obj['rotation']} 与第 0 帧；这是地图精灵，不是对话头像。"""
    else:
        sprite = "## 地图人物精灵\n\n资源索引指向的人物 FRM 当前没有可用导出帧，因此不借用其他人物造型。"
    sections = [f"""---
title: "{title}"
aliases:
{alias_lines}
tags: [辐射1, 人物, 地点, 大教堂]
map: {region.map_name}
elevation: {region.elevation}
map_object_id: {oid}
prototype_id: {obj['prototype']['list_index']}
map_tile: {obj['tile']}
{resource_line}---

# 名称

| 属性 | 内容 |
|---|---|
| 英文名 | {en} |
| 中文名 | {zh} |
| 全名 | {'素材或脚本直接提供姓名' if named else '普通人物类别或职务名称，不是专名'} |
| 游戏观察文字 | {bb.md(character_observation(repo, obj, proto, critter_messages))} |

# 地图信息

![[{map_filename}|900]]

橙色轮廓为本页人物，绿色轮廓为本层其他人物；同类人物通过地图对象 ID 区分。

| 属性 | 值 |
|---|---|
| 出现地点 | [[Cathedral 大教堂\\|大教堂]] |
| 所属区域 | [[地点/Cathedral 大教堂/{region.directory}/{region.title}\\|{region.title}]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | {region.elevation} |
| 地图对象 ID | {oid} |
| 人物原型 ID | {obj['prototype']['list_index']} |
| 地图格 | {obj['tile']}（{obj['tile_x']}, {obj['tile_y']}） |
| 朝向 | {obj['rotation']} |
| 人物脚本 | {f'`{script}.INT`' if script else '无独立人物脚本'} |
| 人物形象 | `{art_name}` |

# 形象

{sprite}

{bb.head_assets(repo, attachments, en, zh, script)}""",
        bb.game_data(obj, proto),
        bb.inventory_section(obj, lookup, item_messages, note_index),
    ]
    topics = topic_records(repo, script)
    if topics:
        sections.append(render_topic_section(topics))
    dialogue = reachable_dialogue(repo, obj)
    if dialogue:
        sections.append(dialogue)
    sections.append(f"# 身份与处境\n\n{situation}")
    if oid == 1527:
        sections.append("# 任务关联\n\n劳拉是天启追随者渗透大教堂的成员，并与追随者内部间谍调查的后续情报相连；该 Pip-Boy 任务的第一个发起人不在大教堂，因此本地点包不复制其任务主页。")
    if oid == 673:
        sections.append("# 主线关联\n\n墨菲斯控制通往地下设施的关键路径。击败、说服或绕过他会影响玩家接近主宰的方式；`Cathedral Destruction` 在 `PIPBOY.MSG` 中是影片档案标题，不是可接取任务名。")
    return "\n\n".join(sections).rstrip() + "\n", title, named


def item_records(region: Region, characters: list[dict], objects: list[dict], lookup: dict, item_messages: dict,
                 note_index: dict, character_titles: dict[int, str]) -> tuple[list[tuple], list[tuple]]:
    items, containers = [], []
    for obj in characters:
        owner_title = character_titles[int(obj["object_id"])]
        owner = f"[[{owner_title}\\|{short_title(owner_title)}]]"
        for entry in obj.get("inventory", []):
            kind, en, zh = bb.item_data(entry["item"], lookup, item_messages)
            items.append((kind, bb.item_link(en, zh, note_index), region.title, owner, int(entry["quantity"])))
    for obj in objects:
        if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0:
            continue
        kind, en, zh = bb.item_data(obj, lookup, item_messages)
        link = bb.item_link(en, zh, note_index)
        where = f"对象 ID {obj['object_id']}；tile {obj['tile']}"
        if obj["prototype"].get("subtype_name") == "container":
            contents = []
            for entry in obj.get("inventory", []):
                _, ien, izh = bb.item_data(entry["item"], lookup, item_messages)
                contents.append(f"{bb.item_link(ien, izh, note_index)} ×{entry['quantity']}")
            containers.append((region.title, f"{link}（{where}）", "<br>".join(contents) if contents else "空"))
        else:
            items.append((kind, link, region.title, where, 1))
    return items, containers


def people_table(characters: list[dict], titles: dict[int, str], named: bool) -> list[str]:
    selected = [o for o in characters if (int(o["object_id"]) in NAMED) == named]
    if not selected:
        return ["| — | — | — | — |"]
    result = []
    for index, obj in enumerate(sorted(selected, key=lambda o: int(o["object_id"])), 1):
        oid = int(obj["object_id"])
        title = titles[oid]
        script = f"`{script_stem(obj)}.INT`" if script_stem(obj) else "无独立脚本"
        result.append(f"| {index} | {oid} | [[{title}\\|{short_title(title)}]] | {script} |")
    return result


def write_region_page(vault_dir: Path, region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                      item_messages: dict, note_index: dict, titles: dict[int, str]) -> None:
    named_rows = people_table(characters, titles, True)
    generic_rows = people_table(characters, titles, False)
    items, containers = item_records(region, characters, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {quantity} |" for kind, name, _, owner, quantity in sorted(items)] or ["| — | — | — | 0 |"]
    container_rows = [f"| {name} | {contents} |" for _, name, contents in containers] or ["| — | 本区域没有容器。 |"]
    service_rows = [f"| {name} | {provider} | {content} |" for name, provider, content in region.services] or ["| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |"]
    destroyed = region.map_name == "CHILDEAD"
    map_note = ("本图采用 `CHILDEAD.MAP` 的地板与残墙层。该地图没有可见场景物件、人物、门、地面物品或容器。" if destroyed else
                "绿色轮廓与标签表示人物，黄色轮廓与标签表示地面物品和容器；容器标签列出直接库存。")
    page = f"""---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, 大教堂]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[Cathedral 大教堂\\|Cathedral 大教堂]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

正常塔楼区域之间通过楼梯和脚本门禁相连；海报上的区域选择与玩家当下可进入的路径不是同一件事。毁坏状态是剧情替代地图，不是正常路线中的附加楼层。

## 地图

![[{region.title}地图（人物与物品标注，活动区域裁切）.png|900]]

{map_note} 图片是 MAP 保存状态的静态快照，不执行人物移动、隐身、战斗、条件性增援或脚本生成对象。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(service_rows)}

## 人物

### 专名人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(named_rows)}

### 普通人物

| 序号 | 地图对象 ID | 人物 | 人物脚本 |
|---:|---:|---|---|
{chr(10).join(generic_rows)}

## 物品

下表按单件物品记录人物随身库存与地图顶层物品；静态库存不代表任意剧情时刻的实时状态。容器只在下一节展开。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 容器 | 直接库存 |
|---|---|
{chr(10).join(container_rows)}

## 任务

本区域没有以大教堂人物为第一个发起人的独立 Pip-Boy 任务主页。劳拉参与从晒骨场发起的追随者调查；塔楼顶层与主宰主线相连。`Cathedral Destruction` 是影片档案标题，不是接取任务。
"""
    (vault_dir / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_home(vault_dir: Path, region_chars: dict[str, list[dict]], region_objects: dict[str, tuple[list[dict], dict]],
               titles: dict[int, str], item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, all_items, all_containers = [], [], [], [], []
    for region in REGIONS:
        chars = region_chars[region.title]
        region_rows.append(f"| [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` | {region.elevation} | {len(chars)} | {region.description.split('。')[0]}。 |")
        for obj in sorted(chars, key=lambda o: int(o["object_id"])):
            oid = int(obj["object_id"])
            row = f"| [[{region.title}\\|{region.chinese}]] | {oid} | [[{titles[oid]}\\|{short_title(titles[oid])}]] |"
            (named_rows if oid in NAMED else generic_rows).append(row)
        objects, lookup = region_objects[region.title]
        items, containers = item_records(region, chars, objects, lookup, item_messages, note_index, titles)
        all_items.extend(items)
        all_containers.extend(containers)
    item_rows = [f"| {kind} | {name} | [[{region}\\|{region.split()[-1]}]] | {owner} | {quantity} |" for kind, name, region, owner, quantity in sorted(all_items)]
    container_rows = [f"| [[{region}\\|{region.split()[-1]}]] | {name} | {contents} |" for region, name, contents in all_containers]
    page = f"""---
title: "Cathedral 大教堂"
aliases: ["Cathedral", "大教堂", "大教堂之子总部"]
tags: [辐射1, 地点, 大教堂]
world_map_grid: "15,20"
world_map_pixel: "775,1025"
---

# Cathedral 大教堂

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图与 Pip-Boy | Cathedral / 大教堂 |
| 知识库标题 | Cathedral 大教堂 |
| 资源地图组 | `CHILDRN1.MAP`、`CHILDRN2.MAP`、`CHILDEAD.MAP` |

## 地点概览

大教堂位于世界地图网格 `(15, 20)`、像素坐标约 `(775, 1025)`。正常状态由入口与四层塔楼组成：公开礼拜、诊疗与交易集中在塔楼一层，夜行者逐层加强警戒，墨菲斯位于塔楼四层。`CHILDEAD.MAP` 是核爆后的毁坏替代状态，不是第六个正常可进入楼层。

地图对象揭示了地点的剧情变化：入口同时保存天启追随者与钢铁兄弟会的条件性突袭队，卡尔德也由毁坏剧情条件控制。这些对象必须落页，但不能据此断言他们在每次到访时都常驻入口。

## 世界地图位置

世界地图网格为 `(15, 20)`，地点锚点像素坐标约为 `(775, 1025)`，发现状态变量为 `77`；知识库总地图另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[Cathedral 大教堂城镇地图（区域标注）.jpg|900]]

海报原图是 `TWNMAP11.FRM`。当前图标出入口与塔楼一至四层的视觉位置；本地导出没有包含引擎 `TownHotSpots` 按钮坐标，因此这些点明确作为视觉锚点保存，不冒充精确点击坐标。毁坏状态复用地点入口逻辑，不另列海报区域。

## 区域与楼层

| 区域 | 资源地图 | elevation | 人物数 | 作用 |
|---|---|---:|---:|---|
{chr(10).join(region_rows)}

## 商店和服务

| 区域 | 商店或服务 | 提供者 | 内容 |
|---|---|---|---|
| [[Tower Level 1 塔楼一层\\|塔楼一层]] | 物资交易 | [[Cathedral 大教堂 - Cathedral Shopkeeper 大教堂店主（ID 1177）\\|Cathedral Shopkeeper 大教堂店主]] | 以物易物；接待受敌对、持械和偷窃状态影响。 |
| [[Tower Level 1 塔楼一层\\|塔楼一层]] | 诊疗与药物 | [[Cathedral 大教堂 - Doctor Wu 吴医生（ID 1301）\\|Doctor Wu 吴医生]] | 存在真实治疗、欺骗和毒害分支，不是无条件安全服务。 |
| [[Tower Level 1 塔楼一层\\|塔楼一层]] | 内部引导 | [[Cathedral 大教堂 - Laura 劳拉（ID 1527）\\|Laura 劳拉]] | 在相关调查状态下介绍内部并协助接近上层。 |

## 地图中的人物

完整对象清点得到正常状态下 38 名人物。专名与普通人物分开列出；同类人物按地图对象 ID 逐个落页。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_rows)}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows)}

## 地图中的物品

下表按单件物品汇总人物随身库存和地图顶层物品；容器实体及其直接库存单列。数据来自 MAP 保存状态，不等同于任意剧情时刻的实时库存。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(item_rows) if item_rows else '| — | — | — | — | 0 |'}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows) if container_rows else '| — | — | 无容器。 |'}

## 任务

| 条目 | 第一个发起人或性质 | 大教堂中的环节 |
|---|---|---|
| Find Children spy in the Followers / 找出追随者中的大教堂间谍 | 首位发起人在晒骨场的天启追随者区域 | 劳拉是追随者渗透大教堂的成员并提供后续情报；任务主页应随首位发起人归档，不在本地点重复创建。 |
| 主宰主线 | 没有大教堂本地的独立 Pip-Boy 接取项 | 经塔楼、墨菲斯及地下通路接近主宰；摧毁大教堂触发毁坏状态。 |
| Cathedral Destruction | Pip-Boy 影片档案标题 | 这是影片名，不是任务名。 |

## 来源边界

- 地点坐标、发现变量与地图编号来自导出的世界地图和 MAP 资源。
- 区域人物、物品、容器与楼层来自 `CHILDRN1.MAP`、`CHILDRN2.MAP`、`CHILDEAD.MAP` 的对象清点。
- 人物身份、条件性增援、服务与对话来自对应 INT 脚本和当前中文消息资源。
- 城镇海报区域标注使用视觉锚点；在本地素材没有引擎按钮表时不写伪精确热点坐标。
"""
    (vault_dir / "Cathedral 大教堂.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    vault = args.vault_root.resolve()
    vault_dir = vault / "地点/Cathedral 大教堂"
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    region_chars: dict[str, list[dict]] = {}
    region_objects: dict[str, tuple[list[dict], dict]] = {}
    titles: dict[int, str] = {}
    homepage_attachments = vault_dir / "attachments"
    homepage_attachments.mkdir(exist_ok=True)
    poster(REPO, homepage_attachments / "Cathedral 大教堂城镇地图（区域标注）.jpg")

    for region in REGIONS:
        region_dir = vault_dir / region.directory
        attachments = region_dir / "attachments"
        people_dir = region_dir / "人物"
        named_dir = people_dir / "Named Characters 专名人物"
        generic_dir = people_dir / "Generic Characters 普通人物"
        people_attachments = people_dir / "attachments"
        for path in (attachments, named_dir, generic_dir, people_attachments):
            path.mkdir(parents=True, exist_ok=True)
        map_doc = load_json(REPO / f"workspace/output/maps/master/MAPS/{region.map_name}/{region.map_name}.json")
        lookup = bb.proto_lookup(map_doc)
        objects = [o for o in map_doc["objects"]["entries"] if int(o.get("elevation_group", -1)) == region.elevation]
        characters = [o for o in objects if o.get("prototype", {}).get("type") == "critter" and int(o.get("tile", -1)) >= 0]
        region_chars[region.title] = characters
        region_objects[region.title] = (objects, lookup)

        render_root = REPO / "workspace/output/maps-rendered" / region.map_name
        map_name = f"{region.title}地图（人物与物品标注，活动区域裁切）.png"
        if region.map_name == "CHILDEAD":
            shutil.copyfile(render_root / "elevation-0-floor-walls.png", attachments / map_name)
            profile = {}
            render_by_id = {}
        else:
            shutil.copyfile(render_root / f"elevation-{region.elevation}-cathedral-region-cropped.png", attachments / map_name)
            shutil.copyfile(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png",
                            attachments / f"Cathedral 大教堂地图（{region.map_name} elevation {region.elevation}，人物与物品高亮）.png")
            profile = profile_maps(REPO, region, characters, people_attachments)
            render_doc = load_json(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json")
            render_by_id = {int(item["object_id"]): item for item in render_doc["critters"]}

        for obj in characters:
            oid = int(obj["object_id"])
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            proto_en, proto_zh = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
            en, zh, _, named = identity(obj, proto_en, proto_zh)
            render_entry = render_by_id[oid]
            frm_stem = Path(render_entry["filename"]).stem.upper()
            art_name = f"{frm_stem}.FRM"
            source = bb.find_critter_frame(REPO, render_entry["filename"], int(obj["rotation"]))
            sprite_name = None
            if source:
                sprite_name = f"{en} {zh}（ID {oid}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
                shutil.copyfile(source, people_attachments / sprite_name)
            text, title, is_named = character_note(REPO, vault, region, obj, proto, proto_en, proto_zh, lookup,
                                                    item_messages, critter_messages, note_index, profile[oid],
                                                    sprite_name, art_name, people_attachments)
            filename = f"Cathedral 大教堂 - {title}.md"
            target = (named_dir if is_named else generic_dir) / filename
            if target.exists() and not args.overwrite:
                raise FileExistsError(target)
            target.write_text(text, encoding="utf-8")
            titles[oid] = f"Cathedral 大教堂 - {title}"

    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        write_region_page(vault_dir, region, region_chars[region.title], objects, lookup, item_messages, note_index, titles)
    write_home(vault_dir, region_chars, region_objects, titles, item_messages, note_index)
    sync_tree(vault_dir, REPO)
    print(f"generated Cathedral package: {len(REGIONS)} regions, {sum(len(v) for v in region_chars.values())} character notes")


if __name__ == "__main__":
    main()
