#!/usr/bin/env python3
"""Generate Obsidian region and character notes for the Hub outside Old Town."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from generate_old_town_character_notes import (
    dialogue_rows,
    find_critter_frame,
    game_data_markdown,
    load_json,
    markdown_text,
    message_groups,
    nearest_component,
    observation_text,
    prototype_names,
)
from fallout1_character_topics import render_topic_section, sync_tree, topic_records


GREEN = (101, 231, 101, 255)
ORANGE = (255, 126, 48, 255)
ITEM_TYPES = {
    "armor": "装甲",
    "weapon": "武器",
    "ammo": "弹药",
    "drug": "药品",
    "container": "容器",
    "key": "钥匙",
    "misc": "杂项",
}
EXTERNAL_STOCK = {
    ("HUBDWNTN", 3177): "BethBox 贝斯的地图外交易库存箱",
    ("HUBDWNTN", 3297): "MitchBox 米奇的地图外交易库存箱",
}
CONTAINER_NAMES = {"Bookcase", "Bookshelf", "Fridge", "Footlocker", "Desk", "Crate"}

# Some task maps contain long traversable routes but very few actors. Cropping
# those maps around labels would hide playable terrain, so preserve the full
# route with a map-specific canvas box instead.
MAP_CROP_BOXES = {
    ("DETHCLAW", 0): (750, 250, 4300, 2200),
}


@dataclass(frozen=True)
class Region:
    directory: str
    map_name: str
    elevation: int
    description: tuple[str, ...]
    services: tuple[tuple[str, str, str], ...]
    tasks: tuple[tuple[str, str, str, str], ...]


REGIONS = (
    Region(
        "Entrance 城门", "HUBENT", 0,
        (
            "城门是[[Hub 哈勃城|哈勃城]]的城镇入口和商队集结区。地图中可以直接看到多支商队的车夫、领队、警卫和双头牛，以及哈勃城警察。",
            "Mat 马特、John 约翰和 Luke 卢克分别在这里处理商队往来；Tony Fry 托尼·佛莱和 Gunther 刚瑟提供哈勃城及治安方面的信息。",
        ),
        (
            ("商队往来", "Mat 马特、John 约翰、Luke 卢克", "商队代表、车夫、领队和警卫在城门区域集结。"),
            ("双头牛交易", "Dan 丹", "丹会谈论并出售双头牛。"),
            ("城市与治安信息", "Tony Fry 托尼·佛莱、Gunther 刚瑟", "介绍哈勃城区域、警察和当地治安。"),
        ),
        (),
    ),
    Region(
        "Downtown 中心区", "HUBDWNTN", 0,
        (
            "中心区是[[Hub 哈勃城|哈勃城]]主要商业街区。Far Go Traders 远行商队、Crimson Caravan 深红商队、贝斯的武器店、米奇的综合商店、斯塔布雷顿夫人的图书馆、罗伦佐的借贷生意和马耳他猎鹰都集中在这张地图。",
            "德克的藏身处位于同一资源地图的地下层，另见[[Decker's Hideout 德克藏身处|德克藏身处]]。",
        ),
        (
            ("Far Go Traders 远行商队", "Butch Harris 布奇·哈里斯、Rutger 罗格尔", "商队业务与失踪商队调查。"),
            ("Crimson Caravan 深红商队", "Demetre Romara 戴米德·罗玛拉、Keri 凯利", "商队业务。"),
            ("武器交易", "Beth 贝斯", "贝斯的武器店；交易库存来自地图外库存箱。"),
            ("All-in-One Store 综合商店", "Mitch 米奇", "药品、工具和书籍等货物；交易库存来自地图外库存箱。"),
            ("图书馆", "Mrs. Stapleton 斯塔布雷顿夫人", "书籍与资料。"),
            ("借贷", "Lorenzo 罗伦佐", "提供贷款。"),
            ("Maltese Falcon 马耳他猎鹰", "Kane 凯恩", "德克控制的酒吧与据点。"),
            ("食物", "Bob 鲍勃", "经营食物摊。"),
        ),
        (
            ("Find the Missing Caravans 寻找失踪的商队（发起人 ID 937）", "Rutger 罗格尔", "中心区", "在远行商队接取和结算。"),
            ("Destroy Deathclaw 消灭死亡爪（发起人 ID 937）", "Rutger 罗格尔", "中心区", "从中心区的失踪商队调查延伸。"),
            ("Help Irwin Clear His Farm 帮助艾尔文清理农场（发起人 ID 3446）", "Irwin 艾尔文", "中心区", "与艾尔文交谈后进入农场。"),
        ),
    ),
    Region(
        "Decker's Hideout 德克藏身处", "HUBDWNTN", 1,
        (
            "德克藏身处位于中心区地下，是 Decker 德克与其手下活动的房间。该区域与[[Downtown 中心区|中心区]]使用同一张资源地图，但属于楼层 1。",
            "Decker 德克在这里向玩家提出刺杀 Daren Hightower 达伦·海托和 Jain 简恩的工作。",
        ),
        (),
        (
            ("Kill the Merchant 干掉商人（发起人 ID 2227）", "Decker 德克", "德克藏身处", "刺杀达伦·海托及其妻子。"),
            ("Kill Jain 干掉简恩（发起人 ID 2227）", "Decker 德克", "德克藏身处", "刺杀纯水商人区的简恩。"),
        ),
    ),
    Region(
        "Merchants 商业区", "HUBWATER", 0,
        (
            "商业区是纯水商人的建筑群和水塔所在区域。地图中还有 Thorndyke 索恩戴克所在的医院，以及 Jain 简恩和大教堂成员活动的建筑。",
            "本页把资源地图 `HUBWATER.MAP` 的地面层记为商业区；它在部分对话中也被称为纯水商人区。",
        ),
        (
            ("医疗", "Thorndyke 索恩戴克", "在医院提供治疗。"),
            ("纯水商人", "Master Merchant 水商首席商人及雇员", "管理供水与商队业务。"),
            ("大教堂活动", "Jain 简恩", "简恩及其护卫在此活动。"),
        ),
        (
            ("Kill Jain 干掉简恩（发起人 ID 2227）", "Decker 德克", "德克藏身处", "简恩是本区域中的刺杀目标。"),
        ),
    ),
    Region(
        "Heights 高地区", "HUBHEIGT", 0,
        (
            "高地区是 Daren Hightower 达伦·海托宅邸所在的住宅区域。地图中的人物主要是海托夫妇、宅邸人员和警卫。",
            "德克所说的商人刺杀目标位于这里。",
        ),
        (),
        (
            ("Kill the Merchant 干掉商人（发起人 ID 2227）", "Decker 德克", "德克藏身处", "达伦·海托及其妻子是本区域中的刺杀目标。"),
        ),
    ),
    Region(
        "Irwin's Farm 艾尔文农场", "HUBMIS1", 0,
        (
            "艾尔文农场是从中心区任务直接进入的独立地图。Irwin 艾尔文说，强盗占据了他的农场并杀死了他的双头牛 Pugsly；地图中实际放置了七名强盗。",
            "玩家清除强盗后返回中心区向艾尔文报告。",
        ),
        (),
        (
            ("Help Irwin Clear His Farm 帮助艾尔文清理农场（发起人 ID 3446）", "Irwin 艾尔文", "中心区", "清除本地图中的七名强盗，再返回艾尔文处。"),
        ),
    ),
    Region(
        "Thieves Circle 贼窝", "HUBOLDTN", 1,
        (
            "贼窝是[[Old Town 旧城区|旧城区]]地下的盗贼公会据点，与旧城区使用同一张资源地图但位于楼层 1。这里不是死亡爪的窝。",
            "Loxley 洛克西里、Jasmine 茉莉、Cleo 克利奥和 Smitty 史密蒂都位于本层。",
        ),
        (
            ("盗贼公会", "Loxley 洛克西里、Jasmine 茉莉", "处理加入公会的测试和任务说明。"),
        ),
        (
            ("Steal the Necklace 从商人那里偷走项链（发起人 ID 2372）", "Loxley 洛克西里", "贼窝", "由茉莉提供细节、地图和工具；取得项链后返回。"),
        ),
    ),
)


FULL_NAMES = {
    722: ("Butch Harris", "布奇·哈里斯"),
    392: ("Demetre Romara", "戴米德·罗玛拉"),
    2505: ("Justin Greene", "贾斯丁·格林"),
    1311: ("Tony Fry", "托尼·佛莱"),
    2540: ("Tony Fry", "托尼·佛莱"),
    804: ("Daren Hightower", "达伦·海托"),
}

SCRIPT_ENGLISH = {
    "gencop": "Police",
    "carvlead": "Caravan Leader",
    "danwife": "Dan's Wife",
    "deckgrd": "Decker's Guard",
    "farmraid": "Raider",
    "hwmhost": "Hub Guard",
    "hchdgrd": "Cathedral Guard",
    "wmguard": "Water Merchant Guard",
    "hubpatnt": "Patient",
    "hbodgrd2": "Jain's Guard",
    "hubflrcd": "Flower Child",
    "wmgroup": "Water Merchant Employee",
    "wmcarvn": "Water Merchant Caravan Driver",
    "mstmerch": "Master Merchant",
    "htwrgrd": "Hightower's Guard",
    "hubpris": "Prisoner",
    "hhooker": "Drunk",
    "fgtgard": "Far Go Traders Guard",
    "hrndbar": "Bar Patron",
    "ccguard": "Crimson Caravan Guard",
    "hgengamb": "Gambler",
    "falcon1": "Bartender",
    "fgtcarvn": "Far Go Traders Caravan Driver",
}

KNOWN_PERSON_LINKS = {
    "Mat 马特": "Hub 哈勃城 - Mat 马特（ID 275）",
    "John 约翰": "Hub 哈勃城 - John 约翰（ID 324）",
    "Luke 卢克": "Hub 哈勃城 - Luke 卢克（ID 477）",
    "Dan 丹": "Hub 哈勃城 - Dan 丹（ID 727）",
    "Tony Fry 托尼·佛莱": "Hub 哈勃城 - Tony Fry 托尼·佛莱（ID 1311）",
    "Gunther 刚瑟": "Hub 哈勃城 - Gunther 刚瑟（ID 2043）",
    "Butch Harris 布奇·哈里斯": "Hub 哈勃城 - Butch Harris 布奇·哈里斯（ID 722）",
    "Rutger 罗格尔": "Hub 哈勃城 - Rutger 罗格尔（ID 937）",
    "Demetre Romara 戴米德·罗玛拉": "Hub 哈勃城 - Demetre Romara 戴米德·罗玛拉（ID 392）",
    "Keri 凯利": "Hub 哈勃城 - Keri 凯利（ID 360）",
    "Mitch 米奇": "Hub 哈勃城 - Mitch 米奇（ID 1134）",
    "Mrs. Stapleton 斯塔布雷顿夫人": "Hub 哈勃城 - Mrs. Stapleton 斯塔布雷顿夫人（ID 1251）",
    "Beth 贝斯": "Hub 哈勃城 - Beth 贝斯（ID 2128）",
    "Lorenzo 罗伦佐": "Hub 哈勃城 - Lorenzo 罗伦佐（ID 2295）",
    "Kane 凯恩": "Hub 哈勃城 - Kane 凯恩（ID 2598）",
    "Bob 鲍勃": "Hub 哈勃城 - Bob 鲍勃（ID 3280）",
    "Irwin 艾尔文": "Hub 哈勃城 - Irwin 艾尔文（ID 3446）",
    "Decker 德克": "Hub 哈勃城 - Decker 德克（ID 2227）",
    "Thorndyke 索恩戴克": "Hub 哈勃城 - Thorndyke 索恩戴克（ID 189）",
    "Master Merchant 水商首席商人": "Hub 哈勃城 - Master Merchant 水商首席商人（ID 1598）",
    "Jain 简恩": "Hub 哈勃城 - Jain 简恩（ID 638）",
    "Loxley 洛克西里": "Hub 哈勃城 - Loxley 洛克西里（ID 2372）",
    "Jasmine 茉莉": "Hub 哈勃城 - Jasmine 茉莉（ID 2121）",
}

LEGACY = {
    275: "Hub 哈勃城 - Mat 马特.md", 477: "Hub 哈勃城 - Luke 卢克.md",
    727: "Hub 哈勃城 - Dan 丹.md", 1311: "Hub 哈勃城 - Tony Fry 托尼·佛莱.md",
    2043: "Hub 哈勃城 - Gunther 刚瑟.md", 722: "Hub 哈勃城 - Butch Harris 布奇·哈里斯.md",
    937: "Hub 哈勃城 - Rutger 罗格尔.md", 392: "Hub 哈勃城 - Demetre Romara 戴米德·罗玛拉.md",
    360: "Hub 哈勃城 - Keri 凯利.md", 1251: "Hub 哈勃城 - Mrs. Stapleton 斯塔布雷顿夫人.md",
    2505: "Hub 哈勃城 - Justin Greene 贾斯丁·格林.md", 2128: "Hub 哈勃城 - Beth 贝斯.md",
    2295: "Hub 哈勃城 - Lorenzo 罗伦佐.md", 2598: "Hub 哈勃城 - Kane 凯恩.md",
    3280: "Hub 哈勃城 - Bob 鲍勃.md", 3446: "Hub 哈勃城 - Irwin 艾尔文.md",
    2227: "Hub 哈勃城 - Decker 德克.md", 2540: "Hub 哈勃城 - Tony Fry 托尼·佛莱.md",
    563: "Hub 哈勃城 - Leon 利昂.md", 589: "Hub 哈勃城 - George 乔治.md",
    804: "Hub 哈勃城 - Daren Hightower 达伦·海托.md", 189: "Hub 哈勃城 - Thorndyke 索恩戴克.md",
    638: "Hub 哈勃城 - Jain 简恩.md", 311: "Hub 哈勃城 - Hub Guard 哈勃城警卫（南区）.md",
    247: "Hub 哈勃城 - Cathedral Guard 大教堂警卫.md", 1532: "Hub 哈勃城 - Caravan Driver 商队车夫（纯水商队）.md",
    1598: "Hub 哈勃城 - Master Merchant 商队头目（纯水商队）.md",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def safe(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "／", value).strip()


def repair_legacy_chinese(value: str) -> str:
    """Repair the small number of Chinese strings exported as Latin-1 mojibake."""
    if any(marker in value for marker in ("Ä", "Ã", "Ò", "¡", "£")):
        try:
            return value.encode("latin-1").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def region_parts(directory: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s+([\u3400-\u9fff].*)$", directory)
    if not match:
        raise ValueError(f"region directory is not bilingual: {directory}")
    return match.group(1), match.group(2)


def strike_table_row(row: str) -> str:
    protected = row.replace("\\|", "\x00")
    cells = [cell.strip().replace("\x00", "\\|") for cell in protected.strip().strip("|").split("|")]
    return "| " + " | ".join(f"~~{cell}~~" for cell in cells) + " |"


def escape_table_wikilinks(value: str) -> str:
    lines = []
    pattern = re.compile(r"\[\[([^\]\n]*?)(?<!\\)\|([^\]\n]+)\]\]")
    for line in value.splitlines():
        if line.startswith("|"):
            line = pattern.sub(r"[[\1\\|\2]]", line)
        lines.append(line)
    return "\n".join(lines) + ("\n" if value.endswith("\n") else "")


def walk_items(obj):
    for entry in obj.get("inventory", []):
        child = entry.get("item", entry)
        yield child, int(entry.get("quantity", 1))


def item_link(pid: int, english: str, chinese: str, item_notes: dict[int, str]) -> str:
    display = f"{english} {chinese}" if chinese and chinese != english else english
    stem = item_notes.get(pid)
    return f"[[{stem}\\|{display}]]" if stem else display


def link_known_people(value: str) -> str:
    result = value
    for display, target in sorted(KNOWN_PERSON_LINKS.items(), key=lambda item: -len(item[0])):
        result = result.replace(display, f"[[{target}\\|{display}]]")
    return result


def scan_item_notes(vault: Path) -> dict[int, str]:
    result = {}
    for path in (vault / "物品").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*-?\s*(\d+)\s*$", text):
            before = text[max(0, match.start() - 80):match.start()]
            if "prototype_id" in before or "prototype_ids" in before:
                result[int(match.group(1))] = path.stem
        match = re.search(r"(?m)^prototype_id:\s*(\d+)\s*$", text)
        if match:
            result[int(match.group(1))] = path.stem
    return result


def load_names(repo: Path):
    config = load_json(repo / "config/hub-critter-names.zh-CN.json")
    return config["bilingual_names"], config["script_names"], config["prototype_names"]


def person_name(label: dict, obj: dict, proto: dict, names) -> tuple[str, str, bool]:
    object_id = int(obj["object_id"])
    if object_id in FULL_NAMES:
        return (*FULL_NAMES[object_id], True)
    bilingual, script_names, proto_names = names
    script = Path(obj.get("script_filename") or "").stem
    display = label.get("display_name", "")
    if " / " in display:
        chinese, english = display.split(" / ", 1)
        return english.strip(), chinese.strip(), True
    english_proto = next((key for key, value in proto_names.items() if value == display), "")
    if not english_proto:
        english_proto = str(proto.get("name") or display or f"Critter {object_id}")
    english = bilingual.get(script) or SCRIPT_ENGLISH.get(script.casefold()) or bilingual.get(english_proto) or english_proto
    chinese = script_names.get(obj.get("script_filename") or "") or proto_names.get(english_proto) or display or english
    named = bool(bilingual.get(script))
    return english, chinese, named


def crop_box(labels: list[dict], size: tuple[int, int], margin=260) -> tuple[int, int, int, int]:
    points = []
    for label in labels:
        points.append(tuple(map(int, label["target_canvas"])))
        box = tuple(map(int, label["label_box_canvas"]))
        points.extend(((box[0], box[1]), (box[2], box[3])))
    left = max(0, min(x for x, _ in points) - margin)
    top = max(0, min(y for _, y in points) - margin)
    right = min(size[0], max(x for x, _ in points) + margin)
    bottom = min(size[1], max(y for _, y in points) + margin)
    return left, top, right, bottom


def scaled_crop(image: Image.Image, box, max_width=3600, max_height=2400) -> Image.Image:
    cropped = image.crop(box)
    ratio = min(1.0, max_width / cropped.width, max_height / cropped.height)
    if ratio < 1:
        cropped = cropped.resize((round(cropped.width * ratio), round(cropped.height * ratio)), Image.Resampling.LANCZOS)
    return cropped


def render_maps(repo: Path, region: Region, attachments: Path, person_attachments: Path, labels: list[dict]):
    root = repo / "workspace/output/maps-rendered" / region.map_name
    prefix = f"elevation-{region.elevation}"
    composite = Image.open(root / f"{prefix}-floor-walls-doors-scenery-items-critters.png").convert("RGBA")
    critters = Image.open(root / f"{prefix}-critters.png").convert("RGBA")
    labeled = Image.open(root / f"{prefix}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png").convert("RGBA")
    render_doc = load_json(root / f"{prefix}-floor-walls-doors-scenery-items-critters.json")
    all_labels = labels + render_doc.get("item_name_labels", {}).get("labels", [])
    fixed_box = MAP_CROP_BOXES.get((region.map_name, region.elevation))
    main_box = fixed_box or crop_box(all_labels or labels, labeled.size, 300)
    main_name = f"{region.directory}地图（人物与物品标注，活动区域裁切）.png"
    scaled_crop(labeled, main_box).save(attachments / main_name, compress_level=9)

    people_labels = [
        label for label in labels
        if Path(label.get("script_filename") or "").stem.casefold() != "brahmin"
    ]
    alpha = critters.getchannel("A")
    green_outline = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(5)), alpha)
    base = Image.composite(Image.new("RGBA", composite.size, GREEN), composite, green_outline)
    people_box = fixed_box or crop_box(people_labels, composite.size, 300)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font = ImageFont.truetype(str(font_path), 28)
    results = {}
    for selected in people_labels:
        selected_id = int(selected["object_id"])
        canvas = base.copy()
        target = tuple(map(int, selected["target_canvas"]))
        if not selected.get("missing_art"):
            component = nearest_component(alpha, target)
            if component is not None:
                outline = ImageChops.subtract(component.filter(ImageFilter.MaxFilter(7)), component)
                canvas = Image.composite(Image.new("RGBA", canvas.size, ORANGE), canvas, outline)
        draw = ImageDraw.Draw(canvas, "RGBA")
        for label in people_labels:
            oid = int(label["object_id"])
            color = ORANGE if oid == selected_id else GREEN
            tx, ty = map(int, label["target_canvas"])
            left, top, right, bottom = map(int, label["label_box_canvas"])
            draw.line((tx, ty, (left + right) // 2, bottom if bottom <= ty else top), fill=color, width=1)
            draw.rectangle((left, top, right, bottom), fill=(0, 0, 0, 218), outline=color, width=1)
            value = label["display_name"]
            text_box = draw.textbbox((0, 0), value, font=font, stroke_width=1)
            x = left + max(4, (right - left - (text_box[2] - text_box[0])) // 2)
            y = top + max(2, (bottom - top - (text_box[3] - text_box[1])) // 2) - text_box[1]
            draw.text((x, y), value, font=font, fill="white", stroke_width=1, stroke_fill="black")
        name = f"{region.directory}地图（人物标注，ID {selected_id}高亮，活动区域裁切）.png"
        scaled_crop(canvas, people_box).save(person_attachments / name, compress_level=9)
        results[selected_id] = name
    return main_name, results, render_doc


def dialogue_markdown(repo: Path, script_filename: str | None) -> str:
    if not script_filename:
        return "## 对话\n\n素材没有为该地图对象配置独立人物脚本。"
    script = Path(script_filename).stem.upper()
    grouped = dialogue_rows(repo, script)
    rows = []
    for proc, entries in grouped.items():
        npc = []
        options = []
        for row in entries:
            text = markdown_text(row.get("msg_text", ""))
            if not text:
                continue
            if row.get("call") in {"reply", "message"} and text not in npc:
                npc.append(text)
            elif row.get("call") == "intelligence_option":
                target = row.get("target_procedure_name") or "结束对话"
                value = f"{text} → `{target}`"
                if value not in options:
                    options.append(value)
        if npc or options:
            rows.append((proc, "<br><br>".join(npc) or "—", "<br>".join(options) or "—"))
    if not rows:
        return f"## 对话\n\n该人物使用 `{script}.INT`，导出的结构化对话表中没有可直接列出的台词。"
    lines = [
        "## 对话", "",
        "以下按脚本过程列出素材中的实际人物台词和玩家选项，不对原文进行改写。", "",
        "| 脚本过程 | 人物台词 | 玩家选项与目标分支 |", "|---|---|---|",
    ]
    lines.extend(f"| `{proc}` | {npc} | {options} |" for proc, npc, options in rows)
    return "\n".join(lines)


def legacy_body(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"(?m)^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", text)
    return "## 既有整理内容\n\n以下内容保留自原人物笔记。\n\n" + text.strip()


def inventory_section(obj: dict, proto_lookup: dict, item_messages, item_notes: dict[int, str]) -> str:
    rows = []
    for child, quantity in walk_items(obj):
        pid = int(child["prototype"]["list_index"])
        proto = proto_lookup[("item", pid)]
        english, chinese = item_messages.get(int(proto["message_id"]), (f"Item {pid}", f"Item {pid}"))
        subtype = proto.get("subtype_name") or "misc"
        item_type = "瓶盖" if english == "Bottle Caps" else ITEM_TYPES.get(subtype, subtype)
        rows.append((item_type, item_link(pid, english, chinese, item_notes), quantity))
    lines = ["## 物品信息", ""]
    if not rows:
        lines.append(f"地图对象 `{obj['object_id']}` 的库存为空。")
    else:
        lines.extend(["| 类型 | 物品 | 数量 |", "|---|---|---:|"])
        lines.extend(f"| {kind} | {name} | {quantity} |" for kind, name, quantity in rows)
    return "\n".join(lines)


def person_note(repo: Path, region: Region, obj: dict, proto: dict, label: dict, names, critter_messages, item_messages, proto_lookup, item_notes, map_name: str, sprite_name: str | None, art_name: str, old_body: str):
    oid = int(obj["object_id"])
    english, chinese, named = person_name(label, obj, proto, names)
    title = f"{english} {chinese}（ID {oid}）"
    script = obj.get("script_filename")
    observation = repair_legacy_chinese(observation_text(repo, script, proto, critter_messages))
    full_name = f"素材直接确认的名称为 {english}；没有提供更多姓名组成部分"
    if named and oid in FULL_NAMES:
        full_name = f"{english} / {chinese}"
    elif not named:
        full_name = "普通人物类别名称，不是专名"
    sprite = f"![[{sprite_name}|160]]\n\n地图人物精灵取自 `{art_name}`，方向 {obj['rotation']} 的第 0 帧。" if sprite_name else "资源索引指向的人物 FRM 当前未能导出，因此不借用其他人物造型。"
    script_value = Path(script).stem.upper() + ".INT" if script else "无独立人物脚本"
    alias_values = [f"Hub 哈勃城 - {english} {chinese}", f"{english} {chinese}", chinese]
    alias_lines = "\n".join(f"  - {json.dumps(value, ensure_ascii=False)}" for value in alias_values)
    parts = [f"""---
