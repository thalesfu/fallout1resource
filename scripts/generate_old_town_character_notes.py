#!/usr/bin/env python3
"""Generate HUBOLDTN elevation-0 character notes and profile assets."""

from __future__ import annotations

import argparse
import csv
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
CROP_BOX = (1750, 1000, 4650, 2450)


@dataclass(frozen=True)
class Character:
    english: str
    chinese: str
    identity: str
    named: bool = False
    task: str | None = None
    services: str | None = None
    knowledge: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()


CHARACTERS: dict[int, Character] = {
    46: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    178: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    223: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    229: Character("Merchant", "商人", "旧城区的一名居民；人物原型名称为 Merchant 商人。"),
    271: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    351: Character(
        "Jacob",
        "雅各布",
        "旧城区的高级军火商人。他自称一直住在附近，过去属于原子产业工人协会；离开组织后在哈勃城定居，并说自己曾多次被警察驱逐。当前中文观察文字将他的名字写作“雅克布”。",
        named=True,
        services="经营高级军火交易，明确提到狙击步枪、火焰喷射器燃料和盖革计数器。实际交易库存由地图外的 JakeDesk 雅各布交易箱提供，不能当作人物随身物品。",
        knowledge=(
            "介绍 DKS 狙击步枪的口径、枪管和扳机改装。",
            "说明盖革计数器用于查看人体积累的辐射量，并谈及辐射与去辐射药。",
            "称万斯可能提供去辐射药，并让玩家报上雅各布的名字。",
            "提到晒骨场的军火商和钢铁兄弟会可能拥有火力更强的装备。",
        ),
        uncertainties=("素材只提供 Jacob，没有姓氏。", "中文资源同时出现“雅各布”和“雅克布”两种译名。"),
    ),
    517: Character("Junkie", "瘾君子", "旧城区万斯住处附近的一名瘾君子。"),
    541: Character(
        "Justin",
        "贾斯廷",
        "[[Hub 哈勃城 - Vance 万斯（ID 654）|Vance 万斯]]的两名守卫之一。万斯在对话中明确点名 Justin 和 Chad；人物原型 ID 238 将本对象确定为 Justin。当前中文对话把名字写作“贾斯汀”。",
        named=True,
        uncertainties=("素材只提供 Justin，没有姓氏。", "中文资料同时出现“贾斯廷”和“贾斯汀”两种译名。"),
    ),
    576: Character("Junkie", "瘾君子", "旧城区万斯住处附近的一名瘾君子。"),
    641: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    654: Character(
        "Vance",
        "万斯",
        "旧城区的一名药品商人。他拒绝详细介绍自己，只说名字是万斯；Justin 贾斯廷和 Chad 查德负责保证屋内无人惹麻烦。",
        named=True,
        services="经营药品交易。实际交易库存由地图外的 VanceBox 万斯交易箱提供，不能当作人物随身物品。",
        knowledge=("明确说 Justin 贾斯廷和 Chad 查德是维持屋内秩序的两名守卫。", "拒绝解释后方房间中的其他人，只称他们是自己的朋友。"),
        uncertainties=("素材只提供 Vance，没有姓氏。",),
    ),
    756: Character("Police", "警察", "旧城区的一名哈勃城警察。"),
    790: Character(
        "Chad",
        "查德",
        "[[Hub 哈勃城 - Vance 万斯（ID 654）|Vance 万斯]]的两名守卫之一。万斯在对话中明确点名 Justin 和 Chad；人物原型 ID 246 将本对象确定为 Chad。",
        named=True,
        uncertainties=("素材只提供 Chad，没有姓氏。",),
    ),
    853: Character("Peasant", "农民", "旧城区的一名居民；人物原型名称为 Peasant 农民。"),
    950: Character("Merchant", "商人", "旧城区的一名居民；人物原型名称为 Merchant 商人。"),
    1124: Character(
        "Rutger",
        "罗格尔",
        "旧城区地图对象使用 Rutger 罗格尔的人物原型，但在这里执行绑匪看守脚本，参与看守失踪的钢铁兄弟会成员。此对象不是中心区商人远行商队办公室中的另一个地图实例。",
        named=True,
        task="在“营救哈勃城中的钢铁兄弟会成员”任务中属于囚禁现场的绑匪一方。",
        uncertainties=("素材只提供 Rutger，没有姓氏。",),
    ),
    1176: Character("Guard", "警卫（绑匪）", "旧城区绑匪团伙的一名警卫，负责看守失踪的钢铁兄弟会成员。", task="在“营救哈勃城中的钢铁兄弟会成员”任务中属于囚禁现场的绑匪一方。"),
    1239: Character("Lowly Peasant", "贫民", "旧城区的一名贫民。"),
    1252: Character(
        "Missing Brotherhood Initiate",
        "失踪的钢铁兄弟会成员",
        "被旧城区绑匪囚禁并殴打的钢铁兄弟会成员。他说自己已经被关押数周，可能接近一个月；获救后会请玩家向 Talus 塔鲁斯报平安。",
        task="“营救哈勃城中的钢铁兄弟会成员”任务的营救目标。玩家解救他后，可以向 Talus 塔鲁斯回报。",
        knowledge=(
            "说钢铁兄弟会位于哈勃城西南方向、西边山脉一带。",
            "提到自己在哈勃城有朋友，可以在获救后照顾他。",
            "听说附近有小偷公会，并猜测绑匪可能因为离他们的地盘太近而准备搬走。",
            "听说旧城区发生了不好的事情，认为当地有人鬼鬼祟祟。",
        ),
    ),
    1303: Character(
        "Vinnie",
        "维尼",
        "旧城区地图对象使用 Vinnie 维尼的人物原型，但在这里执行绑匪看守脚本，参与看守失踪的钢铁兄弟会成员。",
        named=True,
        task="在“营救哈勃城中的钢铁兄弟会成员”任务中属于囚禁现场的绑匪一方。",
        uncertainties=("素材只提供 Vinnie，没有姓氏。",),
    ),
    1307: Character("Guard", "警卫（绑匪）", "旧城区绑匪团伙的一名警卫，负责看守失踪的钢铁兄弟会成员。", task="在“营救哈勃城中的钢铁兄弟会成员”任务中属于囚禁现场的绑匪一方。"),
    1367: Character("Lowly Peasant", "贫民", "旧城区的一名贫民。"),
    1406: Character("Boy", "男孩", "旧城区的一名男孩。"),
    1474: Character("Lowly Peasant", "贫民", "旧城区的一名贫民。"),
    1478: Character("Peasant", "农民", "旧城区的一名居民；人物原型名称为 Peasant 农民。"),
    1502: Character("Lowly Peasant", "贫民", "旧城区的一名贫民。"),
    1633: Character("Harold", "哈罗德", "旧城区居民。", named=True),
    1748: Character("Boy", "男孩", "旧城区的一名男孩。"),
    1800: Character("Boy", "男孩", "旧城区的一名男孩。"),
    1939: Character(
        "Slappy",
        "斯来匹",
        "旧城区的一名居民，说话方式跳跃而混乱。他认识 Harold 哈罗德，并能在死亡爪调查推进后带玩家前往死亡爪巢穴。当前中文观察文字把名字写作“斯莱匹”。",
        named=True,
        task="在死亡爪调查中提供带路环节。玩家先从 Beth 贝斯或 Harold 哈罗德取得相应线索后，可以让他带路前往死亡爪巢穴。",
        knowledge=("知道 Harold 哈罗德会讲故事。", "称死亡爪很吓人，并表示可以带玩家去看它。"),
        uncertainties=("素材只提供 Slappy，没有姓氏。", "中文资源同时出现“斯来匹”和“斯莱匹”两种译名。"),
    ),
}


