#!/usr/bin/env python3
"""Generate the complete Fallout 1 Brotherhood location package for Obsidian."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shutil
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from fallout1_character_topics import render_topic_section, sync_tree, topic_records


GREEN = (101, 231, 101, 255)
ORANGE = (255, 126, 48, 255)
ITEM_TYPES = {
    "armor": "装甲",
    "container": "容器",
    "drug": "药品",
    "weapon": "武器",
    "ammo": "弹药",
    "misc": "杂项",
    "key": "钥匙",
}


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
        "Entrance 入口", "Entrance", "入口", "BROHDENT", 0, 13,
        "钢铁兄弟会地表入口是一处围栏围住的小型警戒站。卡波特负责审查访客、发起入会试炼并控制地堡入口；达雷尔和商队领队也在门外。",
        (("访客接待与地堡准入", "Cabbot 卡波特", "说明入会条件，完成试炼后开启地堡入口。"),
         ("商队交易", "Caravan Leader 商队领队", "使用商队领队脚本；具体可交易内容受运行时商队状态控制。")),
    ),
    Region(
        "Level 1 第一层", "Level 1", "第一层", "BROHD12", 0, 14,
        "第一层集中了训练区、补给区和大量警卫。隆伯斯负责骑士训练，塔鲁斯处理游侠事务与营救成员任务，迈克尔管理装备发放。",
        (("装备与任务奖励领取", "Michael 迈克尔", "发放获准装备；塔鲁斯任务的装备奖励也在这里领取。"),
         ("游侠事务与营救任务", "Talus 塔鲁斯", "发起从哈勃城营救失踪成员的任务并结算。"),
         ("骑士训练", "Rhombus 隆伯斯", "介绍骑士训练与兄弟会纪律。")),
    ),
    Region(
        "Level 2 第二层", "Level 2", "第二层", "BROHD12", 1, 14,
        "第二层由医务区、宿舍和研究员教学区构成。罗伊博士及助手在医务室，杰里与多名新兵、骑士和研究员分布在两侧房间。",
        (("医疗与手术", "Dr. Lorri 罗伊博士", "提供治疗，并在满足条件时讨论强化手术。"),
         ("研究员教学", "Teacher 教师", "负责研究员与新兵的教学区域。")),
    ),
    Region(
        "Level 3 第三层", "Level 3", "第三层", "BROHD34", 0, 15,
        "第三层分为图书研究区、骑士宿舍和维修区。弗蕾主持研究员工作并保存兄弟会资料；凯尔负责维修，索菲娅和保罗也在本层。",
        (("历史、磁盘与变种人研究", "Vree 弗蕾", "提供兄弟会历史、研究资料与尸检结论。"),
         ("装备维修", "Kyle 凯尔", "处理动力装甲维修相关问题。")),
    ),
    Region(
        "Level 4 第四层", "Level 4", "第四层", "BROHD34", 1, 15,
        "第四层是议事和指挥区域。马克松、马蒂雅以及四位元老在此；会议区与马克松办公室构成兄弟会决策核心。",
        (("兄弟会战略与军事基地情报", "Maxson 马克松", "讨论北方威胁、军事基地侦察和兄弟会支援。"),
         ("高层事务协调", "Mathia 马蒂雅", "作为马克松身边的协调人员提供说明。")),
    ),
    Region(
        "Destroyed Entrance 毁坏入口", "Destroyed Entrance", "毁坏入口", "BRODEAD", 0, 55,
        "毁坏入口是与正常入口分离的替代地图状态。围栏和地堡入口仍可辨认，但门体已经破损；导出对象中没有人物、地面物品或容器。",
    ),
)


NAMED = {
    430: ("Darrell", "达雷尔", "入口守卫；其脚本介绍兄弟会并把入会访客引向卡波特。"),
    856: ("Cabbot", "卡波特", "钢铁兄弟会新兵兼入口接待者；发起“加入兄弟会”试炼并控制地堡入口。"),
    866: ("Jennifer", "詹妮佛", "第一层成员；专名由人物脚本与观察文字确认。"),
    1876: ("Michael", "迈克尔", "兄弟会装备管理员，负责发放获准装备与任务奖励。"),
    2275: ("Talus", "塔鲁斯", "游侠事务负责人；发起从哈勃城营救失踪成员的任务。"),
    2408: ("Rhombus", "隆伯斯", "骑士首领与训练负责人，以严格纪律著称。"),
    2651: ("Thomas", "托马斯", "第一层成员；专名来自人物原型与脚本。"),
    435: ("Jerry", "杰里", "第二层的一名新兵；观察文字直接给出姓名。"),
    1151: ("Dr. Lorri", "罗伊博士", "兄弟会医生，负责治疗并讨论强化手术。"),
    1418: ("Sophia", "索菲娅", "第三层研究区成员；专名由人物脚本确认。"),
    1419: ("Vree", "弗蕾", "研究员首领，掌管图书、历史资料和变种人研究。"),
    2282: ("Kyle", "凯尔", "第三层维修负责人，处理动力装甲维修。"),
    2690: ("Paul", "保罗", "第三层维修区成员；专名由人物脚本确认。"),
    632: ("Jacob", "雅各布", "兄弟会元老之一；专名来自人物原型。"),
    638: ("Mary", "玛利亚", "兄弟会高级元老；专名来自人物原型。"),
    728: ("Rachael", "瑞秋", "兄弟会元老之一；专名来自人物原型。"),
    734: ("Jonathan", "乔纳森", "兄弟会元老之一；专名来自人物原型。"),
    2117: ("Maxson", "马克松", "兄弟会高级元老，负责战略与北方军事基地威胁。"),
    2121: ("Mathia", "马蒂雅", "马克松身边的事务协调者。"),
}


SCRIPT_ROLES = {
    "CARVLEAD": ("Caravan Leader", "商队领队", "入口处的商队领队。"),
    "SUPGRD": ("Supply Guard", "补给区警卫", "补给区警卫。"),
    "HALLGRD": ("Hallway Guard", "走廊警卫", "负责走廊警戒的游侠。"),
    "ROOMGRD": ("Room Guard", "房间警卫", "负责房间警戒的游侠。"),
    "SUPLYGRD": ("First-Level Supply Guard", "第一层补给警卫", "第一层补给区域的警卫。"),
    "STUDENT": ("Student", "受训学员", "第一层训练区的受训学员。"),
    "BOSASIS": ("Doctor's Assistant", "医生的助手", "罗伊博士的助手；这是职务而不是姓名。"),
    "GENINIT": ("Initiate", "新兵", "钢铁兄弟会新兵。"),
    "TEACHER": ("Teacher", "教师", "研究员教学区的教师。"),
    "GENSCRIB": ("Scribe", "研究员", "钢铁兄弟会研究员。"),
    "GENKNIGH": ("Knight", "骑士", "钢铁兄弟会骑士。"),
    "RD1KNIG": ("Knight", "骑士", "第三层的钢铁兄弟会骑士。"),
    "RD1SCRB1": ("Scribe", "研究员", "第三层的钢铁兄弟会研究员。"),
    "VRESCRIB": ("Vree's Scribe", "弗蕾的研究员", "在弗蕾研究区工作的研究员。"),
    "VREGRD": ("Vree's Guard", "弗蕾的警卫", "负责弗蕾研究区警戒的游侠。"),
    "MAXGRD": ("Maxson's Guard", "马克松的警卫", "负责马克松办公室警戒的游侠。"),
}


HEADS = {"CABBOT": "CABBT", "RHOMBUS": "RHOMB", "VREE": "VVREE", "MAXSON": "MAXSN"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def message_groups(path: Path) -> dict[int, tuple[str, str]]:
    doc = load_json(path)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for entry in doc["entries"]:
        grouped[int(entry["number"])].append(entry)
    result = {}
    for number, entries in grouped.items():
        effective = next((e["text"] for e in entries if e.get("effective")), entries[-1]["text"])
        result[number] = (entries[0]["text"].replace("\n", " "), effective.replace("\n", " "))
    return result


def md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def short_character_title(title: str) -> str:
    return title.removeprefix("Brotherhood 钢铁兄弟会 - ").split("（ID", 1)[0].strip()


def script_stem(obj: dict) -> str:
    return Path(obj.get("script_filename") or "").stem.upper()


def region_for(map_name: str, elevation: int) -> Region:
    return next(r for r in REGIONS if r.map_name == map_name and r.elevation == elevation)


def find_critter_frame(repo: Path, filename: str, rotation: int) -> Path | None:
    frm_name = f"{Path(filename).stem.upper()}.frm"
    frm_dir = repo / "workspace/output/images/critter/ART/CRITTERS" / frm_name
    metadata = frm_dir / f"{frm_name}.json"
    if not metadata.exists():
        return None
    doc = load_json(metadata)
    direction = next(item for item in doc["directions"] if int(item["index"]) == rotation)
    sequence = int(direction["sequence_index"])
    frame = frm_dir / f"{frm_name}.frames" / f"sequence-{sequence:02d}" / "frame-000.png"
    return frame if frame.exists() else None


def nearest_component(alpha: Image.Image, target: tuple[int, int], radius: int = 104) -> Image.Image | None:
    left, top = max(0, target[0] - radius), max(0, target[1] - radius)
    right, bottom = min(alpha.width, target[0] + radius + 1), min(alpha.height, target[1] + radius + 1)
    crop = alpha.crop((left, top, right, bottom))
    pixels = crop.load()
    candidates = []
    for y in range(crop.height):
        for x in range(crop.width):
            if pixels[x, y] > 0:
                candidates.append(((x + left - target[0]) ** 2 + (y + top - target[1]) ** 2, x, y))
    if not candidates:
        return None
    _, sx, sy = min(candidates)
    queue, visited = deque([(sx, sy)]), {(sx, sy)}
    while queue:
        x, y = queue.popleft()
        for nx in range(max(0, x - 1), min(crop.width, x + 2)):
            for ny in range(max(0, y - 1), min(crop.height, y + 2)):
                if (nx, ny) not in visited and pixels[nx, ny] > 0:
                    visited.add((nx, ny)); queue.append((nx, ny))
    component = Image.new("L", alpha.size, 0)
    out = component.load()
    for x, y in visited:
        out[x + left, y + top] = 255
    return component


def character_identity(obj: dict, proto_name: str) -> tuple[str, str, str, bool]:
    oid = int(obj["object_id"])
    if oid in NAMED:
        en, zh, identity = NAMED[oid]
        return en, zh, identity, True
    stem = script_stem(obj)
    if stem in SCRIPT_ROLES:
        en, zh, identity = SCRIPT_ROLES[stem]
        return en, zh, identity, False
    zh = proto_name
    en = proto_name
    return en, zh, f"人物原型分类为 {proto_name}；资源没有提供可确认的个人姓名。", False


def render_profile_maps(repo: Path, region: Region, characters: list[dict], attachments: Path) -> dict[int, str]:
    render_root = repo / "workspace/output/maps-rendered" / region.map_name
    prefix = f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters"
    render_doc = load_json(render_root / f"{prefix}.json")
    labels = render_doc["critter_name_labels"]["labels"]
    composite = Image.open(render_root / f"{prefix}.png").convert("RGBA")
    critters = Image.open(render_root / f"elevation-{region.elevation}-critters.png").convert("RGBA")
    alpha = critters.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(5))
    base = Image.composite(Image.new("RGBA", composite.size, GREEN), composite, ImageChops.subtract(expanded, alpha))
    crop_doc = load_json(render_root / f"elevation-{region.elevation}-brotherhood-region-cropped.json")
    crop = tuple(int(v) for v in crop_doc["crop_box"])
    scale = float(crop_doc.get("scale", 1.0))
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 28)
    outputs = {}
    for obj in characters:
        oid = int(obj["object_id"])
        own = next(label for label in labels if int(label["object_id"]) == oid)
        canvas = base.copy()
        target = tuple(int(v) for v in own["target_canvas"])
        if not own.get("missing_art"):
            component = nearest_component(alpha, target)
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
            label_text = label["display_name"]
            tb = draw.textbbox((0, 0), label_text, font=font, stroke_width=1)
            x = left + max(4, (right - left - (tb[2] - tb[0])) // 2)
            y = top + max(2, (bottom - top - (tb[3] - tb[1])) // 2) - tb[1]
            draw.text((x, y), label_text, font=font, fill="white", stroke_width=1, stroke_fill="black")
        en, zh, _, _ = character_identity(obj, "")
        filename = f"{region.title}地图（人物标注，{en} {zh} ID {oid}高亮，活动区域裁切）.png"
        covered = canvas.crop(crop)
        if scale != 1.0:
            covered = covered.resize(
                (round(covered.width * scale), round(covered.height * scale)),
                Image.Resampling.LANCZOS,
            )
        covered.save(attachments / filename, format="PNG", compress_level=9)
        outputs[oid] = filename
    return outputs


def proto_lookup(map_doc: dict) -> dict[tuple[str, int], dict]:
    return {(p["type"], int(p["list_index"])): p for p in map_doc["referenced_prototypes"]}


def item_data(item_obj: dict, lookup: dict, item_messages: dict) -> tuple[str, str, str]:
    proto = lookup[("item", int(item_obj["prototype"]["list_index"]))]
    en, zh = item_messages.get(int(proto["message_id"]), ("Unknown Item", "未知物品"))
    subtype = item_obj["prototype"].get("subtype_name") or "misc"
    kind = "瓶盖" if en == "Bottle Caps" else ITEM_TYPES.get(subtype, subtype)
    return kind, en, zh


def build_note_index(vault: Path) -> dict[str, str]:
    result = {}
    for folder in (vault / "物品", vault / "武器防具"):
        if not folder.exists():
            continue
        for path in folder.rglob("*.md"):
            stem = path.stem
            result.setdefault(stem.casefold(), stem)
    return result


def item_link(en: str, zh: str, note_index: dict[str, str]) -> str:
    candidates = [f"{en} {zh}", en, zh]
    for candidate in candidates:
        if candidate.casefold() in note_index:
            target = note_index[candidate.casefold()]
            return f"[[{target}\\|{en} {zh}]]"
    # Match common vault names that begin with the exact English resource name.
    matches = [v for k, v in note_index.items() if k.startswith((en + " ").casefold())]
    if len(matches) == 1:
        return f"[[{matches[0]}\\|{en} {zh}]]"
    return f"{en} {zh}"


def observation(repo: Path, obj: dict, proto: dict, critter_messages: dict) -> str:
    stem = script_stem(obj)
    path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{stem}.messages.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["procedure_name"] == "look_at_p_proc" and row.get("msg_text"):
                    return row["msg_text"]
    return critter_messages.get(int(proto["message_id"]) + 1, ("", "素材没有提供独立观察文字。"))[1]


def game_data(obj: dict, proto: dict) -> str:
    stats = proto["fields"]["base_stats"]
    update, combat = obj.get("update_data", {}), obj.get("update_data", {}).get("combat", {})
    gender = "男性" if stats[34] == 0 else "女性" if stats[34] == 1 else str(stats[34])
    return f"""# 游戏数据

