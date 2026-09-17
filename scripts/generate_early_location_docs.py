#!/usr/bin/env python3
"""Generate Shady Sands, Junktown, or Vault 15 Obsidian location packages."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from fallout1_character_topics import render_topic_section, sync_tree, topic_records


REPO = Path(__file__).resolve().parents[1]
GREEN = (101, 231, 101, 255)
ORANGE = (255, 126, 48, 255)


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bb = import_script("early_location_brotherhood_helpers", "generate_brotherhood_docs.py")
cath = import_script("early_location_cathedral_helpers", "generate_cathedral_docs.py")


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
    task_notes: tuple[tuple[str, str], ...] = ()

    @property
    def title(self) -> str:
        return f"{self.english} {self.chinese}"


@dataclass(frozen=True)
class Task:
    english: str
    chinese: str
    giver_id: int
    giver_name: str
    start_region: str
    summary: str
    steps: str
    related_regions: tuple[str, ...]
    related_scripts: tuple[str, ...]

    @property
    def filename(self) -> str:
        return f"{self.english} {self.chinese}（发起人 ID {self.giver_id}）"


@dataclass(frozen=True)
class Location:
    key: str
    title: str
    english: str
    chinese: str
    poster_number: int
    world_grid: tuple[int, int]
    world_pixel: tuple[int, int]
    discovery_variable: int
    overview: str
    regions: tuple[Region, ...]
    hotspots: tuple[tuple[int, int, int, str, str], ...]
    named_scripts: dict[str, tuple[str, str, str]]
    generic_scripts: dict[str, tuple[str, str, str]]
    creature_scripts: frozenset[str]
    tasks: tuple[Task, ...] = ()
    external_tasks: tuple[tuple[str, str, str], ...] = ()
    aliases: tuple[str, ...] = ()
    heads: dict[str, str] = field(default_factory=dict)


SHADY = Location(
    key="shady-sands", title="Shady Sands 沙荫镇", english="Shady Sands", chinese="沙荫镇",
    poster_number=2, world_grid=(21, 1), world_pixel=(1075, 75), discovery_variable=68,
    overview="沙荫镇由东西两张地面地图组成。西区保存城门、亚拉德什住所、诊所与主要居民；东区保存农田、双头牛、井和大蝎子洞穴入口附近的居民。三枚城镇海报按钮分别进入西区和东区的两个入口。",
    regions=(
        Region("West Side 西区", "West Side", "西区", "SHADYW", 0, 26,
               "沙荫镇的主要居住区。地图中可见城门、中心农田、诊所与多座夯土建筑；亚拉德什、坦蒂、赛思、卡特里娜、伊恩、拉斯洛和贾维斯都保存在本层。",
               (("医疗与解毒剂", "Razlo 拉斯洛", "检查伤势，并在大蝎子毒腺等条件满足时处理解毒剂与贾维斯中毒。"),
                ("同行", "Ian 伊恩", "通过可达对话分支可邀请伊恩同行；费用与说服条件由人物脚本决定。"))),
        Region("East Side 东区", "East Side", "东区", "SHADYE", 0, 25,
               "沙荫镇的东部农业区。地图保存农田、牲畜围栏、井、三处顶层物品以及普通居民；科尔提斯在此谈论耕作与作物轮种。"),
    ),
    hotspots=((158, 192, 1, "SHADYW", "West Side 西区"), (270, 253, 2, "SHADYE", "East Side 东区（入口 2）"), (314, 217, 3, "SHADYE", "East Side 东区（入口 3）")),
    named_scripts={
        "SETH": ("Seth", "赛思", "观察文字直接称其为沙荫镇门卫队长赛思。"),
        "SSGUIDE": ("Katrina", "卡特里娜", "观察文字直接给出卡特里娜的姓名。"),
        "IAN": ("Ian", "伊恩", "人物原型与对话直接给出姓名。"),
        "ARADESH": ("Aradesh", "亚拉德什", "观察文字直接给出姓名。"),
        "JARVIS": ("Jarvis", "贾维斯", "观察文字和自述直接给出姓名。"),
        "RAZLO": ("Razlo", "拉斯洛", "观察文字直接给出姓名。"),
        "TANDI": ("Tandi", "坦蒂", "人物原型和自我介绍直接给出姓名。"),
        "CURTIS": ("Curtis", "科尔提斯", "人物自述直接说自己名叫 Curtis。"),
    },
    generic_scripts={
        "LOSER": ("Resident", "居民", "共用居民脚本，没有个人姓名。"), "CITIZEN": ("Resident", "居民", "共用居民脚本，没有个人姓名。"),
        "PLEASANT": ("Resident", "居民", "共用居民脚本，没有个人姓名。"), "CHILD": ("Child", "儿童", "儿童类别名，不是个人姓名。"),
        "TGUARD": ("Shady Sands Guard", "沙荫镇警卫", "警卫职务名，不是个人姓名。"), "COOK": ("Cook", "厨师", "职业名，不是个人姓名。"),
        "WIFE": ("Razlo's Wife", "拉斯洛的妻子", "关系称谓，不是个人姓名。"),
    },
    creature_scripts=frozenset({"BRAHMIN", "DOG"}),
    tasks=(
        Task("Cure Jarvis of Radscorpion Poison", "治愈中蝎子毒的贾维斯", 1249, "Jarvis 贾维斯", "West Side 西区",
             "贾维斯因大蝎子毒素卧床；拉斯洛与解毒剂流程可使他恢复。", "1. 与贾维斯或拉斯洛确认中毒状况。\n2. 取得或制作大蝎子毒素的解毒剂。\n3. 对贾维斯使用治疗流程并确认恢复。", ("West Side 西区",), ("JARVIS", "RAZLO")),
        Task("Make Poison Antidote", "制作解毒剂", 1486, "Razlo 拉斯洛", "West Side 西区",
             "拉斯洛研究大蝎子毒素，并可利用取得的毒腺制作解毒剂。", "1. 向拉斯洛询问大蝎子毒素。\n2. 取得大蝎子毒腺。\n3. 把材料交给拉斯洛，按脚本条件取得解毒剂。", ("West Side 西区",), ("RAZLO",)),
        Task("Rescue Tandi from the Raiders", "从歹徒营地拯救坦蒂", 1144, "Aradesh 亚拉德什", "West Side 西区",
             "坦蒂被歹徒掳走后，亚拉德什请求玩家把她带回沙荫镇。", "1. 从亚拉德什处确认坦蒂失踪。\n2. 前往[[Raiders 歹徒|歹徒营地]]。\n3. 通过交涉、潜行或战斗使坦蒂脱离囚禁。\n4. 带她返回沙荫镇并向亚拉德什确认结果。", ("West Side 西区",), ("ARADESH", "TANDI", "SETH")),
        Task("Stop the Radscorpions", "阻止大蝎子", 1144, "Aradesh 亚拉德什", "West Side 西区",
             "亚拉德什说明大蝎子威胁村庄，赛思负责把玩家带到洞穴。", "1. 从亚拉德什处得知威胁。\n2. 让赛思带路进入大蝎子洞穴。\n3. 清除洞穴中的大蝎子。\n4. 返回沙荫镇确认任务结果。", ("West Side 西区",), ("ARADESH", "SETH")),
    ),
    aliases=("Shady Sands", "沙荫镇"), heads={"ARADESH": "ARDSH"},
)


JUNKTOWN = Location(
    key="junktown", title="Junktown 迦克镇", english="Junktown", chinese="迦克镇",
    poster_number=3, world_grid=(17, 10), world_pixel=(875, 525), discovery_variable=71,
    overview="迦克镇的三枚城镇按钮分别进入北部入口区、基利安所在的南部街区和吉斯莫赌场区。莫彼得医生地下室与入口区共用 `JUNKENT.MAP` 的 elevation 1，因此单独建为第四个区域。",
    regions=(
        Region("Entrance District 入口区", "Entrance District", "入口区", "JUNKENT", 0, 10,
               "迦克镇北部入口、卫队监牢、莫彼得医生诊所和商队停靠点所在的地面区域。地图保存拉尔斯、安德鲁、卡尔诺、莫彼得医生及其助手。",
               (("医疗与身体检查", "Doc Morbid 莫彼得医生", "提供检查和治疗对话；诊所地下室另保存格雷彻与脚本关联对象。"),
                ("治安与监牢", "Lars 拉尔斯 / Andrew 安德鲁", "卫队长处理重大治安任务，安德鲁看守牢房。"))),
        Region("Doc Morbid's Basement 莫彼得医生地下室", "Doc Morbid's Basement", "莫彼得医生地下室", "JUNKENT", 1, 10,
               "莫彼得医生诊所下方的独立地下室。地图只保存格雷彻一名人物，以及五个容器和一件非容器顶层物品；由地面层的梯子连接。"),
        Region("Casino District 赌场区", "Casino District", "赌场区", "JUNKCSNO", 0, 11,
               "吉斯莫赌场、斯卡姆·匹特酒吧、拳击场及周边住宅所在区域。吉斯莫、艾佐、索尔、尼尔、提可、特里诗、狗肉等对象集中在这里。",
               (("赌场与拳击", "Gizmo 吉斯莫 / Gustofer 古斯托弗", "赌场经营、拳击赛和相关任务状态由脚本控制。"),
                ("酒馆交易", "Neal 尼尔", "斯卡姆·匹特提供饮品、情报和骷髅党任务线索。"),
                ("同行", "Tycho 提可", "满足对话与队伍条件时可邀请提可同行。"))),
        Region("Killian's District 基利安区", "Killian's District", "基利安区", "JUNKKILL", 0, 12,
               "基利安商店、倒塌的国会旅店、骷髅党据点与牲畜围栏所在区域。基利安、维尼、雪莉、玛塞尔、辛西娅及多名镇民保存在本层。",
               (("武器与杂货交易", "Killian Darkwater 基利安·达克沃特", "基利安在商店提供交易，并发起调查吉斯莫的治安任务。"),
                ("住宿", "Marcelle 玛塞尔", "旅店经营者；脚本还发起辛西娅人质事件。"))),
    ),
    hotspots=((400, 317, 3, "JUNKENT", "Entrance District 入口区"), (304, 257, 2, "JUNKKILL", "Killian's District 基利安区"), (200, 279, 1, "JUNKCSNO", "Casino District 赌场区")),
    named_scripts={
        "MORBID": ("Doc Morbid", "莫彼得医生", "观察文字和自述直接给出姓名与医生身份。"), "FLASH": ("Flash", "弗莱士", "莫彼得医生对话与脚本直接点名。"),
        "COUGAR": ("Cougar", "库戈尔", "观察文字直接给出姓名。"), "ANDREW": ("Andrew", "安德鲁", "观察文字与自述直接给出姓名。"),
        "LARS": ("Lars", "拉尔斯", "观察文字直接给出姓名和卫队长职务。"), "ASSBLOW": ("Kalnor", "卡尔诺", "观察文字直接称其为卡尔诺。"),
        "GRETCH": ("Gretch", "格雷彻", "观察文字直接给出姓名。"), "SAUL": ("Saul", "索尔", "观察文字直接给出姓名和拳手身份。"),
        "IZO": ("Izo", "艾佐", "观察文字直接给出姓名。"), "GIZMO": ("Gizmo", "吉斯莫", "观察文字直接给出姓名与赌场老板身份。"),
        "GUSTOFER": ("Gustofer", "古斯托弗", "拳击场对话直接点名。"), "ISMARC": ("Ismarc", "伊斯马克", "观察文字直接给出姓名。"),
        "NEAL": ("Neal", "尼尔", "观察文字直接给出姓名与酒保身份。"), "TYCHO": ("Tycho", "提可", "观察文字直接给出姓名。"),
        "TRISH": ("Trish", "特里诗", "观察文字直接给出姓名和女招待身份。"), "SHARK": ("Shark", "沙克", "观察文字直接给出姓名。"),
        "PHIL": ("Phil", "费尔", "观察文字直接给出姓名。"), "LENORE": ("Lenore", "勒诺", "观察文字直接给出姓名。"),
        "VINNIE": ("Vinnie", "维尼", "人物原型和观察文字直接给出姓名。"), "VICTOR": ("Victor", "维克托", "观察文字直接给出姓名。"),
        "SHERRY": ("Sherry", "雪莉", "观察文字直接给出姓名。"), "SINTHIA": ("Sinthia", "辛西娅", "观察文字直接给出姓名。"),
        "MARCELLE": ("Marcelle", "玛塞尔", "观察文字直接给出姓名。"), "KILLIAN": ("Killian Darkwater", "基利安·达克沃特", "人物原型和观察文字直接给出姓名。"),
    },
    generic_scripts={
        "JCHIDMEM": ("Cathedral Student", "大教堂学徒", "组织身份，不是个人姓名。"), "PEASANTC": ("Resident", "居民", "共用居民脚本。"),
        "GENSKULZ": ("Skulz Gang Member", "骷髅党成员", "帮派身份，不是个人姓名。"), "JTGENGRD": ("Junktown Guard", "迦克镇警卫", "警卫职务名。"),
        "JUNKPEAS": ("Junktown Resident", "迦克镇居民", "共用居民脚本。"), "CARVLEAD": ("Caravan Leader", "商队领队", "职业名。"),
        "BOXGUARD": ("Boxing Guard", "拳击场守卫", "职务名。"), "GENGAMBL": ("Gambler", "赌徒", "类别名。"),
        "BARFLY": ("Barfly", "酒客", "类别名。"), "HDEALER": ("Dealer", "商贩", "职业名。"), "GIZGUARD": ("Gizmo Guard", "吉斯莫守卫", "职务名。"),
    },
    creature_scripts=frozenset({"BRAHMIN", "JUNKDOG"}),
    tasks=(
        Task("Help Saul", "帮助索尔", 1245, "Trish 特里诗", "Casino District 赌场区", "特里诗关心拳手索尔的处境；对话可影响两人的关系和索尔的选择。", "1. 与特里诗谈论索尔。\n2. 与索尔讨论拳击、生活和特里诗。\n3. 选择可达的劝说分支并回到相关人物确认变化。", ("Casino District 赌场区",), ("TRISH", "SAUL")),
        Task("Kill Killian", "杀死基利安", 687, "Gizmo 吉斯莫", "Casino District 赌场区", "吉斯莫雇佣玩家杀死基利安；接受后与基利安路线互斥或冲突。", "1. 与吉斯莫交谈并接受刺杀。\n2. 前往基利安区。\n3. 杀死基利安后返回吉斯莫结算；若转而帮助基利安，则进入制止吉斯莫路线。", ("Casino District 赌场区", "Killian's District 基利安区"), ("GIZMO", "KILLIAN", "IZO")),
        Task("Rescue Sinthia", "拯救辛西娅", 1123, "Marcelle 玛塞尔", "Killian's District 基利安区", "玛塞尔报告有人在旅店房间挟持辛西娅。", "1. 从玛塞尔处得知人质事件。\n2. 进入辛西娅所在房间。\n3. 通过对话或战斗解除威胁并确保辛西娅存活。", ("Killian's District 基利安区",), ("MARCELLE", "SINTHIA")),
        Task("Save Trish", "解救特里诗", 1245, "Trish 特里诗", "Casino District 赌场区", "特里诗与骷髅党事件相连；任务状态取决于酒吧冲突和玩家是否及时介入。", "1. 在斯卡姆·匹特推进特里诗与骷髅党相关对话。\n2. 识别对她的威胁。\n3. 在脚本允许的时间与状态内解除威胁。", ("Casino District 赌场区", "Killian's District 基利安区"), ("TRISH", "NEAL", "VINNIE")),
        Task("Stop Gizmo", "制止吉斯莫", 1779, "Killian Darkwater 基利安·达克沃特", "Killian's District 基利安区", "基利安要求取得吉斯莫企图谋杀自己的证据，并由卫队采取行动。", "1. 在基利安遭袭后接受调查。\n2. 携带录音设备与吉斯莫交谈，引出刺杀计划。\n3. 把证据交回基利安或拉尔斯。\n4. 参加或触发对吉斯莫的逮捕行动。", ("Killian's District 基利安区", "Casino District 赌场区"), ("KILLIAN", "GIZMO", "LARS", "IZO")),
        Task("Bust the Skulz gang", "瓦解骷髅党", 1765, "Lars 拉尔斯", "Entrance District 入口区", "拉尔斯负责迦克镇治安；玩家可调查骷髅党、酒吧骨灰盒和袭击计划，并把证据交给卫队。", "1. 在酒吧和骷髅党据点取得线索。\n2. 处理骨灰盒盗窃与入帮试探。\n3. 向拉尔斯报告袭击计划或取得的证据。\n4. 与卫队共同制止骷髅党。", ("Entrance District 入口区", "Casino District 赌场区", "Killian's District 基利安区"), ("LARS", "VINNIE", "SHERRY", "NEAL")),
    ),
    aliases=("Junktown", "迦克镇"), heads={"GIZMO": "GIZMO", "KILLIAN": "KILLN"},
)


VAULT15 = Location(
    key="vault15", title="Vault 15 15号避难所", english="Vault 15", chinese="15号避难所",
    poster_number=1, world_grid=(25, 1), world_pixel=(1275, 75), discovery_variable=70,
    overview="15 号避难所由地面洞穴入口与被掩埋避难所的三层遗迹组成。地面入口没有人物或物品；三层地下遗迹保存大量变种地鼠、猪鼠、武器、弹药与储物柜。第三层坍塌区域使原本的指挥中心无法正常到达。",
    regions=(
        Region("Surface Entrance 地面入口", "Surface Entrance", "地面入口", "VAULTENT", 0, 7, "15 号避难所上方的洞穴入口。静态地图没有人物、生物、地面物品或容器；一架向下的梯子连接被掩埋避难所。"),
        Region("Level 1 第一层", "Level 1", "第一层", "VAULTBUR", 0, 8, "被掩埋避难所的第一层。地图保存十四只变种地鼠、两个容器和两件地面武器；向上的梯子返回地面入口。"),
        Region("Level 2 第二层", "Level 2", "第二层", "VAULTBUR", 1, 8, "被掩埋避难所的第二层。地图保存十七只变种地鼠或猪鼠、一只储物柜和三件非容器顶层物品。"),
        Region("Level 3 第三层", "Level 3", "第三层", "VAULTBUR", 2, 8, "被掩埋避难所的第三层。地图保存二十三只洞穴鼠、猪鼠或大型鼹鼠，以及三只容器和三件非容器顶层物品；坍塌结构阻断了原有深层设施。"),
    ),
    hotspots=((68, 250, 0, "VAULTENT", "Surface Entrance 地面入口"), (107, 209, 1, "VAULTBUR", "Level 1 第一层"), (298, 187, 2, "VAULTBUR", "Level 2 第二层"), (135, 290, 3, "VAULTBUR", "Level 3 第三层")),
    named_scripts={}, generic_scripts={}, creature_scripts=frozenset({"WANRATS"}),
    external_tasks=(("Find the Water Chip 找到净水芯片（发起人 ID 2209）", "找到净水芯片", "监督者最初把 15 号避难所作为线索；本地点的坍塌遗迹没有可取得的净水芯片。规范任务页位于 13 号避难所。"),),
    aliases=("Vault 15", "15号避难所", "Buried Vault", "被掩埋的避难所"),
)


LOCATIONS = {loc.key: loc for loc in (SHADY, JUNKTOWN, VAULT15)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("location", choices=tuple(LOCATIONS))
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stem(obj: dict) -> str:
    return Path(obj.get("script_filename") or "").stem.upper()


def identity(loc: Location, obj: dict, proto_en: str, proto_zh: str) -> tuple[str, str, str, bool]:
    script = stem(obj)
    if script in loc.named_scripts:
        en, zh, note = loc.named_scripts[script]
        return en, zh, note, True
    if script in loc.generic_scripts:
        en, zh, note = loc.generic_scripts[script]
        return en, zh, note, False
    return proto_en, proto_zh, f"人物原型分类为 {proto_en} / {proto_zh}；素材没有提供个人姓名。", False


def short_title(loc: Location, title: str) -> str:
    return title.removeprefix(f"{loc.title} - ").split("（ID", 1)[0].strip()


def object_key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def poster(loc: Location, output: Path) -> None:
    source = Image.open(REPO / f"workspace/output/images/master/ART/INTRFACE/TWNMAP{loc.poster_number:02d}.frm/TWNMAP{loc.poster_number:02d}.frm.frames/sequence-00/frame-000.png").convert("RGBA")
    canvas = Image.new("RGBA", (1450, 920), (18, 18, 16, 255)); draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 21)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((725, 38), loc.title, font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((725, 70), f"TWNMAP{loc.poster_number:02d}.FRM · 引擎 TownHotSpots 精确按钮坐标", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale, left, top = 1.70, 340, 95
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    canvas.alpha_composite(scaled, (left, top))
    for idx, (x, y, entry, map_name, label) in enumerate(loc.hotspots):
        px, py = left + x * scale, top + y * scale
        side_left = idx % 2 == 0
        bx = 25 if side_left else 1100
        by = 135 + idx * 170
        bw, bh = 320, 92
        edge_x = bx + bw if side_left else bx
        draw.line((px, py, (px + edge_x) / 2, by + bh / 2, edge_x, by + bh / 2), fill=(224, 180, 91), width=3)
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(246, 210, 121), outline=(60, 41, 23), width=3)
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(38, 30, 23, 240), outline=(159, 123, 61), width=2)
        draw.text((bx + 14, by + 16), label, font=label_font, fill=(248, 232, 188))
        draw.text((bx + 14, by + 57), f"{map_name}.MAP · 入口 {entry} · ({x},{y})", font=meta_font, fill=(205, 185, 139))
    draw.text((725, 892), "坐标以 453×444 原始海报左上角为原点；区域页按 MAP + elevation 展开", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def profile_maps(loc: Location, region: Region, people: list[dict], attachments: Path) -> dict[int, str]:
    root = REPO / "workspace/output/maps-rendered" / region.map_name
    prefix = f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters"
    doc = load_json(root / f"{prefix}.json")
    labels = doc["critter_name_labels"]["labels"]
    composite = Image.open(root / f"{prefix}.png").convert("RGBA")
    alpha = Image.open(root / f"elevation-{region.elevation}-critters.png").convert("RGBA").getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(5))
    base = Image.composite(Image.new("RGBA", composite.size, GREEN), composite, ImageChops.subtract(expanded, alpha))
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 28)
    outputs = {}
    for obj in people:
        oid = int(obj["object_id"]); en, zh, _, _ = identity(loc, obj, "", "")
        filename = f"{region.title}地图（人物标注，{en} {zh} ID {oid}高亮，完整原始画布）.png"
        own = next(label for label in labels if int(label["object_id"]) == oid)
        canvas = base.copy(); target = tuple(int(v) for v in own["target_canvas"])
        if not own.get("missing_art"):
            component = bb.nearest_component(alpha, target)
            if component is not None:
                outline = ImageChops.subtract(component.filter(ImageFilter.MaxFilter(7)), component)
                canvas = Image.composite(Image.new("RGBA", canvas.size, ORANGE), canvas, outline)
        draw = ImageDraw.Draw(canvas, "RGBA")
        for label in labels:
            x, y = (int(v) for v in label["target_canvas"]); l, t, r, b = (int(v) for v in label["label_box_canvas"])
            focus = int(label["object_id"]) == oid; color = ORANGE if focus else GREEN
            draw.line((x, y, (l + r) // 2, (t + b) // 2), fill=color, width=3 if focus else 1)
            draw.rounded_rectangle((l, t, r, b), radius=5, fill=(19, 23, 19, 228), outline=color, width=3 if focus else 1)
            draw.text((l + 7, t + 5), label["display_name"], font=font, fill=(255, 255, 255, 255))
        canvas.save(attachments / filename); outputs[oid] = filename
    return outputs


def task_links(loc: Location, script: str) -> str:
    links = [task.filename for task in loc.tasks if script in task.related_scripts]
    if not links:
        return ""
    return "# 任务关联\n\n" + "\n".join(f"- [[{name}|{name.split('（', 1)[0]}]]" for name in links)


def character_note(loc: Location, vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path) -> tuple[str, str, bool]:
    oid = int(obj["object_id"]); en, zh, situation, named = identity(loc, obj, proto_en, proto_zh); script = stem(obj)
    title = f"{en} {zh}（ID {oid}）"; resource_line = f"resource_script: {script}.INT\n" if script else ""
    sprite = f"![[{sprite_filename}|160]]\n\n该图取自 `{art_name}`，使用地图对象方向 {obj['rotation']} 与第 0 帧。" if sprite_filename else "资源缺少本对象可用人物帧，因此未借用其他造型。"
    sections = [rf'''---
title: "{title}"
aliases:
  - "{loc.title} - {en} {zh}"
  - "{en} {zh}"
tags: [辐射1, 人物, 地点, {loc.chinese}]
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
| 全名 | {'素材直接提供个人姓名' if named else '职业、关系或群体类别，不是专名'} |
| 游戏观察文字 | {bb.md(cath.character_observation(REPO, obj, proto, critter_messages))} |

# 地图信息

![[{map_filename}|900]]

橙色轮廓为本页人物，绿色轮廓为本层其他人物或生物；图片保留渲染器完整原始画布和原始像素尺寸。

| 属性 | 值 |
|---|---|
| 出现地点 | [[{loc.title}\|{loc.chinese}]] |
| 所属区域 | [[{region.title}\|{region.title}]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | {region.elevation} |
| 地图对象 ID | {oid} |
| 人物原型 ID | {obj['prototype']['list_index']} |
| 地图格 | {obj['tile']}（{obj['tile_x']}, {obj['tile_y']}） |
| 朝向 | {obj['rotation']} |
| 人物脚本 | {f'`{script}.INT`' if script else '无独立人物脚本'} |
| 人物形象 | `{art_name}` |

# 形象

## 地图人物精灵

{sprite}

{bb.head_assets(REPO, attachments, en, zh, script)}''', bb.game_data(obj, proto), bb.inventory_section(obj, lookup, item_messages, note_index)]
    topics = topic_records(REPO, script)
    if topics: sections.append(render_topic_section(topics))
    dialogue = cath.reachable_dialogue(REPO, obj)
    if dialogue: sections.append(dialogue)
    sections.append(f"# 身份与处境\n\n{situation}")
    task = task_links(loc, script)
    if task: sections.append(task)
    return "\n\n".join(s for s in sections if s).rstrip() + "\n", title, named


def item_records(loc: Location, region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                 item_messages: dict, note_index: dict, titles: dict[tuple[str, int, int], str]) -> tuple[list[tuple], list[tuple]]:
    items, containers = [], []
    for obj in characters:
        owner_title = titles[object_key(region, obj)]; owner = f"[[{owner_title}\\|{short_title(loc, owner_title)}]]"
        for entry in obj.get("inventory", []):
            kind, en, zh = bb.item_data(entry["item"], lookup, item_messages)
            items.append((kind, bb.item_link(en, zh, note_index), region.title, owner, int(entry["quantity"])))
    for obj in objects:
        if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0: continue
        kind, en, zh = bb.item_data(obj, lookup, item_messages); name = bb.item_link(en, zh, note_index); where = f"对象 ID {obj['object_id']}；tile {obj['tile']}"
        if obj["prototype"].get("subtype_name") == "container":
            contents = []
            for entry in obj.get("inventory", []):
                _, ien, izh = bb.item_data(entry["item"], lookup, item_messages)
                contents.append(f"{bb.item_link(ien, izh, note_index)} ×{entry['quantity']}")
            containers.append((region.title, f"{name}（{where}）", "<br>".join(contents) if contents else "空"))
        else: items.append((kind, name, region.title, where, 1))
    return items, containers


def task_rows(loc: Location, region: Region) -> list[str]:
    rows = []
    for task in loc.tasks:
        if region.title in task.related_regions:
            phase = "本区域发起。" if region.title == task.start_region else "本区域承担任务目标、调查或结算环节。"
            rows.append(f"| [[{task.filename}\\|{task.english} {task.chinese}]] | {task.giver_name}（ID {task.giver_id}） | [[{task.start_region}]] | {phase} |")
    for filename, label, phase in loc.external_tasks:
        rows.append(f"| [[{filename}\\|{label}]] | [[Vault 13 13号避难所 - Overseer 监督者（ID 2209）\\|Overseer 监督者]] | [[Command Center 避难所指挥中心]] | {phase} |")
    return rows or ["| — | — | — | 本区域没有独立任务环节。 |"]


def creature_name(obj: dict, proto_en: str, proto_zh: str) -> str:
    return f"{proto_en} / {proto_zh}"


def write_region(loc: Location, root: Path, region: Region, people: list[dict], creatures: list[dict], objects: list[dict], lookup: dict,
                 critter_messages: dict, item_messages: dict, note_index: dict, titles: dict[tuple[str, int, int], str]) -> None:
    named_rows, generic_rows = [], []
    for index, obj in enumerate(sorted(people, key=lambda o: int(o["object_id"])), 1):
        oid = int(obj["object_id"]); title = titles[object_key(region, obj)]; row = f"| {index} | {oid} | [[{title}\\|{short_title(loc, title)}]] | `{stem(obj)}.INT` |"
        (named_rows if stem(obj) in loc.named_scripts else generic_rows).append(row)
    creature_rows = []
    for obj in sorted(creatures, key=lambda o: int(o["object_id"])):
        proto = lookup[("critter", int(obj["prototype"]["list_index"]))]; en, zh = critter_messages[int(proto["message_id"])]
        creature_rows.append(f"| {obj['object_id']} | {en} / {zh} | `{stem(obj)}.INT` | {obj['tile']} |")
    items, containers = item_records(loc, region, people, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {qty} |" for kind, name, _, owner, qty in sorted(items)] or ["| — | — | — | 0 |"]
    container_rows = [f"| {name} | {contents} |" for _, name, contents in containers] or ["| — | 本区域没有容器。 |"]
    services = [f"| {a} | {b} | {c} |" for a, b, c in region.services] or ["| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |"]
    page = rf'''---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, {loc.chinese}]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[{loc.title}\|{loc.title}]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

## 地图

![[{region.title}地图（人物与物品标注，完整原始画布）.png|900]]

绿色表示人物或生物，黄色表示地面物品和容器。图片保留完整渲染画布与原始像素尺寸，不按标签范围裁切，也不缩小；它只表达 MAP 保存状态。

## 商店和服务

| 商店或服务 | 提供者 | 内容 |
|---|---|---|
{chr(10).join(services)}

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
{chr(10).join(creature_rows) if creature_rows else '| — | 本区域没有从人物表中剥离的生物对象。 | — | — |'}

## 物品

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 容器 | 直接库存 |
|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 任务链上第一个发起人 | 发起人所在区域 | 本区域中的环节 |
|---|---|---|---|
{chr(10).join(task_rows(loc, region))}
'''
    (root / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_tasks(loc: Location, root: Path) -> None:
    by_title = {r.title: r for r in loc.regions}
    for task in loc.tasks:
        task_dir = root / by_title[task.start_region].directory / "任务"; task_dir.mkdir(parents=True, exist_ok=True)
        regions = "、".join(f"[[{name}]]" for name in task.related_regions)
        page = rf'''---
title: "{task.english} {task.chinese}"
aliases: ["{task.english}", "{task.chinese}"]
tags: [辐射1, 任务, {loc.chinese}]
quest_giver_map_object_id: {task.giver_id}
---

# {task.english} {task.chinese}

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | {task.english}. |
| 当前中文 | {task.chinese}。 |

## 任务概览

{task.summary}

## 流程

{task.steps}

## 人物与区域

| 属性 | 内容 |
|---|---|
| 第一个发起人 | {task.giver_name}（地图对象 ID {task.giver_id}） |
| 发起区域 | [[{task.start_region}]] |
| 涉及区域 | {regions} |

## 来源边界

任务标题来自原始英文与当前中文 `PIPBOY.MSG`；可见台词来自相关人物消息，条件与状态来自人物或地图脚本。本文不把静态地图保存状态写成任务完成后的必然状态。
'''
        (task_dir / f"{task.filename}.md").write_text(page, encoding="utf-8")


def write_home(loc: Location, root: Path, region_people: dict[str, list[dict]], region_creatures: dict[str, list[dict]],
               region_objects: dict[str, tuple[list[dict], dict]], titles: dict[tuple[str, int, int], str], item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, creature_rows, all_items, all_containers = [], [], [], [], [], []
    for region in loc.regions:
        people, creatures = region_people[region.title], region_creatures[region.title]
        region_rows.append(f"| [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` | {region.elevation} | {len(people)} | {len(creatures)} | {region.description.split('。')[0]}。 |")
        for obj in sorted(people, key=lambda o: int(o["object_id"])):
            title = titles[object_key(region, obj)]; row = f"| [[{region.title}\\|{region.chinese}]] | {obj['object_id']} | [[{title}\\|{short_title(loc, title)}]] |"
            (named_rows if stem(obj) in loc.named_scripts else generic_rows).append(row)
        objects, lookup = region_objects[region.title]; critter_messages = bb.message_groups(REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME/PRO_CRIT.json")
        for obj in creatures:
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]; en, zh = critter_messages[int(proto["message_id"])]
            creature_rows.append(f"| [[{region.title}\\|{region.chinese}]] | {obj['object_id']} | {en} / {zh} | `{stem(obj)}.INT` |")
        items, containers = item_records(loc, region, people, objects, lookup, item_messages, note_index, titles); all_items.extend(items); all_containers.extend(containers)
    item_rows = [f"| {kind} | {name} | [[{region}]] | {owner} | {qty} |" for kind, name, region, owner, qty in sorted(all_items)]
    container_rows = [f"| [[{region}]] | {name} | {contents} |" for region, name, contents in all_containers]
    tasks = [f"| [[{t.filename}\\|{t.english} {t.chinese}]] | {t.giver_name}（ID {t.giver_id}） | [[{t.start_region}]] |" for t in loc.tasks]
    tasks += [f"| [[{f}\\|{label}]] | Overseer 监督者（ID 2209） | [[Command Center 避难所指挥中心]] |" for f, label, _ in loc.external_tasks]
    aliases = "\n".join(f"  - \"{a}\"" for a in loc.aliases)
    page = rf'''---
title: "{loc.title}"
aliases:
{aliases}
tags: [辐射1, 地点, {loc.chinese}]
world_map_grid: "{loc.world_grid[0]},{loc.world_grid[1]}"
world_map_pixel: "{loc.world_pixel[0]},{loc.world_pixel[1]}"
---

# {loc.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图 | {loc.english} / {loc.chinese} |
| 知识库标题 | {loc.title} |
| 城镇海报 | `TWNMAP{loc.poster_number:02d}.FRM` |
| 资源地图组 | {"、".join(f'`{r.map_name}.MAP`' for r in loc.regions)} |

## 世界地图位置

世界地图网格为 `({loc.world_grid[0]}, {loc.world_grid[1]})`，地点锚点像素约为 `({loc.world_pixel[0]}, {loc.world_pixel[1]})`，发现变量为 `{loc.discovery_variable}`。

## 地图

![[{loc.title}城镇地图（区域标注）.jpg|900]]

海报使用原作 `TWNMAP{loc.poster_number:02d}.FRM`；按钮坐标、入口编号与目标 MAP 来自引擎 `TownHotSpots` 表。区域页对无法由按钮单独区分的楼层继续按 MAP + elevation 展开。

## 地点概览

{loc.overview}

## 城市分区

| 英文名称 | 中文名称 |
|---|---|
{chr(10).join(f'| [[{r.title}\\|{r.english}]] | [[{r.title}\\|{r.chinese}]] |' for r in loc.regions)}

## 区域与楼层

| 归属或入口 | 区域与楼层 | 类型 | 进入方式或关系 |
|---|---|---|---|
{chr(10).join(f'| {r.english} | [[{r.title}\\|{r.title}]] | {"地下层" if r.elevation else "地面区域"} | `{r.map_name}.MAP` elevation {r.elevation}；由海报按钮、梯子或相邻区域连接。 |' for r in loc.regions)}

## 地图中的人物

### 专名人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(named_rows) if named_rows else '| — | — | 完整清点没有专名人物。 |'}

### 普通人物

| 区域 | 地图对象 ID | 人物 |
|---|---:|---|
{chr(10).join(generic_rows) if generic_rows else '| — | — | 完整清点没有普通人物。 |'}

### 生物对象

| 区域 | 地图对象 ID | 生物 | 脚本 |
|---|---:|---|---|
{chr(10).join(creature_rows) if creature_rows else '| — | — | 完整清点没有生物对象。 | — |'}

## 地图中的物品

下表汇总人物随身库存和地图顶层非容器物品；容器实体与直接库存单列。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(item_rows) if item_rows else '| — | — | — | 全地点没有人物库存或顶层非容器物品。 | 0 |'}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows) if container_rows else '| — | 全地点没有容器。 | 空集合 |'}

## Pip-Boy 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 |
|---|---|---|
{chr(10).join(tasks) if tasks else '| — | 本地点没有独立 Pip-Boy 任务。 | — |'}

## 来源边界

- 地点坐标来自已验收世界地图地点配置；城镇海报按钮来自引擎 `TownHotSpots` 表。
- 人物、物品、容器与楼层来自完整 MAP 对象清点；人物台词、主题、服务与任务条件来自当前消息和脚本。
- 区域总图与人物位置图保留完整渲染画布和原始像素尺寸，不按标签框裁切，也不缩放。
'''
    (root / f"{loc.title}.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args(); loc = LOCATIONS[args.location]; vault = args.vault_root.resolve(); root = vault / "地点" / loc.title
    root.mkdir(parents=True, exist_ok=True); note_index = bb.build_note_index(vault)
    bb.HEADS = loc.heads
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"; critter_messages = bb.message_groups(game / "PRO_CRIT.json"); item_messages = bb.message_groups(game / "PRO_ITEM.json")
    home_attachments = root / "attachments"; home_attachments.mkdir(exist_ok=True); poster(loc, home_attachments / f"{loc.title}城镇地图（区域标注）.jpg")
    region_people, region_creatures, region_objects, titles = {}, {}, {}, {}
    evidence = {"location": loc.title, "town_poster": f"TWNMAP{loc.poster_number:02d}.FRM", "town_hotspots": loc.hotspots, "maps": [], "character_notes": 0, "creature_objects": 0}
    for region in loc.regions:
        region_dir = root / region.directory; attachments = region_dir / "attachments"; people_root = region_dir / "人物"; named_dir = people_root / "Named Characters 专名人物"; generic_dir = people_root / "Generic Characters 普通人物"; people_attachments = people_root / "attachments"
        for path in (attachments, named_dir, generic_dir, people_attachments): path.mkdir(parents=True, exist_ok=True)
        map_doc = load_json(REPO / f"workspace/output/maps/master/MAPS/{region.map_name}/{region.map_name}.json"); lookup = bb.proto_lookup(map_doc)
        objects = [o for o in map_doc["objects"]["entries"] if int(o.get("elevation_group", -1)) == region.elevation]
        critters = [o for o in objects if o.get("prototype", {}).get("type") == "critter" and int(o.get("tile", -1)) >= 0]
        creatures = [o for o in critters if stem(o) in loc.creature_scripts]; people = [o for o in critters if stem(o) not in loc.creature_scripts]
        region_people[region.title], region_creatures[region.title], region_objects[region.title] = people, creatures, (objects, lookup)
        render_root = REPO / "workspace/output/maps-rendered" / region.map_name; prefix = f"elevation-{region.elevation}-floor-walls-doors-scenery-items"
        labeled = render_root / f"{prefix}-critters-labeled-zh-CN.png"; source_map = labeled if labeled.exists() else render_root / f"{prefix}.png"
        shutil.copyfile(source_map, attachments / f"{region.title}地图（人物与物品标注，完整原始画布）.png")
        maps = profile_maps(loc, region, people, people_attachments) if people else {}
        render_json = render_root / f"{prefix}-critters.json"
        render_doc = load_json(render_json) if render_json.exists() else None
        render_by_id = {int(o["object_id"]): o for o in (render_doc["critters"] + render_doc.get("missing_critter_art", []))} if render_doc else {}
        for obj in people:
            oid = int(obj["object_id"]); proto = lookup[("critter", int(obj["prototype"]["list_index"]))]; proto_en, proto_zh = critter_messages[int(proto["message_id"])]
            en, zh, _, named = identity(loc, obj, proto_en, proto_zh); entry = render_by_id[oid]; art = Path(entry["filename"]).stem.upper(); source = bb.find_critter_frame(REPO, entry["filename"], int(obj["rotation"])); sprite_name = None
            if source:
                sprite_name = f"{en} {zh}（ID {oid}）- 地图人物精灵（{art}，方向{obj['rotation']}，帧0）.png"; shutil.copyfile(source, people_attachments / sprite_name)
            text, title, named = character_note(loc, vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages, critter_messages, note_index, maps[oid], sprite_name, f"{art}.FRM", people_attachments)
            full = f"{loc.title} - {title}"; target = (named_dir if named else generic_dir) / f"{full}.md"
            if target.exists() and not args.overwrite: raise FileExistsError(target)
            target.write_text(text, encoding="utf-8"); titles[object_key(region, obj)] = full
        top_items = [o for o in objects if o.get("prototype", {}).get("type") == "item" and int(o.get("tile", -1)) >= 0]
        evidence["maps"].append({"map": region.map_name, "elevation": region.elevation, "region": region.title, "people": len(people), "creatures": len(creatures), "objects": len(objects), "top_level_items": len(top_items), "containers": sum(o.get("prototype", {}).get("subtype_name") == "container" for o in top_items), "render": str(source_map.relative_to(REPO))})
        evidence["character_notes"] += len(people); evidence["creature_objects"] += len(creatures)
    for region in loc.regions:
        objects, lookup = region_objects[region.title]; write_region(loc, root, region, region_people[region.title], region_creatures[region.title], objects, lookup, critter_messages, item_messages, note_index, titles)
    write_tasks(loc, root); write_home(loc, root, region_people, region_creatures, region_objects, titles, item_messages, note_index); sync_tree(root, REPO)
    out = REPO / f"workspace/output/maps-knowledge/{loc.key}-evidence.json"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {loc.title}: {len(loc.regions)} regions, {evidence['character_notes']} character notes, {evidence['creature_objects']} creature objects, {len(loc.tasks)} local task pages")


if __name__ == "__main__":
    main()