PROC_ORDER = {
    "HUBJAKE": ["Jake01", "Jake02", "Jake03", "Jake04", "Jake05", "Jake06", "Jake07", "Jake08", "Jake12", "Jake09", "Jake10", "Jake16", "Barter"],
    "VANCE": ["Vance01", "Vance02", "Vance03", "Vance04", "Vance06", "Vance07", "Vance08", "Vance09", "Vance10", "Vance11", "Vance12", "Barter"],
    "SLAPPY": ["Slappy01", "Slappy02", "Slappy03", "Slappy04", "Slappy05", "Slappy06", "Slappy07", "Slappy08", "Slappy09", "Slappy11"],
    "MISSBRO": ["Brother00", "Brother01", "Brother02", "Brother03", "Brother04", "Brother05", "Brother06", "Brother07", "Brother08", "Brother09", "Brother10", "Brother11", "Brother12"],
    "CHILD": ["child01", "child02", "child03", "child04", "child05", "child06"],
}

PROC_LABELS = {
    "Jake01": "初次交谈",
    "Jake02": "询问出售的商品",
    "Jake03": "询问净水芯片",
    "Jake04": "询问个人经历",
    "Jake05": "询问狙击步枪",
    "Jake06": "询问盖革计数器",
    "Jake07": "继续询问辐射",
    "Jake08": "询问盖革计数器的用法",
    "Jake09": "再次交谈，关系中立或友好",
    "Jake10": "再次交谈，关系较差",
    "Jake12": "询问去辐射药",
    "Jake16": "询问火力更强的装备",
    "Vance01": "初次交谈",
    "Vance02": "询问身份",
    "Vance03": "没有说明购买意图",
    "Vance04": "表示没事",
    "Vance06": "完成一次交易后继续交谈",
    "Vance07": "表示不喜欢他的生意",
    "Vance08": "询问 Justin 和 Chad",
    "Vance09": "询问后方房间的人",
    "Vance10": "向守卫打招呼后",
    "Vance11": "不受欢迎时",
    "Vance12": "关系较差时",
    "Slappy01": "交谈开场",
    "Slappy02": "低智力角色回应月亮",
    "Slappy03": "提到 Harold 的死亡爪消息",
    "Slappy04": "询问他在做什么",
    "Slappy05": "询问他有什么问题",
    "Slappy06": "追问死亡爪",
    "Slappy07": "请求带路",
    "Slappy08": "继续询问他的活动",
    "Slappy09": "威胁他",
    "Slappy11": "从 Beth 处获得线索",
    "Brother00": "获救后的首次交谈",
    "Brother01": "询问钢铁兄弟会",
    "Brother02": "谎称自己来自钢铁兄弟会",
    "Brother03": "表示很高兴帮忙",
    "Brother04": "询问他的身体状况",
    "Brother05": "说明是 Talus 派来的",
    "Brother06": "说明 Talus 知道他的去向",
    "Brother07": "自称救援只是举手之劳",
    "Brother08": "继续交谈",
    "Brother09": "表示很高兴找到他",
    "Brother10": "称救援只是运气",
    "Brother11": "声称自己刚加入钢铁兄弟会",
    "Brother12": "质疑他是否了解情况",
    "child01": "一种交谈开场",
    "child02": "询问父母",
    "child03": "低智力回应",
    "child04": "另一种交谈开场",
    "child05": "回答会杀人",
    "child06": "回答不会杀人",
    "Barter": "交易",
}