## SPECIAL

| 力量 | 感知 | 耐力 | 魅力 | 智力 | 敏捷 | 幸运 |
|---:|---:|---:|---:|---:|---:|---:|
| {stats[0]} | {stats[1]} | {stats[2]} | {stats[3]} | {stats[4]} | {stats[5]} | {stats[6]} |

## 其他数据

| 属性 | 值 |
|---|---:|
| 地图当前生命值 | {update.get('hit_points', stats[7])} |
| 行动点 | {combat.get('action_points', stats[8])} |
| 护甲等级 | {stats[9]} |
| 近战伤害 | {stats[11]} |
| 最大负重 | {stats[12]} |
| 顺序 | {stats[13]} |
| 治疗率 | {stats[14]} |
| 暴击率 | {stats[15]}% |
| 辐射抗性 | {stats[31]}% |
| 毒素抗性 | {stats[32]}% |
| 击杀经验值 | {proto['fields']['experience']} |
| AI 包 | {combat.get('ai_packet', proto['fields']['ai_packet'])} |
| 队伍 | {combat.get('team', proto['fields']['team'])} |
| 原型年龄（技术值） | {stats[33]} |
| 原型性别 | {gender} |"""


def inventory_section(obj: dict, lookup: dict, item_messages: dict, note_index: dict) -> str:
    lines = ["# 物品信息", ""]
    if not obj.get("inventory"):
        lines.append(f"地图对象 `{obj['object_id']}` 的静态库存为空。")
        return "\n".join(lines)
    lines.extend(["| 类型 | 物品 | 数量 |", "|---|---|---:|"])
    rows = []
    for entry in obj["inventory"]:
        kind, en, zh = item_data(entry["item"], lookup, item_messages)
        rows.append((kind, en, zh, int(entry["quantity"])))
    for kind, en, zh, quantity in sorted(rows):
        lines.append(f"| {kind} | {item_link(en, zh, note_index)} | {quantity} |")
    return "\n".join(lines)


def dialogue_section(repo: Path, obj: dict) -> str:
    stem = script_stem(obj)
    path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{stem}.messages.csv"
    if not path.exists():
        return ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    groups: dict[str, list[dict]] = defaultdict(list)
    order = []
    for row in rows:
        proc = row["procedure_name"]
        if proc in {"look_at_p_proc", "description_p_proc"}:
            continue
        if row.get("msg_text") and proc not in groups:
            order.append(proc)
        if row.get("msg_text"):
            groups[proc].append(row)
    if not order:
        return ""
    lines = [
        "# 对话", "",
        f"以下按 `{stem}.INT` 的消息关联表整理。仅列有玩家可见文字的过程；脚本状态、反应值、属性和任务变量仍决定实际可达分支。没有可见文字的控制过程只在箭头中保留过程名。",
    ]
    for proc in order:
        current = groups[proc]
        npc = []
        options = []
        for row in current:
            text = md(row["msg_text"])
            if row["call"] in {"reply", "message", "message_lookup"} and text not in npc:
                npc.append(text)
            elif row["call"] == "intelligence_option":
                intelligence = row.get("intelligence", "")
                condition = f"智力 {intelligence}" if intelligence else "选项"
                target = row.get("target_procedure_name") or "结束对话"
                options.append(f"`{condition}`：{text} → `{target}`")
        title = npc[0][:34] + ("…" if npc and len(npc[0]) > 34 else "") if npc else f"过程 {proc}"
        lines.extend(["", f"## {proc}", "", f"> [!quote]- {title}"])
        if npc:
            lines.extend(["> **人物台词**", ">"] + [f"> - {text}" for text in npc])
        if options:
            lines.extend([">", "> **玩家选项与下一过程**", ">"] + [f"> - {text}" for text in options])
        if not options:
            lines.extend([">", "> **流程说明**", ">", "> - 消息关联表没有为此过程列出玩家选项；后续由人物脚本处理。"])
    return "\n".join(lines)


def head_assets(repo: Path, attachments: Path, en: str, zh: str, stem: str) -> str:
    prefix = HEADS.get(stem)
    if not prefix:
        return "## 对话头像\n\n人物脚本和人物原型没有提供可确认的独立 HEADS 对话头像。"
    heads_root = repo / "workspace/output/images/master/ART/HEADS"
    sections = []
    static_frm = f"{prefix}NF1"
    static_src = heads_root / f"{static_frm}.frm/{static_frm}.frm.frames/sequence-00/frame-000.png"
    static_name = f"{en} {zh} - 静态对话头像（{static_frm}，帧0）.png"
    shutil.copyfile(static_src, attachments / static_name)
    sections.append(f"""## 静态对话头像