title: {json.dumps(title, ensure_ascii=False)}
aliases:
{alias_lines}
tags:
  - 辐射1
  - 人物
  - 哈勃城
  - {region_parts(region.directory)[1]}
map: {region.map_name}
elevation: {region.elevation}
map_object_id: {oid}
prototype_id: {obj['prototype']['list_index']}
map_tile: {obj['tile']}
---

# {english} {chinese}

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | {english} |
| 中文名 | {chinese} |
| 全名 | {full_name} |
| 游戏观察文字 | {markdown_text(observation)} |

## 地图信息

![[{map_name}|900]]

绿色标出本区域中的其他人物；橙色标出本人物。相同类别的人物通过地图对象 ID 区分。

| 属性 | 值 |
|---|---|
| 出现地点 | [[{region.directory}\\|{region_parts(region.directory)[1]}]] |
| 资源地图 | {region.map_name}.MAP |
| 楼层 | {region.elevation} |
| 地图对象 ID | {oid} |
| 人物原型 ID | {obj['prototype']['list_index']} |
| 地图格 | {obj['tile']} |
| 地图坐标 | X {obj['tile_x']}，Y {obj['tile_y']} |
| 朝向 | {obj['rotation']} |
| 人物脚本 | {script_value} |
| 人物形象 | {art_name} |