TARGET_LABELS = {
    **PROC_LABELS,
    "Jake13": "结束对话",
    "Jake14": "结束对话，关系恶化",
    "Jake15": "开始战斗",
    "JakeEnd": "结束对话",
    "Vance04": "结束对话",
    "Vance02a": "根据玩家的介绍或状态决定进入交易或拒绝接待",
    "Vance05": "交易",
    "Vance11a": "缓和关系并回到交易话题",
    "Vance13": "开始战斗",
    "Vance14": "结束对话",
    "Vance15": "结束对话",
    "VanceEnd": "结束对话",
    "SlappyEnd": "结束对话",
    "SlappyClaw": "前往死亡爪巢穴",
    "BrotherEnd": "结束对话",
    "childend": "结束对话",
}

AUTO_TARGETS = {"Brother01": "Brother08", "Brother06": "Brother08", "Brother07": "Brother08"}

ITEM_TYPES = {
    "armor": "装甲",
    "container": "容器",
    "drug": "药品",
    "weapon": "武器",
    "ammo": "弹药",
    "misc": "杂项",
    "key": "钥匙",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def walk_objects(value):
    if isinstance(value, dict):
        if "object_id" in value and "prototype" in value and "tile" in value:
            yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def message_groups(path: Path) -> dict[int, tuple[str, str]]:
    doc = load_json(path)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for entry in doc["entries"]:
        grouped[int(entry["number"])].append(entry)
    result = {}
    for number, entries in grouped.items():
        effective = next((e["text"] for e in entries if e.get("effective")), entries[-1]["text"])
        source = entries[0]["text"]
        result[number] = (source.replace("\n", " "), effective.replace("\n", " "))
    return result


def effective_messages(path: Path) -> dict[int, str]:
    return {number: effective for number, (_, effective) in message_groups(path).items()}


def find_case_insensitive(directory: Path, name: str) -> Path | None:
    wanted = name.casefold()
    for path in directory.glob("*.json"):
        if path.stem.casefold() == wanted:
            return path
    return None


def markdown_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def dialogue_rows(repo: Path, script: str) -> dict[str, list[dict]]:
    path = repo / "workspace/output/scripts/master/SCRIPTS" / f"{script}.messages.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["procedure_name"]].append(row)
    return grouped


def structured_dialogue(repo: Path, script: str) -> str:
    grouped = dialogue_rows(repo, script)
    order = PROC_ORDER[script]
    lines = [
        "## 对话",
        "",
        "以下按实际交谈阶段整理。人物台词和玩家选项采用当前中文素材；“→”后的文字表示下一分支。",
        "",
        "| 相处阶段或当前回应 | 人物台词 | 玩家选项与分支 |",
        "|---|---|---|",
    ]
    for proc in order:
        rows = grouped.get(proc, [])
        npc = unique([markdown_text(row["msg_text"]) for row in rows if row["call"] in {"reply", "message"}])
        options = []
        for row in rows:
            if row["call"] != "intelligence_option" or not row["msg_text"]:
                continue
            prefix = "低智力选项：" if row["intelligence"].startswith("-") else ""
            target = TARGET_LABELS.get(row["target_procedure_name"], row["target_procedure_name"] or "结束对话")
            options.append(f"{prefix}**{markdown_text(row['msg_text'])}** → {target}")
        if not options and proc in AUTO_TARGETS:
            options.append(f"自动进入“{TARGET_LABELS[AUTO_TARGETS[proc]]}”")
        elif not options:
            options.append("结束对话")
        lines.append(
            f"| {PROC_LABELS[proc]} | {'<br><br>'.join(npc) if npc else '—'} | {'<br>'.join(options)} |"
        )
    return "\n".join(lines)


def random_dialogue(repo: Path, script: str) -> str:
    data_dir = repo / "workspace/output/text/data/TEXT/ENGLISH/DIALOG"
    message_path = find_case_insensitive(data_dir, script)
    messages = effective_messages(message_path) if message_path else {}
    if script == "JUNKIE":
        groups = [("交谈时可能出现", range(101, 104))]
    elif script == "GENSKAG":
        groups = [("白天交谈时可能出现", range(101, 110)), ("夜间交谈时可能出现", range(110, 117))]
    elif script == "LOSER":
        groups = [("请求食物时可能出现", range(100, 107))]
    elif script == "HUBCAPTR":
        groups = [("连续交谈", range(101, 105)), ("进入敌对或战斗时可能喊出", range(105, 110))]
    elif script == "GENCOP":
        groups = [
            ("一般警告、声望与任务状态台词", range(101, 120)),
            ("一般巡逻与哈勃城状态台词", range(120, 144)),
            ("旧城区及治安状态台词", range(144, 164)),
        ]
    else:
        return ""
    lines = [
        "## 对话",
        "",
        "该人物使用共用脚本，没有树状玩家选项；交谈时由脚本从相应状态的台词中选取。",
    ]
    for title, numbers in groups:
        values = [messages[number] for number in numbers if number in messages]
        if not values:
            continue
        lines.extend(["", f"### {title}", ""])
        lines.extend(f"- {markdown_text(value)}" for value in values)
    return "\n".join(lines)


def script_dialogue(repo: Path, script_filename: str | None) -> str:
    if not script_filename:
        return ""
    script = Path(script_filename).stem.upper()
    if script in PROC_ORDER:
        return structured_dialogue(repo, script)
    if script in {"GENCOP", "GENSKAG", "JUNKIE", "LOSER", "HUBCAPTR"}:
        return random_dialogue(repo, script)
    return ""


def prototype_names(repo: Path) -> tuple[dict[int, tuple[str, str]], dict[int, tuple[str, str]]]:
    game = repo / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter = message_groups(game / "PRO_CRIT.json")
    item = message_groups(game / "PRO_ITEM.json")
    return critter, item


def prototype_description(proto: dict, messages: dict[int, tuple[str, str]]) -> tuple[str, str]:
    message_id = int(proto["message_id"])
    name = messages.get(message_id, ("", ""))
    description = messages.get(message_id + 1, ("", ""))
    return name[1], description[1]


def observation_text(repo: Path, script_filename: str | None, proto: dict, critter_messages) -> str:
    if script_filename:
        script = Path(script_filename).stem.upper()
        rows = dialogue_rows(repo, script)
        values = [
            row["msg_text"]
            for row in rows.get("look_at_p_proc", [])
            if row["msg_text"]
        ]
        if values:
            return values[0]
    _, description = prototype_description(proto, critter_messages)
    return description or "素材没有提供独立观察文字。"


def item_display(item_obj: dict, proto_lookup: dict, item_messages) -> tuple[str, str, str]:
    item_proto = proto_lookup[("item", item_obj["prototype"]["list_index"])]
    english, chinese = item_messages.get(int(item_proto["message_id"]), ("", ""))
    subtype = item_obj["prototype"].get("subtype_name") or "misc"
    item_type = "瓶盖" if english == "Bottle Caps" or chinese == "瓶盖" else ITEM_TYPES.get(subtype, subtype)
    return item_type, english, chinese


def inventory_markdown(obj: dict, proto_lookup: dict, item_messages) -> str:
    inventory = obj.get("inventory", [])
    lines = ["## 物品信息", ""]
    if not inventory:
        lines.append(f"地图对象 `{obj['object_id']}` 的库存为空。")
        return "\n".join(lines)
    rows = []
    for entry in inventory:
        item_type, english, chinese = item_display(entry["item"], proto_lookup, item_messages)
        rows.append((item_type, english, chinese, int(entry["quantity"])))
    rows.sort(key=lambda row: (row[0], row[1], -row[3]))
    lines.extend(["| 类型 | 英文物品名 | 中文物品名 | 数量 |", "|---|---|---|---:|"])
    for item_type, english, chinese, quantity in rows:
        lines.append(f"| {item_type} | {markdown_text(english)} | {markdown_text(chinese)} | {quantity} |")
    return "\n".join(lines)


def trade_inventory_markdown(character_id: int) -> str:
    if character_id == 351:
        return """
### 交易库存

雅各布的交易库存由地图外的 `JakeDesk` 储物箱提供，包括高级枪械、弹药、装甲、手榴弹、火箭、火焰喷射器燃料和盖革计数器。该容器位于正常活动边界之外，是交易系统库存，不是可在雅各布身上直接取得的随身物品；逐项清单见[[Old Town 旧城区#容器|旧城区容器表]]。
""".strip()
    if character_id == 654:
        return """
### 交易库存

万斯的交易库存由地图外的 `VanceBox` 储物箱提供，包括治疗针、急救包、消辐宁、解毒剂、敏达、壮壮素、辐特宁、狂怒药和超级治疗针。该容器位于正常活动边界之外，是交易系统库存，不是可在万斯身上直接取得的随身物品；逐项清单见[[Old Town 旧城区#容器|旧城区容器表]]。
""".strip()
    return ""


def find_critter_frame(repo: Path, frm_filename: str, rotation: int) -> Path | None:
    frm_name = f"{Path(frm_filename).stem.upper()}.frm"
    frm_dir = repo / "workspace/output/images/critter/ART/CRITTERS" / frm_name
    metadata = frm_dir / f"{frm_name}.json"
    if not metadata.exists():
        return None
    document = load_json(metadata)
    direction = next(item for item in document["directions"] if int(item["index"]) == rotation)
    sequence = int(direction["sequence_index"])
    frame = frm_dir / f"{frm_name}.frames" / f"sequence-{sequence:02d}" / "frame-000.png"
    return frame if frame.exists() else None


def nearest_component(alpha: Image.Image, target: tuple[int, int], radius: int = 96) -> Image.Image | None:
    left = max(0, target[0] - radius)
    top = max(0, target[1] - radius)
    right = min(alpha.width, target[0] + radius + 1)
    bottom = min(alpha.height, target[1] + radius + 1)
    crop = alpha.crop((left, top, right, bottom))
    pixels = crop.load()
    candidates = []
    for y in range(crop.height):
        for x in range(crop.width):
            if pixels[x, y] > 0:
                gx, gy = x + left, y + top
                candidates.append(((gx - target[0]) ** 2 + (gy - target[1]) ** 2, x, y))
    if not candidates:
        return None
    _, start_x, start_y = min(candidates)
    queue = deque([(start_x, start_y)])
    visited = {(start_x, start_y)}
    while queue:
        x, y = queue.popleft()
        for nx in range(max(0, x - 1), min(crop.width, x + 2)):
            for ny in range(max(0, y - 1), min(crop.height, y + 2)):
                if (nx, ny) not in visited and pixels[nx, ny] > 0:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
    component = Image.new("L", alpha.size, 0)
    component_pixels = component.load()
    for x, y in visited:
        component_pixels[x + left, y + top] = 255
    return component


def render_profile_maps(repo: Path, attachments: Path, labels: list[dict]) -> dict[int, str]:
    render_root = repo / "workspace/output/maps-rendered/HUBOLDTN"
    composite = Image.open(render_root / "elevation-0-floor-walls-doors-scenery-items-critters.png").convert("RGBA")
    critters = Image.open(render_root / "elevation-0-critters.png").convert("RGBA")
    alpha = critters.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(5))
    green_outline = ImageChops.subtract(expanded, alpha)
    green_layer = Image.new("RGBA", composite.size, GREEN)
    base = Image.composite(green_layer, composite, green_outline)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font = ImageFont.truetype(str(font_path), 28)
    outputs = {}
    for object_id, character in CHARACTERS.items():
        if object_id == 1633:
            continue
        label = next(item for item in labels if int(item["object_id"]) == object_id)
        canvas = base.copy()
        target = tuple(int(value) for value in label["target_canvas"])
        if not label.get("missing_art"):
            component = nearest_component(alpha, target)
            if component is not None:
                orange_outline = ImageChops.subtract(component.filter(ImageFilter.MaxFilter(7)), component)
                canvas = Image.composite(Image.new("RGBA", canvas.size, ORANGE), canvas, orange_outline)
        draw = ImageDraw.Draw(canvas, "RGBA")
        for current in labels:
            current_id = int(current["object_id"])
            color = ORANGE if current_id == object_id else GREEN
            tx, ty = (int(value) for value in current["target_canvas"])
            left, top, right, bottom = (int(value) for value in current["label_box_canvas"])
            draw.line((tx, ty, (left + right) // 2, bottom if bottom <= ty else top), fill=color, width=1)
            draw.rectangle((left, top, right, bottom), fill=(0, 0, 0, 218), outline=color, width=1)
            text = current["display_name"]
            text_box = draw.textbbox((0, 0), text, font=font, stroke_width=1)
            x = left + max(4, (right - left - (text_box[2] - text_box[0])) // 2)
            y = top + max(2, (bottom - top - (text_box[3] - text_box[1])) // 2) - text_box[1]
            draw.text((x, y), text, font=font, fill="white", stroke_width=1, stroke_fill="black")
        cropped = canvas.crop(CROP_BOX)
        filename = f"Old Town 旧城区地图（人物标注，{character.chinese} ID {object_id}高亮，活动区域裁切）.png"
        cropped.save(attachments / filename, format="PNG", compress_level=9)
        outputs[object_id] = filename
    return outputs


def game_data_markdown(obj: dict, proto: dict) -> str:
    stats = proto["fields"]["base_stats"]
    update = obj.get("update_data", {})
    combat = update.get("combat", {})
    gender = "男性" if stats[34] == 0 else "女性" if stats[34] == 1 else str(stats[34])
    return f"""## 游戏数据

### SPECIAL

| 力量 | 感知 | 耐力 | 魅力 | 智力 | 敏捷 | 幸运 |
|---:|---:|---:|---:|---:|---:|---:|
| {stats[0]} | {stats[1]} | {stats[2]} | {stats[3]} | {stats[4]} | {stats[5]} | {stats[6]} |

### 其他数据

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
| 原型性别 | {gender} |
""".strip()


def aliases(character: Character, object_id: int) -> list[str]:
    if object_id == 1124:
        return [
            "旧城区 - Rutger 罗格尔（ID 1124）",
            "Old Town - Rutger 罗格尔（ID 1124）",
        ]
    if character.named or character.english == "Missing Brotherhood Initiate":
        return [
            f"Hub 哈勃城 - {character.english} {character.chinese}",
            f"{character.english} {character.chinese}",
            character.chinese,
        ]
    return [f"旧城区 - {character.english} {character.chinese}（ID {object_id}）"]


def note_markdown(
    repo: Path,
    character: Character,
    object_id: int,
    obj: dict,
    proto: dict,
    critter_messages,
    item_messages,
    proto_lookup,
    map_filename: str,
    sprite_filename: str | None,
    art_name: str,
) -> str:
    title = f"{character.english} {character.chinese}（ID {object_id}）"
    alias_lines = "\n".join(f"  - {value}" for value in aliases(character, object_id))
    script_filename = obj.get("script_filename")
    resource_line = f"resource_script: {Path(script_filename).stem.upper()}.INT\n" if script_filename else ""
    observation = observation_text(repo, script_filename, proto, critter_messages)
    full_name = (
        f"素材只提供 {character.english}，没有姓氏"
        if character.named
        else "普通人物类别名称，不是专名"
    )
    if character.english == "Missing Brotherhood Initiate":
        full_name = "素材没有提供姓名；这是任务身份描述"
    map_script = Path(script_filename).stem.upper() + ".INT" if script_filename else "无独立人物脚本"
    sprite_section = (
        f"""### 地图人物精灵

![[{sprite_filename}|160]]

这是 `{art_name}` 方向{obj['rotation']}的第0帧，与旧城区地图对象记录的朝向一致。
""".strip()
        if sprite_filename
        else """### 地图人物精灵

资源索引指向的人物 FRM 当前未能导出，因此不借用其他人物造型；位置图只保留该对象的坐标锚点和标签。
""".strip()
    )
    sections = [
        f"""---
title: {title}
aliases:
{alias_lines}
tags:
  - 辐射1
  - 人物
  - 哈勃城
  - 旧城区
map: HUBOLDTN
elevation: 0
map_object_id: {object_id}
prototype_id: {obj['prototype']['list_index']}
map_tile: {obj['tile']}
{resource_line}---

# {character.english} {character.chinese}

## 名称

| 属性 | 内容 |
|---|---|
| 英文名 | {character.english} |
| 中文名 | {character.chinese} |
| 全名 | {full_name} |
| 游戏观察文字 | {markdown_text(observation)} |

## 地图信息

![[{map_filename}|900]]

绿色标出旧城区中的其他人物；橙色标出本人物。相同类别的人物通过地图对象 ID 区分。

| 属性 | 值 |
|---|---|
| 出现地点 | [[Old Town 旧城区\\|旧城区]] |
| 资源地图 | HUBOLDTN.MAP |
| 楼层 | 0 |
| 地图对象 ID | {object_id} |
| 人物原型 ID | {obj['prototype']['list_index']} |
| 地图格 | {obj['tile']} |
| 地图坐标 | X {obj['tile_x']}，Y {obj['tile_y']} |
| 朝向 | {obj['rotation']} |
| 人物脚本 | {map_script} |
| 人物形象 | {art_name} |

## 形象

{sprite_section}

### 对话头像

素材没有为此人物配置独立对话头像。""".strip(),
        game_data_markdown(obj, proto),
        inventory_markdown(obj, proto_lookup, item_messages),
    ]
    trade = trade_inventory_markdown(object_id)
    if trade:
        sections.append(trade)
    if character.services:
        sections.append(f"## 商店与服务\n\n{character.services}")
    topics = topic_records(repo, script_filename or "")
    if topics:
        sections.append(render_topic_section(topics, level=2))
    dialogue = script_dialogue(repo, script_filename)
    if dialogue:
        sections.append(dialogue)
    sections.append(f"## 身份与处境\n\n{character.identity}")
    if character.knowledge:
        sections.append("## 掌握的信息\n\n" + "\n".join(f"- {item}" for item in character.knowledge))
    if character.task:
        sections.append(f"## 任务关联\n\n{character.task}")
    if character.uncertainties:
        sections.append("## 未确定的信息\n\n" + "\n".join(f"- {item}" for item in character.uncertainties))
    return "\n\n".join(sections).rstrip() + "\n"


def main() -> None:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    vault = args.vault_root.resolve()
    people_dir = vault / "地点/Hub 哈勃城/Old Town 旧城区/人物"
    attachments = people_dir / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    map_doc = load_json(repo / "workspace/output/maps/master/MAPS/HUBOLDTN/HUBOLDTN.json")
    render_doc = load_json(repo / "workspace/output/maps-rendered/HUBOLDTN/elevation-0-floor-walls-doors-scenery-items-critters.json")
    labels = render_doc["critter_name_labels"]["labels"]
    all_objects = list(walk_objects(map_doc["objects"]))
    critters = {
        int(obj["object_id"]): obj
        for obj in all_objects
        if obj.get("prototype", {}).get("type") == "critter"
        and int(obj.get("elevation_group", -1)) == 0
        and int(obj.get("tile", -1)) >= 0
    }
    proto_lookup = {(proto["type"], int(proto["list_index"])): proto for proto in map_doc["referenced_prototypes"]}
    critter_messages, item_messages = prototype_names(repo)
    map_files = render_profile_maps(repo, attachments, labels)
    generated = []
    for object_id, character in CHARACTERS.items():
        if object_id == 1633:
            continue
        obj = critters[object_id]
        proto = proto_lookup[("critter", int(obj["prototype"]["list_index"]))]
        render_entry = next(
            (item for item in render_doc["critters"] if int(item["object_id"]) == object_id),
            next(
                (item for item in render_doc["missing_critter_art"] if int(item["object_id"]) == object_id),
                {"base_name": "unknown", "filename": "unknown.frm"},
            ),
        )
        frm_stem = Path(render_entry["filename"]).stem.upper()
        art_name = f"{frm_stem}.FRM"
        source_frame = find_critter_frame(repo, render_entry["filename"], int(obj["rotation"]))
        sprite_filename = None
        if source_frame:
            sprite_filename = f"{character.english} {character.chinese}（ID {object_id}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
            shutil.copyfile(source_frame, attachments / sprite_filename)
        filename = f"Hub 哈勃城 - {character.english} {character.chinese}（ID {object_id}）.md"
        target = people_dir / filename
        if target.exists() and not args.overwrite:
            raise FileExistsError(f"refusing to overwrite {target}")
        target.write_text(
            note_markdown(
                repo,
                character,
                object_id,
                obj,
                proto,
                critter_messages,
                item_messages,
                proto_lookup,
                map_files[object_id],
                sprite_filename,
                art_name,
            ),
            encoding="utf-8",
        )
        generated.append(target)
    expected = set(CHARACTERS) - {1633}
    if set(map_files) != expected or len(generated) != len(expected):
        raise RuntimeError("generated character set does not match expected HUBOLDTN object IDs")
    sync_tree(people_dir, repo)
    print(f"generated {len(generated)} notes and {len(map_files)} focused maps")


if __name__ == "__main__":
    main()