![[{static_name}|360]]

静态头像采用 `{static_frm}.FRM` 第 0 帧；`{stem}.INT` 的 `start_gdialog` 头像索引经 `HEADS.LST` 反查为 `{prefix}`。""")
    expression_rows = []
    for code, label in (("GF2", "友好"), ("NF2", "中性"), ("BF2", "敌对")):
        frm = f"{prefix}{code}"
        directory = heads_root / f"{frm}.frm/{frm}.frm.frames/sequence-00"
        frames = sorted(directory.glob("frame-*.png")) if directory.exists() else []
        if frames:
            src = frames[min(4, len(frames) - 1)]
            name = f"{en} {zh} - {label}表情（{frm}，帧{min(4, len(frames)-1)}）.png"
            shutil.copyfile(src, attachments / name)
            expression_rows.append((label, name))
    if expression_rows:
        body = ["## 对话头像表情", ""]
        for label, name in expression_rows:
            body.extend([f"### {label}", "", f"![[{name}|300]]", ""])
        body.append("表情图取自对应 HEADS 表情动画的代表帧，没有补帧或重绘。")
        sections.append("\n".join(body))
    animation_rows = []
    for code, label in (("NF2", "中性待机表情"), ("NP", "中性说话口型"), ("NG", "中性转为友好"), ("NB", "中性转为敌对")):
        frm = f"{prefix}{code}"
        root = heads_root / f"{frm}.frm"
        directory = root / f"{frm}.frm.frames/sequence-00"
        frames = sorted(directory.glob("frame-*.png")) if directory.exists() else []
        if not frames:
            continue
        meta = load_json(root / f"{frm}.frm.json")
        fps = max(1, int(meta["header"].get("effective_frames_per_second", 10)))
        images = [Image.open(path).convert("RGBA") for path in frames]
        name = f"{en} {zh} - {label}动画（{frm}）.gif"
        images[0].save(attachments / name, save_all=True, append_images=images[1:], duration=round(1000/fps), loop=0, disposal=2)
        animation_rows.append((label, name))
    if animation_rows:
        body = ["## 头像动画", ""]
        for label, name in animation_rows:
            body.extend([f"### {label}", "", f"![[{name}|300]]", ""])
        body.append("动画按各 FRM 记录的有效帧率播放导出原始帧，没有补帧或重绘。")
        sections.append("\n".join(body))
    return "\n\n".join(sections)


def task_association(oid: int) -> str:
    if oid == 856:
        return "# 任务关联\n\n发起并结算[[Become an Initiate 加入兄弟会（发起人 ID 856）|加入兄弟会]]：要求玩家从闪光之地带回能证明进入遗迹的物件。"
    if oid == 2275:
        return "# 任务关联\n\n发起并结算[[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）|从哈勃城救出新成员]]；任务现场位于哈勃城旧城区，奖励装备由迈克尔发放。"
    if oid == 1876:
        return "# 任务关联\n\n在[[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）|从哈勃城救出新成员]]完成后负责发放获准的装备奖励。"
    return ""


def character_note(repo: Path, vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path) -> tuple[str, str, bool]:
    oid = int(obj["object_id"])
    en, zh, identity, named = character_identity(obj, proto_zh)
    title = f"{en} {zh}（ID {oid}）"
    full_name = f"素材直接提供姓名 {en}" if named else "普通人物类别或职务名称，不是专名"
    script = script_stem(obj)
    resource_line = f"resource_script: {script}.INT\n" if script else ""
    sprite = (f"""## 地图人物精灵