## 形象

### 地图人物精灵

{sprite}

### 对话头像

素材没有为此人物配置独立对话头像。""", game_data_markdown(obj, proto), inventory_section(obj, proto_lookup, item_messages, item_notes)]
    topics = topic_records(repo, script_value)
    if topics:
        parts.append(render_topic_section(topics, level=2))
    parts.extend([dialogue_markdown(repo, script), f"## 身份与处境\n\n{markdown_text(observation)}"])
    if old_body:
        parts.append(old_body)
    return "\n\n".join(parts).rstrip() + "\n", title, english, chinese, named


def area_items(objects, critter_names, proto_lookup, item_messages, item_notes, region: Region):
    ground = defaultdict(lambda: defaultdict(int))
    containers = []
    for obj in objects:
        p = obj.get("prototype", {})
        if p.get("type") == "critter":
            holder = critter_names.get(int(obj["object_id"]), ("", "人物"))[1]
            for child, quantity in walk_items(obj):
                pid = int(child["prototype"]["list_index"])
                proto = proto_lookup[("item", pid)]
                english, chinese = item_messages.get(int(proto["message_id"]), (f"Item {pid}", f"Item {pid}"))
                subtype = proto.get("subtype_name") or "misc"
                kind = "瓶盖" if english == "Bottle Caps" else ITEM_TYPES.get(subtype, subtype)
                ground[(kind, item_link(pid, english, chinese, item_notes))][holder] += quantity
        elif p.get("type") == "item":
            pid = int(p["list_index"])
            proto = proto_lookup[("item", pid)]
            english, chinese = item_messages.get(int(proto["message_id"]), (f"Item {pid}", f"Item {pid}"))
            subtype = proto.get("subtype_name") or "misc"
            kind = "瓶盖" if english == "Bottle Caps" else ITEM_TYPES.get(subtype, subtype)
            if subtype == "container" or english in CONTAINER_NAMES:
                contents = []
                for child, quantity in walk_items(obj):
                    child_pid = int(child["prototype"]["list_index"])
                    child_proto = proto_lookup[("item", child_pid)]
                    en, zh = item_messages.get(int(child_proto["message_id"]), (f"Item {child_pid}", f"Item {child_pid}"))
                    contents.append(f"{item_link(child_pid, en, zh, item_notes)} ×{quantity}")
                external = (region.map_name, int(obj["object_id"])) in EXTERNAL_STOCK or int(obj.get("tile", -1)) == 0
                suffix = f"（{EXTERNAL_STOCK[(region.map_name, int(obj['object_id']))]}）" if (region.map_name, int(obj["object_id"])) in EXTERNAL_STOCK else ""
                containers.append((external, item_link(pid, english, chinese, item_notes) + suffix, "<br>".join(contents) or "空"))
            else:
                holder = "地图边界（地图格 0）" if int(obj.get("tile", -1)) == 0 else "地面"
                ground[(kind, item_link(pid, english, chinese, item_notes))][holder] += 1
    item_lines = ["| 类型 | 物品名 | 人物或位置 | 数量 |", "|---|---|---|---:|"]
    normal, external_rows = [], []
    for (kind, linked_item), holders in sorted(ground.items(), key=lambda row: (row[0][0], row[0][1])):
        for holder, quantity in sorted(holders.items(), key=lambda row: -row[1]):
            row = f"| {kind} | {linked_item} | {holder} | {quantity} |"
            (external_rows if "地图格 0" in holder else normal).append(row)
    item_lines.extend(normal)
    item_lines.extend(strike_table_row(row) for row in external_rows)
    if not normal and not external_rows:
        item_lines.append("| — | — | — | — |")
    container_lines = ["| 区域 | 容器名 | 物品列表 |", "|---|---|---|"]
    for external, name, contents in sorted(containers, key=lambda row: row[0]):
        row = f"| {region_parts(region.directory)[1]} | {name} | {contents} |"
        container_lines.append(strike_table_row(row) if external else row)
    if not containers:
        container_lines.append(f"| {region_parts(region.directory)[1]} | — | 本区域没有物品容器。 |")
    return "\n".join(item_lines), "\n".join(container_lines)


def area_note(region: Region, main_map: str, people, item_table: str, container_table: str):
    named = [p for p in people if p[5]]
    generic = [p for p in people if not p[5]]
    def people_table(entries):
        lines = ["| 序号 | 地图对象 ID | 人物 | 身份或作用 |", "|---:|---:|---|---|"]
        for index, (oid, stem, english, chinese, observation, _) in enumerate(entries, 1):
            lines.append(f"| {index} | {oid} | [[{stem}\\|{english} {chinese}]] | {markdown_text(observation)} |")
        if not entries:
            lines.append("| — | — | — | — |")
        return "\n".join(lines)
    service_lines = ["| 商店或服务 | 提供者 | 内容 |", "|---|---|---|"]
    for service, provider, content in region.services:
        service_lines.append(f"| {service} | {link_known_people(provider)} | {content} |")
    if not region.services:
        service_lines.append("| — | — | 本区域没有从素材中确认的公开商店或服务。 |")
    task_lines = ["| 任务名 | 任务链上第一个发起人 | 发起人所在区域 | 本区域中的环节 |", "|---|---|---|---|"]
    for task, giver, giver_area, step in region.tasks:
        task_lines.append(f"| [[{task}\\|{task.split('（', 1)[0]}]] | {link_known_people(giver)} | {giver_area} | {step} |")
    if not region.tasks:
        task_lines.append("| — | — | — | 本区域没有独立任务。 |")
    english, chinese = region_parts(region.directory)
    description = "\n\n".join(region.description)
    return f"""---