![[{sprite_filename}|160]]

该图取自 `{art_name}`，使用地图对象记录的方向 {obj['rotation']} 与第 0 帧；这是地图精灵，不是对话头像。"""
              if sprite_filename else "## 地图人物精灵\n\n资源索引指向的人物 FRM 当前没有可用导出帧，因此不借用其他人物造型。")
    aliases = [f"Brotherhood 钢铁兄弟会 - {en} {zh}", f"{en} {zh}"]
    alias_lines = "\n".join(f"  - \"{a}\"" for a in aliases)
    sections = [f"""---
title: "{title}"
aliases:
{alias_lines}
tags: [辐射1, 人物, 地点, 钢铁兄弟会]
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
| 全名 | {full_name} |
| 游戏观察文字 | {md(observation(repo, obj, proto, critter_messages))} |

# 地图信息

![[{map_filename}|900]]

橙色轮廓为本页人物，绿色轮廓为本层其他人物；相同类别通过地图对象 ID 区分。

| 属性 | 值 |
|---|---|
| 出现地点 | [[Brotherhood 钢铁兄弟会\\|钢铁兄弟会]] |
| 所属区域 | [[{region.title}]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | {region.elevation} |
| 地图对象 ID | {oid} |
| 人物原型 ID | {obj['prototype']['list_index']} |
| 地图格 | {obj['tile']}（{obj['tile_x']}, {obj['tile_y']}） |
| 朝向 | {obj['rotation']} |
| 人物脚本 | `{script}.INT` |
| 人物形象 | `{art_name}` |

# 形象

{sprite}

{head_assets(repo, attachments, en, zh, script)}""", game_data(obj, proto),
        inventory_section(obj, lookup, item_messages, note_index)]
    topics = topic_records(repo, script)
    if topics:
        sections.append(render_topic_section(topics))
    dialogue = dialogue_section(repo, obj)
    if dialogue:
        sections.append(dialogue)
    sections.append(f"# 身份与处境\n\n{identity}")
    task = task_association(oid)
    if task:
        sections.append(task)
    return "\n\n".join(sections).rstrip() + "\n", title, named


def inventory_rows(region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                   item_messages: dict, note_index: dict, character_titles: dict[int, str]) -> tuple[list[str], list[str], list[str]]:
    carried, ground, containers = [], [], []
    for obj in characters:
        if not obj.get("inventory"):
            continue
        items = []
        quantities = []
        for entry in obj["inventory"]:
            _, en, zh = item_data(entry["item"], lookup, item_messages)
            items.append(item_link(en, zh, note_index)); quantities.append(str(entry["quantity"]))
        title = character_titles[int(obj["object_id"])]
        carried.append(f"| 随身库存 | {'<br>'.join(items)} | [[{title}\\|{short_character_title(title)}]] | {'<br>'.join(quantities)} |")
    for obj in objects:
        if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0:
            continue
        kind, en, zh = item_data(obj, lookup, item_messages)
        name = item_link(en, zh, note_index)
        location = f"对象 ID {obj['object_id']}；tile {obj['tile']}"
        if obj["prototype"].get("subtype_name") == "container":
            contents = []
            for entry in obj.get("inventory", []):
                _, ien, izh = item_data(entry["item"], lookup, item_messages)
                contents.append(f"{item_link(ien, izh, note_index)} ×{entry['quantity']}")
            containers.append(f"| {name}（{location}） | {'<br>'.join(contents) if contents else '空'} |")
        else:
            ground.append(f"| 地面物品 | {name} | {location} | 1 |")
    return carried, ground, containers


def people_tables(characters: list[dict], character_titles: dict[int, str], named_ids: set[int]) -> str:
    lines = []
    for label, wanted in (("专名人物", True), ("普通人物", False)):
        selected = [o for o in characters if (int(o["object_id"]) in named_ids) == wanted]
        lines.extend([f"### {label}", ""])
        if not selected:
            lines.extend(["完整对象清点没有发现此类人物。", ""]); continue
        lines.extend(["| 序号 | 地图对象 ID | 人物 | 人物脚本 |", "|---:|---:|---|---|"])
        for i, obj in enumerate(sorted(selected, key=lambda x: int(x["object_id"])), 1):
            oid = int(obj["object_id"]); title = character_titles[oid]
            lines.append(f"| {i} | {oid} | [[{title}\\|{short_character_title(title)}]] | `{script_stem(obj)}.INT` |")
        lines.append("")
    return "\n".join(lines).rstrip()


def write_region_page(vault_dir: Path, region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                      item_messages: dict, note_index: dict, character_titles: dict[int, str], named_ids: set[int]) -> None:
    region_dir = vault_dir / region.directory
    map_file = f"{region.title}地图（人物与物品标注，活动区域裁切）.png"
    if region.map_name == "BRODEAD":
        map_note = "本图为毁坏状态的地表入口；该地图没有人物、地面物品或容器，因此不附人物/物品标签。"
    else:
        map_note = "绿色轮廓与标签表示人物，黄色轮廓与标签表示地面物品和容器；容器标签列出直接库存。"
    service_rows = [f"| {a} | {b} | {c} |" for a, b, c in region.services] or ["| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |"]
    carried, ground, containers = inventory_rows(region, characters, objects, lookup, item_messages, note_index, character_titles)
    item_rows = carried + ground
    if not item_rows:
        item_rows = ["| — | — | — | 0 |"]
    if not containers:
        containers = ["| — | 本区域没有容器。 |"]
    tasks = []
    if region.title == "Entrance 入口":
        tasks.append("| [[Become an Initiate 加入兄弟会（发起人 ID 856）\\|加入兄弟会]] | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）\\|Cabbot 卡波特]] | 本区域发起与结算。 |")
    if region.title == "Level 1 第一层":
        tasks.append("| [[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）\\|从哈勃城救出新成员]] | [[Brotherhood 钢铁兄弟会 - Talus 塔鲁斯（ID 2275）\\|Talus 塔鲁斯]] | 本区域发起与结算；营救现场在哈勃城旧城区。 |")
    if not tasks:
        tasks = ["| — | — | 本区域没有独立的 Pip-Boy 任务发起项。 |"]
    page = f"""---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, 钢铁兄弟会]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[Brotherhood 钢铁兄弟会\\|Brotherhood 钢铁兄弟会]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