title: {json.dumps(region.directory, ensure_ascii=False)}
aliases:
  - {json.dumps(english, ensure_ascii=False)}
  - {json.dumps(chinese, ensure_ascii=False)}
tags:
  - 辐射1
  - 地点
  - 哈勃城
map: {region.map_name}
elevation: {region.elevation}
---

# {region.directory}

## 名称

| 使用位置 | 名称 |
|---|---|
| 城市区域 | {english} |
| 中文 | {chinese} |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | {region.elevation} |

## 直接描述

{description}

## 地图

![[{main_map}|900]]

地图保留导出资源中的人物、物品和容器标注，并裁切到包含有效标注的活动区域。

## 商店和服务

{chr(10).join(service_lines)}

## 人物

下列 ID 是本区域导出数据中的地图对象 ID。普通人物即使名称相同，也按地图中实际对象逐个列行。双头牛等非人物生物不列入人物笔记。

### 专名人物

{people_table(named)}

### 普通人物

{people_table(generic)}

## 物品

下表记录地面直接放置或由人物携带的物品；容器内物品另见“容器”。地图格 0 或地图外库存使用删除线标识并置底。

{item_table}

## 容器

{container_table}

## 任务

{chr(10).join(task_lines)}
"""


TASK_DOCS = {
    "Decker's Hideout 德克藏身处/任务/Kill the Merchant 干掉商人（发起人 ID 2227）.md": """---