城镇海报允许从世界地图界面直接选择该区域。相邻楼层是否在当前剧情状态下开放仍由地堡脚本和门禁控制，不能只根据海报按钮推定。

## 地图

![[{map_file}|900]]

{map_note} 图片是地图保存状态的静态快照，不执行人物移动、战斗、脚本生成对象或门的运行时变化。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(service_rows)}

## 人物

{people_tables(characters, character_titles, named_ids)}

## 物品

下表区分人物随身库存与地面顶层物品。容器库存只在“容器”章节展开；静态库存不代表任意剧情时刻的实时状态。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 容器 | 直接库存 |
|---|---|
{chr(10).join(containers)}

## 任务

| 任务名 | 发起人 | 本区域中的环节 |
|---|---|---|
{chr(10).join(tasks)}
"""
    (region_dir / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_initiate_task(vault_dir: Path) -> None:
    task_dir = vault_dir / "Entrance 入口/任务"
    task_dir.mkdir(parents=True, exist_ok=True)
    page = """---
title: "Become an Initiate 加入兄弟会（发起人 ID 856）"
aliases: ["Become an Initiate", "加入兄弟会"]
tags: [辐射1, 任务, 钢铁兄弟会, 闪光之地]
quest_giver_map_object_id: 856
---

# Become an Initiate 加入兄弟会

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | Become an Initiate. |
| 当前中文 | 加入兄弟会。 |