title: Kill the Merchant 干掉商人
aliases: [干掉商人, Kill the Merchant]
tags: [辐射1, 任务, 哈勃城, 德克藏身处]
quest_giver: Decker 德克
quest_giver_map_object_id: 2227
---

# Kill the Merchant 干掉商人

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | Kill the Merchant |
| 中文名 | 干掉商人 |
| 发起人 | [[Hub 哈勃城 - Decker 德克（ID 2227）|Decker 德克]] |

## 任务概览

德克把目标称为高地区的一名商人和他的妻子，并说明目标住在 Business Street 与 Sand Ave 一带。目标是[[Hub 哈勃城 - Daren Hightower 达伦·海托（ID 804）|Daren Hightower 达伦·海托]]与[[Hub 哈勃城 - Martha 玛莎（ID 576）|Martha 玛莎]]。

## 接取与报酬

德克承诺先付 500 瓶盖，完成后再付 2500 瓶盖。这里保留脚本台词给出的两个数值，不把它们合并成已经一次性取得的报酬。

## 人物与区域

| 人物 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[Hub 哈勃城 - Decker 德克（ID 2227）|Decker 德克]] | 2227 | [[Decker's Hideout 德克藏身处|德克藏身处]] | 发起任务。 |
| [[Hub 哈勃城 - Daren Hightower 达伦·海托（ID 804）|Daren Hightower 达伦·海托]] | 804 | [[Heights 高地区|高地区]] | 刺杀目标。 |
| [[Hub 哈勃城 - Martha 玛莎（ID 576）|Martha 玛莎]] | 576 | [[Heights 高地区|高地区]] | 刺杀目标。 |
""",
    "Decker's Hideout 德克藏身处/任务/Kill Jain 干掉简恩（发起人 ID 2227）.md": """---
title: Kill Jain 干掉简恩
aliases: [干掉简恩, Kill Jain]
tags: [辐射1, 任务, 哈勃城, 德克藏身处]
quest_giver: Decker 德克
quest_giver_map_object_id: 2227
---

# Kill Jain 干掉简恩

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | Kill Jain |
| 中文名 | 干掉简恩 |
| 发起人 | [[Hub 哈勃城 - Decker 德克（ID 2227）|Decker 德克]] |

## 任务概览

完成德克的第一项刺杀工作后，他会提出第二项工作：杀死纯水商人区的大祭司 Jain 简恩。目标位于[[Merchants 商业区|商业区]]。

## 接取与报酬

德克在对话中承诺先付 1000 瓶盖，完成后再付 4000 瓶盖。

## 人物与区域

| 人物 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[Hub 哈勃城 - Decker 德克（ID 2227）|Decker 德克]] | 2227 | [[Decker's Hideout 德克藏身处|德克藏身处]] | 发起任务。 |
| [[Hub 哈勃城 - Jain 简恩（ID 638）|Jain 简恩]] | 638 | [[Merchants 商业区|商业区]] | 刺杀目标。 |
""",
    "Irwin's Farm 艾尔文农场/任务/Help Irwin Clear His Farm 帮助艾尔文清理农场（发起人 ID 3446）.md": """---
title: Help Irwin Clear His Farm 帮助艾尔文清理农场
aliases: [帮助艾尔文清理农场, Help Irwin Clear His Farm]
tags: [辐射1, 任务, 哈勃城, 艾尔文农场]
quest_giver: Irwin 艾尔文
quest_giver_map_object_id: 3446
---

# Help Irwin Clear His Farm 帮助艾尔文清理农场

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | Help Irwin Clear His Farm |
| 中文名 | 帮助艾尔文清理农场 |
| 发起人 | [[Hub 哈勃城 - Irwin 艾尔文（ID 3446）|Irwin 艾尔文]] |

## 任务背景

艾尔文说，他在城外的农场被强盗占据，强盗还杀死了他的双头牛 Pugsly。接受委托后，玩家会进入独立的 `HUBMIS1.MAP`。

## 目标与完成

地图中有七名执行 `FarmRaid.INT` 的强盗。清除他们后返回中心区告诉艾尔文农场已经安全；艾尔文的完成台词说会把“一把枪”交给玩家。脚本完成分支还使用 `500` 这一奖励数值。

## 人物与区域

| 人物 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[Hub 哈勃城 - Irwin 艾尔文（ID 3446）|Irwin 艾尔文]] | 3446 | [[Downtown 中心区|中心区]] | 发起和结算任务。 |
| 强盗（7人） | 579、602、669、749、809、842、858 | [[Irwin's Farm 艾尔文农场|艾尔文农场]] | 需要清除的占据者。 |
""",
    "Thieves Circle 贼窝/任务/Steal the Necklace 从商人那里偷走项链（发起人 ID 2372）.md": """---
title: Steal the Necklace 从商人那里偷走项链
aliases: [从商人那里偷走项链, Steal the Necklace]
tags: [辐射1, 任务, 哈勃城, 贼窝]
quest_giver: Loxley 洛克西里
quest_giver_map_object_id: 2372
---

# Steal the Necklace 从商人那里偷走项链

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | Steal the Necklace |
| 中文名 | 从商人那里偷走项链 |
| 发起人 | [[Hub 哈勃城 - Loxley 洛克西里（ID 2372）|Loxley 洛克西里]] |

## 任务概览

这是洛克西里给出的盗贼公会入会测试。接受后，[[Hub 哈勃城 - Jasmine 茉莉（ID 2121）|Jasmine 茉莉]]会提供目标细节、地图和工具；玩家取得项链后返回贼窝。

## 完成

把项链带回后，洛克西里的完成分支确认玩家加入公会。脚本在这一分支使用 `500` 点经验奖励并显示经验提示。

## 人物与区域

| 人物 | 地图对象 ID | 区域 | 作用 |
|---|---:|---|---|
| [[Hub 哈勃城 - Loxley 洛克西里（ID 2372）|Loxley 洛克西里]] | 2372 | [[Thieves Circle 贼窝|贼窝]] | 发起并完成入会测试。 |
| [[Hub 哈勃城 - Jasmine 茉莉（ID 2121）|Jasmine 茉莉]] | 2121 | [[Thieves Circle 贼窝|贼窝]] | 提供细节、地图和工具。 |
""",
}


def update_links(vault: Path, replacements: dict[str, str]):
    for path in vault.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        changed = text
        for old, new in replacements.items():
            changed = changed.replace(f"[[{old}\\|", f"[[{new}\\|")
            changed = changed.replace(f"[[{old}|", f"[[{new}|")
            changed = changed.replace(f"[[{old}]]", f"[[{new}]]")
            changed = changed.replace(f"[[{old}#", f"[[{new}#")
        if changed != text:
            path.write_text(changed, encoding="utf-8")


def update_hub_regions(hub: Path):
    text = hub.read_text(encoding="utf-8")
    region_links = {
        "| Entrance | 城门 |": "| [[Entrance 城门|Entrance]] | [[Entrance 城门|城门]] |",
        "| Downtown | 中心区 |": "| [[Downtown 中心区|Downtown]] | [[Downtown 中心区|中心区]] |",
        "| Heights | 高地区 |": "| [[Heights 高地区|Heights]] | [[Heights 高地区|高地区]] |",
        "| Old Town | 旧城区 |": "| [[Old Town 旧城区|Old Town]] | [[Old Town 旧城区|旧城区]] |",
        "| Merchants | 商业区 |": "| [[Merchants 商业区|Merchants]] | [[Merchants 商业区|商业区]] |",
        "| 城门 | 城门与商队入口 |": "| [[Entrance 城门|城门]] | [[Entrance 城门|城门与商队入口]] |",
        "| 中心区 | 中心区 |": "| [[Downtown 中心区|中心区]] | [[Downtown 中心区|中心区]] |",
        "| 中心区 | 德克藏身处 |": "| [[Downtown 中心区|中心区]] | [[Decker's Hideout 德克藏身处|德克藏身处]] |",
        "| 高地区 | 高地区 |": "| [[Heights 高地区|高地区]] | [[Heights 高地区|高地区]] |",
        "| 旧城区 | 旧城区 |": "| [[Old Town 旧城区|旧城区]] | [[Old Town 旧城区|旧城区]] |",
        "| 旧城区 | 贼窝 |": "| [[Old Town 旧城区|旧城区]] | [[Thieves Circle 贼窝|贼窝]] |",
        "| 商业区 | 纯水商人区 |": "| [[Merchants 商业区|商业区]] | [[Merchants 商业区|纯水商人区]] |",
        "| 中心区任务 | 艾尔文农场 |": "| [[Downtown 中心区|中心区任务]] | [[Irwin's Farm 艾尔文农场|艾尔文农场]] |",
        "| 干掉[[Hub 哈勃城 - Jain 简恩|简恩]] |": "| [[Kill Jain 干掉简恩（发起人 ID 2227）|干掉简恩]] |",
        "| 干掉商人 |": "| [[Kill the Merchant 干掉商人（发起人 ID 2227）|干掉商人]] |",
        "| 从商人那里偷走项链 |": "| [[Steal the Necklace 从商人那里偷走项链（发起人 ID 2372）|从商人那里偷走项链]] |",
    }
    for old, new in region_links.items():
        text = text.replace(old, new)
    hub.write_text(text, encoding="utf-8")


def main():
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    vault = args.vault_root.resolve()
    hub_root = vault / "地点/Hub 哈勃城"
    root_people = vault / "人物"
    item_notes = scan_item_notes(vault)
    names = load_names(repo)
    critter_messages, item_messages = prototype_names(repo)
    planned_people = 0
    legacy_cache = {name: (root_people / name).read_text(encoding="utf-8") for name in set(LEGACY.values()) if (root_people / name).exists()}
    replacements = {}
    all_legacy_targets = defaultdict(list)

    for region in REGIONS:
        region_dir = hub_root / region.directory
        people_dir = region_dir / "人物"
        task_dir = region_dir / "任务"
        attachments = region_dir / "attachments"
        person_attachments = people_dir / "attachments"
        if not args.dry_run:
            for directory in (region_dir, people_dir, task_dir, attachments, person_attachments):
                directory.mkdir(parents=True, exist_ok=True)
        map_doc = load_json(repo / f"workspace/output/maps/master/MAPS/{region.map_name}/{region.map_name}.json")
        render_path = repo / f"workspace/output/maps-rendered/{region.map_name}/elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json"
        render_doc = load_json(render_path)
        labels = render_doc["critter_name_labels"]["labels"]
        label_by_id = {int(label["object_id"]): label for label in labels}
        objects = [obj for obj in map_doc["objects"]["entries"] if int(obj.get("elevation_group", -1)) == region.elevation]
        critters = [obj for obj in objects if obj.get("prototype", {}).get("type") == "critter" and Path(obj.get("script_filename") or "").stem.casefold() != "brahmin"]
        proto_lookup = {(proto["type"], int(proto["list_index"])): proto for proto in map_doc["referenced_prototypes"]}
        if args.dry_run:
            planned_people += len(critters)
            continue
        main_map, person_maps, full_render_doc = render_maps(repo, region, attachments, person_attachments, labels)
        render_entries = {int(entry["object_id"]): entry for entry in full_render_doc.get("critters", []) + full_render_doc.get("missing_critter_art", [])}
        people = []
        critter_names = {}
        for obj in critters:
            oid = int(obj["object_id"])
            label = label_by_id[oid]
            proto = proto_lookup[("critter", int(obj["prototype"]["list_index"]))]
            render_entry = render_entries.get(oid, {"filename": "unknown.frm"})
            frm_stem = Path(render_entry["filename"]).stem.upper()
            art_name = f"{frm_stem}.FRM"
            frame = find_critter_frame(repo, render_entry["filename"], int(obj["rotation"]))
            english, chinese, named = person_name(label, obj, proto, names)
            sprite_name = None
            if frame:
                sprite_name = f"{safe(english)} {safe(chinese)}（ID {oid}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
                shutil.copyfile(frame, person_attachments / sprite_name)
            # Map object IDs are only unique inside their map/layer. Object 1598 is
            # both a Decker guard on HUBDWNTN elevation 1 and the Master Merchant
            # on HUBWATER elevation 0; only the latter owns the legacy note.
            legacy_name = None if (region.map_name, region.elevation, oid) == ("HUBDWNTN", 1, 1598) else LEGACY.get(oid)
            old_body = ""
            if legacy_name and legacy_name in legacy_cache:
                temp = people_dir / ".legacy-temp.md"
                temp.write_text(legacy_cache[legacy_name], encoding="utf-8")
                old_body = legacy_body(temp)
                temp.unlink()
            content, title, english, chinese, named = person_note(repo, region, obj, proto, label, names, critter_messages, item_messages, proto_lookup, item_notes, person_maps[oid], sprite_name, art_name, old_body)
            stem = f"Hub 哈勃城 - {safe(english)} {safe(chinese)}（ID {oid}）"
            target = people_dir / f"{stem}.md"
            if target.exists() and not args.overwrite:
                raise FileExistsError(f"refusing to overwrite {target}")
            target.write_text(content, encoding="utf-8")
            observation = repair_legacy_chinese(observation_text(repo, obj.get("script_filename"), proto, critter_messages))
            people.append((oid, stem, english, chinese, observation, named))
            critter_names[oid] = (stem, f"[[{stem}\\|{english} {chinese}]]")
            if legacy_name:
                old_stem = Path(legacy_name).stem
                replacements.setdefault(old_stem, stem)
                all_legacy_targets[old_stem].append(stem)
        item_table, container_table = area_items(objects, critter_names, proto_lookup, item_messages, item_notes, region)
        (region_dir / f"{region.directory}.md").write_text(area_note(region, main_map, people, item_table, container_table), encoding="utf-8")
        planned_people += len(people)

    if args.dry_run:
        print(f"would generate 7 region notes and {planned_people} character notes")
        return

    for relative, content in TASK_DOCS.items():
        target = hub_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not args.overwrite:
            raise FileExistsError(f"refusing to overwrite {target}")
        target.write_text(escape_table_wikilinks(content.rstrip() + "\n"), encoding="utf-8")

    # Tony Fry has two map instances; ambiguous old links point to the entrance instance,
    # while both generated notes retain the former note body.
    update_links(vault, replacements)
    update_hub_regions(hub_root / "Hub 哈勃城.md")
    hub_main = hub_root / "Hub 哈勃城.md"
    hub_main.write_text(escape_table_wikilinks(hub_main.read_text(encoding="utf-8")), encoding="utf-8")
    for legacy_name in set(LEGACY.values()):
        path = root_people / legacy_name
        if path.exists():
            path.unlink()
    sync_tree(hub_root, repo)
    print(f"generated 7 region notes, {planned_people} character notes, and {len(TASK_DOCS)} task notes")


if __name__ == "__main__":
    main()