## 任务概览

| 属性 | 内容 |
|---|---|
| Pip-Boy 分类 | Brotherhood 钢铁兄弟会 |
| Pip-Boy 目标 | Become an Initiate. / 加入兄弟会。 |
| 任务链上第一个发起人 | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）\\|Cabbot 卡波特]]（地图对象 ID 856） |
| 接取区域 | [[Entrance 入口\\|入口]] |
| 目标地点 | [[The Glow 闪光之地\\|闪光之地]] |
| 结算区域 | [[Entrance 入口\\|入口]] |

## 任务背景

卡波特告诉玩家，高级元老不允许任何人直接加入。入会试炼要求前往南方的古代机构遗迹，进入辐射严重的设施，并带回能证明自己确实到过内部的物件。

## 流程

1. 在钢铁兄弟会入口向卡波特表示希望加入。
2. 接受前往闪光之地遗迹的试炼；Pip-Boy 加入“加入兄弟会”。
3. 从遗迹内部取得可被卡波特识别的物件。
4. 返回入口并把物件交给卡波特。
5. 卡波特开启地堡入口，玩家成为兄弟会新兵，并获得 2000 点经验值。

## 人物与区域

| 人物 | 地图对象 ID | 所在区域 | 作用 |
|---|---:|---|---|
| [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）\\|Cabbot 卡波特]] | 856 | [[Entrance 入口\\|入口]] | 发起、检查物件、开启入口并结算。 |

## 资源依据

- `PIPBOY.MSG` 770–771：Brotherhood / Become an Initiate。
- `CABBOT.INT` 及消息 114–130、157–168、232：说明试炼、检查返回物件、开启入口和 2000 点经验奖励。
- 任务目标不是“随便带回任意物品”；卡波特脚本会区分能否证明进入遗迹的物件。
"""
    (task_dir / "Become an Initiate 加入兄弟会（发起人 ID 856）.md").write_text(page, encoding="utf-8")


def write_homepage(vault_dir: Path, region_character_data: dict[str, list[dict]], character_titles: dict[int, str],
                   region_objects: dict[str, tuple[list[dict], dict]], item_messages: dict, note_index: dict) -> None:
    region_rows, named_lines, generic_lines, all_items, all_containers = [], [], [], [], []
    named_ids = set(NAMED)
    for region in REGIONS:
        chars = region_character_data[region.title]
        region_rows.append(f"| [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` | {region.elevation} | {len(chars)} | {region.description.split('。')[0]}。 |")
        named = [o for o in chars if int(o["object_id"]) in named_ids]
        generic = [o for o in chars if int(o["object_id"]) not in named_ids]
        named_lines.extend([f"| [[{region.title}\\|{region.chinese}]] | {int(o['object_id'])} | [[{character_titles[int(o['object_id'])]}\\|{short_character_title(character_titles[int(o['object_id'])])}]] |" for o in named])
        generic_lines.extend([f"| [[{region.title}\\|{region.chinese}]] | {int(o['object_id'])} | [[{character_titles[int(o['object_id'])]}\\|{short_character_title(character_titles[int(o['object_id'])])}]] |" for o in generic])
        objects, lookup = region_objects[region.title]
        for obj in chars:
            owner = f"[[{character_titles[int(obj['object_id'])]}\\|{short_character_title(character_titles[int(obj['object_id'])])}]]"
            for entry in obj.get("inventory", []):
                kind, en, zh = item_data(entry["item"], lookup, item_messages)
                all_items.append((kind, item_link(en, zh, note_index), region.title, owner, int(entry["quantity"])))
        for obj in objects:
            if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0:
                continue
            kind, en, zh = item_data(obj, lookup, item_messages)
            name = item_link(en, zh, note_index)
            where = f"对象 ID {obj['object_id']}；tile {obj['tile']}"
            if obj["prototype"].get("subtype_name") == "container":
                contents = []
                for entry in obj.get("inventory", []):
                    _, ien, izh = item_data(entry["item"], lookup, item_messages)
                    contents.append(f"{item_link(ien, izh, note_index)} ×{entry['quantity']}")
                all_containers.append((region.title, f"{name}（{where}）", "<br>".join(contents) if contents else "空"))
            else:
                all_items.append((kind, name, region.title, where, 1))
    if not named_lines: named_lines = ["| — | — | — |"]
    if not generic_lines: generic_lines = ["| — | — | — |"]
    item_lines = [f"| {kind} | {name} | [[{region}\\|{region.split()[-1]}]] | {owner} | {qty} |" for kind, name, region, owner, qty in sorted(all_items)]
    container_lines = [f"| [[{region}\\|{region.split()[-1]}]] | {name} | {contents} |" for region, name, contents in all_containers]
    page = f"""---
title: "Brotherhood 钢铁兄弟会"
aliases: ["Brotherhood", "Brotherhood of Steel", "钢铁兄弟会", "钢铁兄弟会总部"]
tags: [辐射1, 地点, 钢铁兄弟会]
world_map_grid: "12,9"
world_map_pixel: "625,475"
---

# Brotherhood 钢铁兄弟会

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图与 Pip-Boy | Brotherhood / 钢铁兄弟会 |
| 城镇海报标题 | Brotherhood of Steel |
| 知识库标题 | Brotherhood 钢铁兄弟会 |
| 资源地图组 | `BROHDENT.MAP`、`BROHD12.MAP`、`BROHD34.MAP`、`BRODEAD.MAP` |

## 地点概览

钢铁兄弟会总部位于世界地图网格 `(12, 9)`、像素坐标约 `(625, 475)`。正常地点由地表入口和四个地堡楼层组成；`BRODEAD.MAP` 是复用入口热点的毁坏状态替代地图，不是海报上的独立第六区域。

入口脚本把这里呈现为严格控制访客的军事组织总部。完成卡波特的入会试炼后，玩家才能稳定进入地堡；内部功能从第一层训练与补给、第二层医疗与教学、第三层研究与维修，一直延伸到第四层的议事和指挥区域。

## 世界地图位置

世界地图网格为 `(12, 9)`，地点锚点像素坐标约为 `(625, 475)`；知识库总地图另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[Brotherhood 钢铁兄弟会城镇地图（区域标注）.png|900]]

海报原图是 `TWNMAP07.FRM`。五个标注点来自游戏城镇地图热点表：入口 `(172,167)`、第一层 `(254,194)`、第二层 `(136,263)`、第三层 `(280,306)`、第四层 `(161,373)`；坐标按原图 453×444 记录。

## 区域与楼层

| 区域 | 资源地图 | elevation | 人物数 | 作用 |
|---|---|---:|---:|---|
{chr(10).join(region_rows)}

## 商店和服务

| 区域 | 商店或服务 | 提供者 | 内容 |
|---|---|---|---|
| [[Entrance 入口\\|入口]] | 访客接待与准入 | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）\\|Cabbot 卡波特]] | 入会试炼、地堡入口开启和访客问答。 |
| [[Level 1 第一层\\|第一层]] | 装备与奖励领取 | [[Brotherhood 钢铁兄弟会 - Michael 迈克尔（ID 1876）\\|Michael 迈克尔]] | 发放获准装备与塔鲁斯任务奖励。 |
| [[Level 2 第二层\\|第二层]] | 医疗与强化手术 | [[Brotherhood 钢铁兄弟会 - Dr. Lorri 罗伊博士（ID 1151）\\|Dr. Lorri 罗伊博士]] | 治疗并讨论满足条件后的强化手术。 |
| [[Level 3 第三层\\|第三层]] | 研究资料 | [[Brotherhood 钢铁兄弟会 - Vree 弗蕾（ID 1419）\\|Vree 弗蕾]] | 历史、磁盘、变种人研究与尸检结论。 |
| [[Level 3 第三层\\|第三层]] | 动力装甲维修 | [[Brotherhood 钢铁兄弟会 - Kyle 凯尔（ID 2282）\\|Kyle 凯尔]] | 处理损坏动力装甲的维修问题。 |

## 地图中的人物

地图对象完整清点得到正常状态下 73 名人物。专名与普通人物分开列出；普通人物即使名称相同，也按地图对象 ID 逐个落页。

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_lines)}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_lines)}

## 地图中的物品

下表汇总人物随身库存和地图顶层物品。它们是 MAP 保存状态的静态数据，不等同于任意剧情时刻的实时库存。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(item_lines) if item_lines else '| — | — | — | — | 0 |'}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_lines) if container_lines else '| — | — | 无容器。 |'}

## 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 | 经过区域 | 简短目标 |
|---|---|---|---|---|
| [[Become an Initiate 加入兄弟会（发起人 ID 856）\\|Become an Initiate 加入兄弟会]] | [[Brotherhood 钢铁兄弟会 - Cabbot 卡波特（ID 856）\\|Cabbot 卡波特]]（ID 856） | [[Entrance 入口\\|入口]] | [[The Glow 闪光之地\\|闪光之地]]、[[Entrance 入口\\|入口]] | 从古代遗迹内部带回证明，成为兄弟会新兵。 |
| [[Rescue Initiate from the Hub 从哈勃城救出新成员（发起人 ID 2275）\\|Rescue Initiate from the Hub 从哈勃城救出新成员]] | [[Brotherhood 钢铁兄弟会 - Talus 塔鲁斯（ID 2275）\\|Talus 塔鲁斯]]（ID 2275） | [[Level 1 第一层\\|第一层]] | [[Old Town 旧城区\\|哈勃城旧城区]]、[[Level 1 第一层\\|第一层]] | 营救被绑架的兄弟会成员并向塔鲁斯回报。 |

## 位置线索与来源边界

- 世界地图数据直接给出网格和像素坐标；城镇海报热点直接给出五个正常区域的按钮坐标。
- 迦克镇的 Ismarc 伊斯马克说兄弟会位于当地西北方向、相距数日，并声称只有商队获准进入。这是人物说法；实际入口脚本还允许完成试炼的玩家进入。
- 区域人物、物品和容器来自 MAP 对象清点；对话、身份与任务条件来自对应 INT 脚本和当前中文消息资源。
"""
    (vault_dir / "Brotherhood 钢铁兄弟会.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    vault = args.vault_root.resolve()
    vault_dir = vault / "地点/Brotherhood 钢铁兄弟会"
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = build_note_index(vault)
    game = repo / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = message_groups(game / "PRO_CRIT.json")
    item_messages = message_groups(game / "PRO_ITEM.json")
    region_character_data, region_objects, character_titles = {}, {}, {}
    named_ids = set(NAMED)

    (vault_dir / "attachments").mkdir(exist_ok=True)
    shutil.copyfile(repo / "docs/assets/brotherhood-town-map-annotated.png", vault_dir / "attachments/Brotherhood 钢铁兄弟会城镇地图（区域标注）.png")

    for region in REGIONS:
        region_dir = vault_dir / region.directory
        attachments = region_dir / "attachments"
        people = region_dir / "人物"
        named_dir = people / "Named Characters 专名人物"
        generic_dir = people / "Generic Characters 普通人物"
        people_attachments = people / "attachments"
        for path in (attachments, named_dir, generic_dir, people_attachments):
            path.mkdir(parents=True, exist_ok=True)
        map_doc = load_json(repo / f"workspace/output/maps/master/MAPS/{region.map_name}/{region.map_name}.json")
        lookup = proto_lookup(map_doc)
        objects = [o for o in map_doc["objects"]["entries"] if int(o.get("elevation_group", -1)) == region.elevation]
        characters = [o for o in objects if o.get("prototype", {}).get("type") == "critter" and int(o.get("tile", -1)) >= 0]
        region_character_data[region.title] = characters
        region_objects[region.title] = (objects, lookup)

        render_root = repo / "workspace/output/maps-rendered" / region.map_name
        region_map_src = render_root / f"elevation-{region.elevation}-brotherhood-region-cropped.png"
        region_map_name = f"{region.title}地图（人物与物品标注，活动区域裁切）.png"
        shutil.copyfile(region_map_src, attachments / region_map_name)
        if region.map_name != "BRODEAD":
            full_src = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png"
            shutil.copyfile(full_src, attachments / f"Brotherhood 钢铁兄弟会地图（{region.map_name} elevation {region.elevation}，人物与物品高亮）.png")
        else:
            shutil.copyfile(render_root / "elevation-0-floor-walls-doors-scenery-items.png", attachments / "Brotherhood 钢铁兄弟会地图（BRODEAD elevation 0，毁坏入口）.png")

        profile_maps = render_profile_maps(repo, region, characters, people_attachments) if characters else {}
        render_doc = (load_json(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json") if characters else {})
        render_by_id = {int(item["object_id"]): item for item in render_doc.get("critters", [])}
        for obj in characters:
            oid = int(obj["object_id"])
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            proto_en, proto_zh = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
            en, zh, _, named = character_identity(obj, proto_zh)
            render_entry = render_by_id[oid]
            frm_stem = Path(render_entry["filename"]).stem.upper()
            art_name = f"{frm_stem}.FRM"
            source_frame = find_critter_frame(repo, render_entry["filename"], int(obj["rotation"]))
            sprite_name = None
            if source_frame:
                sprite_name = f"{en} {zh}（ID {oid}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
                shutil.copyfile(source_frame, people_attachments / sprite_name)
            text, title, is_named = character_note(repo, vault, region, obj, proto, proto_en, proto_zh, lookup,
                                                    item_messages, critter_messages, note_index, profile_maps[oid],
                                                    sprite_name, art_name, people_attachments)
            filename = f"Brotherhood 钢铁兄弟会 - {title}.md"
            target = (named_dir if is_named else generic_dir) / filename
            if target.exists() and not args.overwrite:
                raise FileExistsError(target)
            target.write_text(text, encoding="utf-8")
            character_titles[oid] = f"Brotherhood 钢铁兄弟会 - {title}"

    write_initiate_task(vault_dir)
    for region in REGIONS:
        objects, lookup = region_objects[region.title]
        write_region_page(vault_dir, region, region_character_data[region.title], objects, lookup, item_messages,
                          note_index, character_titles, named_ids)
    write_homepage(vault_dir, region_character_data, character_titles, region_objects, item_messages, note_index)
    sync_tree(vault_dir, repo)
    total = sum(len(v) for v in region_character_data.values())
    print(f"generated Brotherhood package: {len(REGIONS)} regions, {total} character notes, 2 quest links/pages")


if __name__ == "__main__":
    main()
