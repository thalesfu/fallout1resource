#!/usr/bin/env python3
"""Generate the complete Fallout 1 Boneyard location package for Obsidian."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from fallout1_character_topics import render_topic_section, sync_tree, topic_records


REPO = Path(__file__).resolve().parents[1]


def import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bb = import_script("boneyard_brotherhood_helpers", "generate_brotherhood_docs.py")
cath = import_script("boneyard_cathedral_helpers", "generate_cathedral_docs.py")
bb.HEADS = {"NICOLE": "NICOL"}

GREEN = (101, 231, 101, 255)
ORANGE = (255, 126, 48, 255)
Region = bb.Region

REGIONS = (
    Region("Adytum 内城区", "Adytum", "内城区", "LAADYTUM", 0, 28,
           "晒骨场南部的围墙聚落。乔恩·齐默曼名义上管理城镇，管理者武装实际控制治安；迈尔斯、史密蒂、萨缪尔与农场居民也在这里。",
           (("贸易", "Caravan Leader 商队领队", "商队领队对象使用共享商队脚本；实际交易受运行时商队状态影响。"),
            ("化学与水耕技术", "Miles 迈尔斯", "发起水耕农场维修，并在完成后提供后续装备改造线索。"),
            ("修理", "Smitty 史密蒂", "修理水耕农场零件；任务完成后可处理电浆步枪改造。"))),
    Region("Underground 地下与室内层", "Underground", "地下与室内层", "LAADYTUM", 1, 28,
           "资源把商店室内、单独房间、洞穴空间与利刃帮进攻内城区时的条件性集结点保存在同一 elevation。它不是一间连续的大地下室。",
           (("物资交易", "Tine 提恩", "内城区商人；静态地图对象位于本层的商店室内。"),)),
    Region("Downtown 商业区", "Downtown", "商业区", "LABLADES", 0, 44,
           "利刃帮聚居的废墟街区。剃刀领导这里的居民，麦克雷训练成员；地图还保存大量普通成员与儿童对象。"),
    Region("Library 图书馆", "Library", "图书馆", "LAFOLLWR", 0, 29,
           "天启追随者的地表总部，包括图书、医疗物资和公开活动空间。妮可、卡佳及多名学者位于此层。",
           (("组织情报与大教堂调查", "Nicole 妮可", "介绍追随者、指向劳拉与大教堂调查。"),
            ("可招募同伴", "Katja 卡佳", "满足队伍与对话条件时可以加入玩家。"))),
    Region("Library Underground 图书馆地下室", "Library Underground", "图书馆地下室", "LAFOLLWR", 1, 29,
           "天启追随者的地下生活与储藏空间。塔利乌斯及多名追随者学者位于本层；间谍任务由塔利乌斯发起。"),
    Region("Warehouse 仓库区", "Warehouse", "仓库区", "LARIPPER", 0, 45,
           "军火商要塞西南方的废弃仓库入口。静态地图只有一名无独立脚本的商人与少量地面物品；通往地下巢穴的路线穿过仓库建筑。"),
    Region("Warehouse Underground 仓库地下巢穴", "Warehouse Underground", "仓库地下巢穴", "LARIPPER", 1, 45,
           "死亡爪巢穴的地下层，静态对象包括四枚死亡爪卵和一只死亡爪母兽。它们是生物，不列入人物页。"),
    Region("Fortress 军火商要塞", "Fortress", "军火商要塞", "LAGUNRUN", 0, 46,
           "军火商占据的武器工厂与防御工事。加百列负责组织决策，扎克经营武器交易；壕沟和守卫把要塞与仓库区隔开。",
           (("武器交易", "Zack 扎克", "提供军火商武器与弹药交易。"),
            ("死亡爪与利刃帮军援", "Gabriel 加百列", "确认死亡爪清除情况，并可把武器支持转给利刃帮。"))),
)

NAMED = {
    734: ("Caleb", "卡勒布", "管理者首领，负责内城区武装。"),
    1186: ("Sheriff Greene", "治安官格林", "姓名来自人物原型；对象复用普通管理者脚本。"),
    1356: ("Smitty", "史密蒂", "内城区修理工，处理水耕农场零件和后续武器改造。"),
    1654: ("Jon Zimmerman", "乔恩·齐默曼", "内城区镇长；脚本观察文字直接给出姓名和职务。"),
    1884: ("Lorraine", "洛林", "姓名来自 Boneyard 专用脚本文件。"),
    2309: ("Chuck", "查克", "内城区的吉普赛占卜者。"),
    2497: ("Miles", "迈尔斯", "内城区化学家，发起水耕农场维修。"),
    2636: ("Sammael", "萨缪尔", "内城区拾荒者，提供失踪拾荒者与零件位置线索。"),
    633: ("Tine", "提恩", "内城区商人；英文观察文字写作 Tine，而脚本文件名为 Taylor。"),
    780: ("Razor", "剃刀", "内城区进攻状态下生成的剃刀对象。"),
    754: ("Dugan", "杜根", "利刃帮成员，以核子可乐嗜好著称。"),
    842: ("Hammer", "哈默", "姓名来自人物原型；对象使用普通利刃帮脚本。"),
    824: ("Michael", "迈克尔", "利刃帮成员；观察文字直接给出姓名。"),
    825: ("Christine", "克里斯廷", "迈克尔的妻子；观察文字直接说明关系。"),
    981: ("MacRae", "麦克雷", "训练利刃帮对抗死亡爪与管理者。"),
    1514: ("Greg", "格雷格", "利刃帮成员；观察文字直接给出姓名。"),
    821: ("Razor", "剃刀", "利刃帮首领，揭露管理者与乔希之死，并组织反攻。"),
    275: ("Avellone", "艾维隆", "姓名来自人物原型；脚本把他描述为赏金猎人。"),
    1298: ("Nicole", "妮可", "天启追随者领袖，提供大教堂和劳拉的调查线索。"),
    1563: ("Katja", "卡佳", "天启追随者区域的可招募同伴。"),
    1423: ("Talius", "塔利乌斯", "追随者成员，发起查找内部间谍的任务。"),
    954: ("Gabriel", "加百列", "军火商领袖，处理死亡爪与对利刃帮供武问题。"),
    1143: ("Zack", "扎克", "军火商交易员。"),
}

SCRIPT_ROLES = {
    "CARVLEAD": ("Caravan Leader", "商队领队", "使用共享商队领队脚本。"),
    "REGGUARD": ("Adytum Guard", "内城区警卫", "内城区入口或治安岗位警卫。"),
    "REGULATR": ("Regulator", "管理者成员", "管理者武装成员。"),
    "ADYTOWNR": ("Adytum Resident", "内城区居民", "内城区普通居民或劳作者。"),
    "PGUARD": ("Zimmerman's Bodyguard", "齐默曼的保镖", "乔恩·齐默曼身边的护卫。"),
    "CHILD": ("Child", "儿童", "地图保存的儿童对象；当前资源缺少部分儿童 FRM。"),
    "BLADE": ("Blade", "利刃帮成员", "利刃帮普通成员。"),
    "INBLADE": ("Blade Assault Member", "利刃帮突袭队", "进攻内城区状态下保存的条件性利刃帮成员。"),
    "THUG": ("Thug", "暴徒", "追随者图书馆附近的暴徒。"),
    "FOLSCHOL": ("Followers Scholar", "天启追随者学者", "天启追随者普通学者或居民。"),
    "GUNRNR": ("Gun Runner", "军火商成员", "军火商普通成员。"),
    "MOATGRD": ("Moat Guard", "壕沟守卫", "军火商要塞壕沟守卫。"),
}

CREATURE_SCRIPTS = {"DOG2", "EGGCLAW", "MOMCLAW"}
TASKS = (
    ("Become a Blade 成为利刃帮成员（发起人 ID 821）", "Become a Blade", "成为利刃帮成员", 821,
     "Downtown 商业区", "剃刀", "与剃刀建立互信、取得乔希死亡证据并帮助利刃帮摆脱管理者控制。Pip-Boy 只保留简短目标；具体反攻路线由对话与全局状态控制。"),
    ("Deliver package from the Gun Runners 递送军火商的包裹（发起人 ID 821）", "Deliver package from the Gun Runners", "递送军火商的包裹", 821,
     "Downtown 商业区", "剃刀", "先清除仓库地下巢穴的死亡爪和卵，使军火商恢复通路；再让加百列同意向利刃帮供武，并回报剃刀。"),
    ("Find Children spy in the Followers 找出追随者中的大教堂间谍（发起人 ID 1423）", "Find Children spy in the Followers", "找出追随者中的大教堂间谍", 1423,
     "Library Underground 图书馆地下室", "塔利乌斯", "调查正在破坏追随者内部信任的间谍；塔利乌斯的脚本明确提到叛徒希瑟，并在完成后给予奖励。不要与妮可派往大教堂寻找劳拉的主线情报混为同一件事。"),
    ("Fix hydroponic farms in Adytum 修复内城区水耕农场（发起人 ID 2497）", "Fix hydroponic farms in Adytum", "修复内城区水耕农场", 2497,
     "Adytum 内城区", "迈尔斯", "从拾荒线索找到农场零件，交给史密蒂修好，再把修好的零件交还迈尔斯。"),
)

TASK_DETAILS = {
    "Become a Blade": {
        "status": "标题与剃刀任务链均存在；脚本未发现一条独立的“正式入帮仪式”台词，完成语义主要落在帮助利刃帮推翻管理者。",
        "areas": "[[Downtown 商业区]]、[[Adytum 内城区]]；可选军援路线还经过[[Warehouse Underground 仓库地下巢穴]]与[[Fortress 军火商要塞]]。",
        "people": "[[Boneyard 晒骨场 - Razor 剃刀（ID 821）|Razor 剃刀]]、[[Boneyard 晒骨场 - Jon Zimmerman 乔恩·齐默曼（ID 1654）|Jon Zimmerman 乔恩·齐默曼]]、[[Boneyard 晒骨场 - Gabriel 加百列（ID 954）|Gabriel 加百列]]。",
        "steps": """1. 与剃刀交谈，了解管理者对利刃帮的压迫以及乔希·齐默曼之死。
2. 接受协助并取得能揭露管理者行为的磁盘线索。
3. 选择直接对付管理者，或先打通军火商路线取得利刃帮所需武器。
4. 参加或触发对内城区管理者的反攻，并在冲突结束后与剃刀确认结果。""",
        "boundary": "`PIPBOY.MSG` 的标题是“Become a Blade”，但剃刀消息更明确地把终点描述为解放居民、推翻管理者和共同作战；本文不把没有直接台词支持的头衔、徽章或正式仪式写成奖励。",
    },
    "Deliver package from the Gun Runners": {
        "status": "可由剃刀—死亡爪—加百列—剃刀路线推进；标题说“包裹”，脚本实际以供武承诺和全局状态传递为主。",
        "areas": "[[Downtown 商业区]]、[[Warehouse 仓库区]]、[[Warehouse Underground 仓库地下巢穴]]、[[Fortress 军火商要塞]]。",
        "people": "[[Boneyard 晒骨场 - Razor 剃刀（ID 821）|Razor 剃刀]]、[[Boneyard 晒骨场 - Gabriel 加百列（ID 954）|Gabriel 加百列]]；[[Boneyard 晒骨场 - Zack 扎克（ID 1143）|Zack 扎克]]负责日常武器交易。",
        "steps": """1. 从剃刀处得知利刃帮需要军火商武器，但双方被死亡爪巢穴隔断。
2. 穿过仓库区，杀死地下层的死亡爪母兽并摧毁四枚死亡爪卵。
3. 向加百列确认巢穴已经清除。
4. 在奖励选项中说明有朋友需要武器；加百列同意让这些朋友取得军火。
5. 返回剃刀，使利刃帮能够武装并推进反攻。""",
        "boundary": "静态 MAP 没有与该任务标题对应的独立“包裹”顶层物品；加百列的可见台词是“告诉你的朋友他们有武器了”。因此文档不虚构一个必须搬运的箱子。",
    },
    "Find Children spy in the Followers": {
        "status": "Pip-Boy 标题、塔利乌斯任务台词与 `HEATHER.INT` 都存在，但五张晒骨场 MAP 没有实际放置 Heather 对象；按当前资源属于未完整落地的任务链。",
        "areas": "[[Library Underground 图书馆地下室]]；间谍脚本描述其在追随者驻地活动，但当前地图对象清点找不到该人物。",
        "people": "[[Boneyard 晒骨场 - Talius 塔利乌斯（ID 1423）|Talius 塔利乌斯]]；脚本目标 Heather 希瑟没有可用地图对象 ID。",
        "steps": """1. 与塔利乌斯讨论追随者内部正在泄露情报的间谍。
2. 理论上的调查对象是 Heather 希瑟；她的脚本包含否认、误导、索要 300 瓶盖和暴露大教堂袭击地点等分支。
3. 塔利乌斯的完成台词把结果描述为除去叛徒希瑟，并提供一把火焰喷射器。
4. 当前 MAP 没有放置希瑟，因此正常游戏流程无法仅凭这些地图对象完成上述链路。""",
        "boundary": "妮可让玩家去大教堂寻找劳拉、使用“红骑士”暗号，是另一条大教堂调查线索；它与“找出追随者内部间谍”有关联，但不能代替缺失的希瑟对象。",
    },
    "Fix hydroponic farms in Adytum": {
        "status": "人物、任务物品交接和结算台词均存在，是完整落地的晒骨场任务。",
        "areas": "[[Adytum 内城区]]；零件线索把玩家引向拾荒者失踪地点，修理与结算仍回到内城区。",
        "people": "[[Boneyard 晒骨场 - Miles 迈尔斯（ID 2497）|Miles 迈尔斯]]、[[Boneyard 晒骨场 - Sammael 萨缪尔（ID 2636）|Sammael 萨缪尔]]、[[Boneyard 晒骨场 - Smitty 史密蒂（ID 1356）|Smitty 史密蒂]]。",
        "steps": """1. 从迈尔斯处接受修复水耕农场的请求。
2. 向萨缪尔询问零件；他说明一名拾荒者带着零件失踪。
3. 找回农场零件并交给史密蒂修理。
4. 取回修好的零件，再交给迈尔斯完成任务。
5. 完成农场维修后，史密蒂会提出后续电浆步枪改造服务。""",
        "boundary": "电浆步枪改造是完成水耕任务后开放的后续服务，不是“修复水耕农场”本身的目标物。",
    },
}


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
    return title.removeprefix("Boneyard 晒骨场 - ").split("（ID", 1)[0].strip()


def key(region: Region, obj: dict) -> tuple[str, int, int]:
    return region.map_name, region.elevation, int(obj["object_id"])


def poster(output: Path) -> None:
    source = Image.open(REPO / "workspace/output/images/master/ART/INTRFACE/TWNMAP10.frm/TWNMAP10.frm.frames/sequence-00/frame-000.png").convert("RGBA")
    canvas = Image.new("RGBA", (1400, 900), (18, 18, 16, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 34)
    label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 22)
    meta_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    draw.text((700, 38), "Boneyard 晒骨场", font=title_font, fill=(241, 221, 172), anchor="mm")
    draw.text((700, 70), "TWNMAP10.FRM · 引擎城镇热点五区域", font=meta_font, fill=(189, 169, 124), anchor="mm")
    scale = 1.72
    left, top = 310, 92
    scaled = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.NEAREST)
    draw.rounded_rectangle((left - 10, top - 10, left + scaled.width + 10, top + scaled.height + 10), radius=18, fill=(7, 7, 6), outline=(89, 70, 46), width=5)
    canvas.alpha_composite(scaled, (left, top))
    anchors = [
        ("Adytum 内城区", "LAADYTUM · e0", 276, 239, 45, 655),
        ("Downtown 商业区", "LABLADES · e0", 229, 195, 45, 452),
        ("Library 图书馆", "LAFOLLWR · e0", 179, 185, 45, 252),
        ("Fortress 军火商要塞", "LAGUNRUN · e0", 346, 114, 1080, 216),
        ("Warehouse 仓库区", "LARIPPER · e0", 285, 159, 1080, 420),
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
    draw.text((700, 866), "标注点按原始 453×444 海报坐标保存；同一 MAP 的其他 elevation 在区域页展开", font=meta_font, fill=(189, 169, 124), anchor="mm")
    canvas.convert("RGB").save(output, quality=95)


def profile_maps(region: Region, characters: list[dict], attachments: Path) -> dict[int, str]:
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
    for obj in characters:
        oid = int(obj["object_id"])
        en, zh, _, _ = identity(obj, "", "")
        filename = f"{region.title}地图（人物标注，{en} {zh} ID {oid}高亮，完整原始画布）.png"
        target_path = attachments / filename
        if target_path.exists():
            outputs[oid] = filename
            continue
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
            l, t, r, b = (int(v) for v in label["label_box_canvas"])
            draw.line((tx, ty, (l + r) // 2, b if b <= ty else t), fill=color, width=1)
            draw.rectangle((l, t, r, b), fill=(0, 0, 0, 218), outline=color, width=1)
            value = label["display_name"]
            box = draw.textbbox((0, 0), value, font=font, stroke_width=1)
            x = l + max(4, (r - l - (box[2] - box[0])) // 2)
            y = t + max(2, (b - t - (box[3] - box[1])) // 2) - box[1]
            draw.text((x, y), value, font=font, fill="white", stroke_width=1, stroke_fill="black")
        canvas.save(target_path, format="PNG", compress_level=9)
        outputs[oid] = filename
    return outputs


def task_association(region: Region, oid: int) -> str:
    links = []
    if oid == 821:
        links += [TASKS[0][0], TASKS[1][0]]
    if oid in {954, 1143}:
        links.append(TASKS[1][0])
    if oid == 1423:
        links.append(TASKS[2][0])
    if oid in {2497, 1356, 2636}:
        links.append(TASKS[3][0])
    if not links:
        return ""
    return "# 任务关联\n\n" + "\n".join(f"- [[{name}|{name.split('（', 1)[0]}]]" for name in links)


def character_note(vault: Path, region: Region, obj: dict, proto: dict, proto_en: str, proto_zh: str,
                   lookup: dict, item_messages: dict, critter_messages: dict, note_index: dict,
                   map_filename: str, sprite_filename: str | None, art_name: str, attachments: Path) -> tuple[str, str, bool]:
    oid = int(obj["object_id"])
    en, zh, situation, named = identity(obj, proto_en, proto_zh)
    title = f"{en} {zh}（ID {oid}）"
    script = script_stem(obj)
    aliases = "\n".join(f"  - \"{value}\"" for value in (f"Boneyard 晒骨场 - {en} {zh}", f"{en} {zh}"))
    sprite = (f"![[{sprite_filename}|160]]\n\n该图取自 `{art_name}`，使用地图对象记录的方向 {obj['rotation']} 与第 0 帧；这是地图精灵，不是对话头像。"
              if sprite_filename else "资源索引指向的人物 FRM 当前没有可用导出帧，因此不借用其他人物造型。")
    resource_line = f"resource_script: {script}.INT\n" if script else ""
    sections = [f"""---
title: "{title}"
aliases:
{aliases}
tags: [辐射1, 人物, 地点, 晒骨场]
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
| 全名 | {'素材、人物原型或脚本直接提供姓名' if named else '普通人物类别或职务名称，不是专名'} |
| 游戏观察文字 | {bb.md(cath.character_observation(REPO, obj, proto, critter_messages))} |

# 地图信息

![[{map_filename}|900]]

橙色轮廓为本页人物，绿色轮廓为本层其他人物或生物；图片保留渲染器完整原始画布与原始像素尺寸，没有按标签边界裁图，也没有等比例缩小。

| 属性 | 值 |
|---|---|
| 出现地点 | [[Boneyard 晒骨场\\|晒骨场]] |
| 所属区域 | [[地点/Boneyard 晒骨场/{region.directory}/{region.title}\\|{region.title}]] |
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

{bb.head_assets(REPO, attachments, en, zh, script)}""",
        bb.game_data(obj, proto),
        bb.inventory_section(obj, lookup, item_messages, note_index),
    ]
    dialogue = cath.reachable_dialogue(REPO, obj)
    topics = topic_records(REPO, script)
    if topics:
        sections.append(render_topic_section(topics))
    if dialogue:
        sections.append(dialogue)
    sections.append(f"# 身份与处境\n\n{situation}")
    task = task_association(region, oid)
    if task:
        sections.append(task)
    return "\n\n".join(sections).rstrip() + "\n", title, named


def item_records(region: Region, characters: list[dict], objects: list[dict], lookup: dict,
                 item_messages: dict, note_index: dict, titles: dict[tuple[str, int, int], str]) -> tuple[list[tuple], list[tuple]]:
    items, containers = [], []
    for obj in characters:
        owner_title = titles[key(region, obj)]
        owner = f"[[{owner_title}\\|{short_title(owner_title)}]]"
        for entry in obj.get("inventory", []):
            kind, en, zh = bb.item_data(entry["item"], lookup, item_messages)
            items.append((kind, bb.item_link(en, zh, note_index), region.title, owner, int(entry["quantity"])))
    for obj in objects:
        if obj.get("prototype", {}).get("type") != "item" or int(obj.get("tile", -1)) < 0:
            continue
        kind, en, zh = bb.item_data(obj, lookup, item_messages)
        name = bb.item_link(en, zh, note_index)
        where = f"对象 ID {obj['object_id']}；tile {obj['tile']}"
        if obj["prototype"].get("subtype_name") == "container":
            contents = []
            for entry in obj.get("inventory", []):
                _, ien, izh = bb.item_data(entry["item"], lookup, item_messages)
                contents.append(f"{bb.item_link(ien, izh, note_index)} ×{entry['quantity']}")
            containers.append((region.title, f"{name}（{where}）", "<br>".join(contents) if contents else "空"))
        else:
            items.append((kind, name, region.title, where, 1))
    return items, containers


def task_rows_for(region: Region) -> list[str]:
    rows = []
    for filename, en, zh, oid, start_region, giver, _ in TASKS:
        if start_region == region.title:
            rows.append(f"| [[{filename}\\|{en} {zh}]] | {giver}（ID {oid}） | 本区域发起。 |")
        elif region.title in {"Warehouse Underground 仓库地下巢穴", "Fortress 军火商要塞"} and filename == TASKS[1][0]:
            rows.append(f"| [[{filename}\\|{en} {zh}]] | {giver}（ID {oid}） | 清除死亡爪或取得军火商供武承诺。 |")
    return rows or ["| — | — | 本区域没有独立的 Pip-Boy 任务发起项。 |"]


def write_region_page(vault_dir: Path, region: Region, characters: list[dict], creatures: list[dict], objects: list[dict], lookup: dict,
                      item_messages: dict, note_index: dict, titles: dict[tuple[str, int, int], str]) -> None:
    named_rows, generic_rows = [], []
    for index, obj in enumerate(sorted(characters, key=lambda o: int(o["object_id"])), 1):
        oid = int(obj["object_id"]); title = titles[key(region, obj)]
        row = f"| {index} | {oid} | [[{title}\\|{short_title(title)}]] | {f'`{script_stem(obj)}.INT`' if script_stem(obj) else '无独立脚本'} |"
        (named_rows if oid in NAMED else generic_rows).append(row)
    creature_rows = []
    for obj in creatures:
        oid, stem = int(obj["object_id"]), script_stem(obj)
        label = "Dog 狗" if stem == "DOG2" else "Deathclaw Egg 死亡爪卵" if stem == "EGGCLAW" else "Mother Deathclaw 死亡爪母兽"
        link = "[[Deathclaw 死亡爪|死亡爪母兽]]" if stem == "MOMCLAW" else label
        creature_rows.append(f"| {oid} | {link} | `{stem}.INT` | {obj['tile']} |")
    items, containers = item_records(region, characters, objects, lookup, item_messages, note_index, titles)
    item_rows = [f"| {kind} | {name} | {owner} | {qty} |" for kind, name, _, owner, qty in sorted(items)] or ["| — | — | — | 0 |"]
    container_rows = [f"| {name} | {contents} |" for _, name, contents in containers] or ["| — | 本区域没有容器。 |"]
    services = [f"| {a} | {b} | {c} |" for a, b, c in region.services] or ["| — | — | 完整脚本与对象清点没有确认面向玩家开放的商店或服务。 |"]
    page = f"""---
title: "{region.title}"
aliases: ["{region.english}", "{region.chinese}"]
tags: [辐射1, 地点, 晒骨场]
map: {region.map_name}
elevation: {region.elevation}
---

# {region.title}

## 名称

| 使用位置 | 名称 |
|---|---|
| 区域显示名 | {region.english} |
| 中文描述名 | {region.chinese} |
| 世界地图地点 | [[Boneyard 晒骨场\\|Boneyard 晒骨场]] |
| 资源地图 | `{region.map_name}.MAP` |
| 楼层 | elevation {region.elevation} |
| 地图编号 | {region.map_number} |

## 直接描述

{region.description}

## 地图

![[{region.title}地图（人物与物品标注，完整原始画布）.png|900]]

绿色轮廓与标签表示人物或生物，黄色轮廓与标签表示地面物品和容器。图片保留渲染器完整原始画布及原始像素尺寸，不按人物标签裁切，不缩放。它是 MAP 保存状态的静态快照，不执行人物移动、战斗、条件性生成或脚本改变。

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

下表按单件记录人物随身库存和地图顶层物品。容器实体及直接库存单列；静态库存不等同于任意剧情时刻的实时状态。

| 类型 | 物品名 | 人物或位置 | 数量 |
|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 容器 | 直接库存 |
|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 发起人 | 本区域中的环节 |
|---|---|---|
{chr(10).join(task_rows_for(region))}
"""
    (vault_dir / region.directory / f"{region.title}.md").write_text(page, encoding="utf-8")


def write_tasks(vault_dir: Path) -> None:
    by_title = {r.title: r for r in REGIONS}
    for filename, en, zh, oid, start_region, giver, summary in TASKS:
        task_dir = vault_dir / by_title[start_region].directory / "任务"
        task_dir.mkdir(parents=True, exist_ok=True)
        detail = TASK_DETAILS[en]
        page = f"""---
title: "{en} {zh}"
aliases: ["{en}", "{zh}"]
tags: [辐射1, 任务, 晒骨场]
quest_giver_map_object_id: {oid}
---

# {en} {zh}

## 名称

| 使用位置 | 名称 |
|---|---|
| Pip-Boy 英文 | {en}. |
| 当前中文 | {zh}。 |

## 任务概览

| 属性 | 内容 |
|---|---|
| Pip-Boy 分类 | Boneyard / 晒骨场 |
| 任务链上第一个发起人 | {giver}（地图对象 ID {oid}） |
| 接取区域 | [[{start_region}]] |
| 实现状态 | {detail['status']} |

## 涉及区域与人物

| 类型 | 内容 |
|---|---|
| 区域 | {detail['areas']} |
| 人物 | {detail['people']} |

## 流程

{detail['steps']}

## 资源边界

{summary}

{detail['boundary']}

## 资源依据

- `PIPBOY.MSG` 800–807 保存晒骨场任务标题。
- 发起人、分支、物品交接与完成状态来自相应人物 INT 脚本及消息关联表。
- 文档只陈述静态资源能直接确认的流程；未把地图中预置的条件性对象当作每次到访都存在。
"""
        (task_dir / f"{filename}.md").write_text(page, encoding="utf-8")


def write_home(vault_dir: Path, region_people: dict[str, list[dict]], region_creatures: dict[str, list[dict]],
               region_objects: dict[str, tuple[list[dict], dict]], titles: dict[tuple[str, int, int], str],
               item_messages: dict, note_index: dict) -> None:
    region_rows, named_rows, generic_rows, creature_rows, all_items, all_containers = [], [], [], [], [], []
    for region in REGIONS:
        people, creatures = region_people[region.title], region_creatures[region.title]
        region_rows.append(f"| [[{region.title}\\|{region.title}]] | `{region.map_name}.MAP` | {region.elevation} | {len(people)} | {len(creatures)} | {region.description.split('。')[0]}。 |")
        for obj in sorted(people, key=lambda o: int(o["object_id"])):
            oid, title = int(obj["object_id"]), titles[key(region, obj)]
            row = f"| [[{region.title}\\|{region.chinese}]] | {oid} | [[{title}\\|{short_title(title)}]] |"
            (named_rows if oid in NAMED else generic_rows).append(row)
        for obj in creatures:
            stem = script_stem(obj); label = "Dog 狗" if stem == "DOG2" else "Deathclaw Egg 死亡爪卵" if stem == "EGGCLAW" else "[[Deathclaw 死亡爪|Mother Deathclaw 死亡爪母兽]]"
            creature_rows.append(f"| [[{region.title}\\|{region.chinese}]] | {obj['object_id']} | {label} | `{stem}.INT` |")
        objects, lookup = region_objects[region.title]
        items, containers = item_records(region, people, objects, lookup, item_messages, note_index, titles)
        all_items.extend(items); all_containers.extend(containers)
    item_rows = [f"| {kind} | {name} | [[{region}]] | {owner} | {qty} |" for kind, name, region, owner, qty in sorted(all_items)]
    container_rows = [f"| [[{region}]] | {name} | {contents} |" for region, name, contents in all_containers]
    task_rows = [f"| [[{filename}\\|{en} {zh}]] | {giver}（ID {oid}） | [[{start_region}]] |" for filename, en, zh, oid, start_region, giver, _ in TASKS]
    page = f"""---
title: "Boneyard 晒骨场"
aliases: ["Boneyard", "Boneyard 晒谷场", "晒谷场", "晒骨场", "Los Angeles Boneyard"]
tags: [辐射1, 地点, 晒骨场]
world_map_grid: "15,18"
world_map_pixel: "775,925"
---

# Boneyard 晒骨场

## 名称

| 使用位置 | 名称 |
|---|---|
| 世界地图与 Pip-Boy | Boneyard / 晒骨场 |
| 城镇海报 | 洛杉矶县及沿海市区地图 |
| 知识库标题 | Boneyard 晒骨场 |
| 资源地图组 | `LAADYTUM.MAP`、`LABLADES.MAP`、`LAFOLLWR.MAP`、`LAGUNRUN.MAP`、`LARIPPER.MAP` |

## 地点概览

晒骨场位于世界地图网格 `(15, 18)`、像素坐标约 `(775, 925)`，建立在洛杉矶废墟上。五个城镇热点分别通往内城区、利刃帮商业区、天启追随者图书馆、军火商要塞和死亡爪占据的仓库区；三个额外 elevation 保存室内、地下层与剧情条件性对象，所以本包按八个区域页展开。

这里的核心冲突是内城区管理者、利刃帮和军火商之间被死亡爪阻断的力量关系。天启追随者则把地点线索延伸到[[Cathedral 大教堂|大教堂]]。日记中“靠近海边的地方，帮派聚集，生活不易”保留为提可的评价，不把人物说法写成地图资源本身的结论。

## 世界地图位置

世界地图网格为 `(15, 18)`，地点锚点像素坐标约为 `(775, 925)`；总览另见[[World Map 世界地图|World Map 世界地图]]。

## 地图

![[Boneyard 晒骨场城镇地图（区域标注）.jpg|900]]

海报原图是 `TWNMAP10.FRM`。五个标注点来自引擎城镇热点表，并按原图 453×444 坐标记录：内城区 `(276,239)`、商业区 `(229,195)`、图书馆 `(179,185)`、军火商要塞 `(346,114)`、仓库区 `(285,159)`。

## 区域与楼层

| 区域 | 资源地图 | elevation | 人物数 | 生物数 | 作用 |
|---|---|---:|---:|---:|---|
{chr(10).join(region_rows)}

## 商店和服务

| 区域 | 商店或服务 | 提供者 | 内容 |
|---|---|---|---|
| [[Adytum 内城区]] | 化学与水耕技术 | [[Boneyard 晒骨场 - Miles 迈尔斯（ID 2497）\\|Miles 迈尔斯]] | 发起并结算水耕农场维修。 |
| [[Adytum 内城区]] | 修理与武器改造 | [[Boneyard 晒骨场 - Smitty 史密蒂（ID 1356）\\|Smitty 史密蒂]] | 修理农场零件；完成任务后处理电浆步枪改造。 |
| [[Underground 地下与室内层]] | 物资交易 | [[Boneyard 晒骨场 - Tine 提恩（ID 633）\\|Tine 提恩]] | 内城区商店。 |
| [[Library 图书馆]] | 组织与大教堂情报 | [[Boneyard 晒骨场 - Nicole 妮可（ID 1298）\\|Nicole 妮可]] | 提供追随者和大教堂调查线索。 |
| [[Fortress 军火商要塞]] | 武器交易 | [[Boneyard 晒骨场 - Zack 扎克（ID 1143）\\|Zack 扎克]] | 交易武器和弹药。 |

## 地图中的人物

完整对象清点得到 137 名人物。专名与普通人物分开列出；同类人物按地图对象 ID 逐个落页。另有 6 个生物对象，不计入人物数。

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
{chr(10).join(creature_rows)}

## 地图中的物品

下表汇总人物随身库存和地图顶层物品；容器实体及其直接库存单列。数据来自 MAP 保存状态，不等同于任意剧情时刻的实时库存。

| 类型 | 物品名 | 地图区域 | 容器或人物 | 数量 |
|---|---|---|---|---:|
{chr(10).join(item_rows)}

## 容器

| 地图区域 | 容器名 | 物品列表 |
|---|---|---|
{chr(10).join(container_rows)}

## 任务

| 任务名 | 任务链上第一个发起人 | 接取区域 |
|---|---|---|
{chr(10).join(task_rows)}

`PIPBOY.MSG` 还保留“为罗梅罗送纪念品”“拯救贾森·齐默曼”“阻止黑帮攻击内城区”三条标题。当前五张晒骨场 MAP 的实际人物对象中没有罗梅罗、朱莉安娜或仍可营救的贾森对象；本包把这些标题保留为未完整落地或被最终剧情替代的任务残留，不编造发起人 ID，也不生成伪任务主页。

## 来源边界

- 地点坐标、地图编号与区域名称来自导出的世界地图、`MAP.MSG` 和结构化 MAP。
- 人物、物品、容器和楼层来自五张 MAP 的完整对象清点；人物身份、服务与任务条件来自对应 INT 脚本和当前中文消息资源。
- 所有区域总图与人物位置图保留完整渲染画布和原始像素尺寸；没有按标签框裁切，也没有缩放。
- “靠近海边的地方，帮派聚集，生活不易”来自游玩日记中的提可评价。
"""
    (vault_dir / "Boneyard 晒骨场.md").write_text(page, encoding="utf-8")


def main() -> None:
    args = parse_args()
    vault = args.vault_root.resolve()
    vault_dir = vault / "地点/Boneyard 晒骨场"
    vault_dir.mkdir(parents=True, exist_ok=True)
    note_index = bb.build_note_index(vault)
    game = REPO / "workspace/output/text/data/TEXT/ENGLISH/GAME"
    critter_messages = bb.message_groups(game / "PRO_CRIT.json")
    item_messages = bb.message_groups(game / "PRO_ITEM.json")
    homepage_attachments = vault_dir / "attachments"
    homepage_attachments.mkdir(exist_ok=True)
    poster(homepage_attachments / "Boneyard 晒骨场城镇地图（区域标注）.jpg")
    region_people, region_creatures, region_objects, titles = {}, {}, {}, {}
    evidence = {
        "location": "Boneyard",
        "source_maps": ["LAADYTUM.MAP", "LABLADES.MAP", "LAFOLLWR.MAP", "LAGUNRUN.MAP", "LARIPPER.MAP"],
        "town_poster": "TWNMAP10.FRM",
        "world_map": {"grid": [15, 18], "pixel": [775, 925]},
        "maps": [],
        "character_notes": 0,
        "creature_objects": 0,
        "task_pages": [row[0] for row in TASKS],
        "unplaced_task_residue": ["Deliver Locket for Romero", "Rescue Jason Zimmerman", "Stop the Gangs from attacking Adytum"],
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
        objects = [o for o in map_doc["objects"]["entries"] if int(o.get("elevation_group", -1)) == region.elevation]
        critters = [o for o in objects if o.get("prototype", {}).get("type") == "critter" and int(o.get("tile", -1)) >= 0]
        creatures = [o for o in critters if script_stem(o) in CREATURE_SCRIPTS]
        people = [o for o in critters if script_stem(o) not in CREATURE_SCRIPTS]
        region_people[region.title], region_creatures[region.title] = people, creatures
        region_objects[region.title] = (objects, lookup)
        render_root = REPO / "workspace/output/maps-rendered" / region.map_name
        src_map = render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png"
        shutil.copyfile(src_map, attachments / f"{region.title}地图（人物与物品标注，完整原始画布）.png")
        maps = profile_maps(region, people, people_attachments) if people else {}
        render_doc = load_json(render_root / f"elevation-{region.elevation}-floor-walls-doors-scenery-items-critters.json")
        render_by_id = {
            int(o["object_id"]): o
            for o in render_doc["critters"] + render_doc.get("missing_critter_art", [])
        }
        for obj in people:
            oid = int(obj["object_id"])
            proto = lookup[("critter", int(obj["prototype"]["list_index"]))]
            proto_en, proto_zh = critter_messages.get(int(proto["message_id"]), ("Unknown", "未知人物"))
            en, zh, _, is_named = identity(obj, proto_en, proto_zh)
            render_entry = render_by_id[oid]
            frm_stem = Path(render_entry["filename"]).stem.upper()
            source = bb.find_critter_frame(REPO, render_entry["filename"], int(obj["rotation"]))
            sprite_name = None
            if source:
                sprite_name = f"{en} {zh}（ID {oid}）- 地图人物精灵（{frm_stem}，方向{obj['rotation']}，帧0）.png"
                shutil.copyfile(source, people_attachments / sprite_name)
            text, title, named = character_note(vault, region, obj, proto, proto_en, proto_zh, lookup, item_messages,
                                                critter_messages, note_index, maps[oid], sprite_name, f"{frm_stem}.FRM", people_attachments)
            full_title = f"Boneyard 晒骨场 - {title}"
            target = (named_dir if named else generic_dir) / f"{full_title}.md"
            if target.exists() and not args.overwrite:
                raise FileExistsError(target)
            target.write_text(text, encoding="utf-8")
            titles[key(region, obj)] = full_title
        top_items = [o for o in objects if o.get("prototype", {}).get("type") == "item" and int(o.get("tile", -1)) >= 0]
        containers = [o for o in top_items if o.get("prototype", {}).get("subtype_name") == "container"]
        carried = [entry for o in people for entry in o.get("inventory", [])]
        evidence["maps"].append({
            "map": region.map_name,
            "elevation": region.elevation,
            "region": region.title,
            "people": len(people),
            "named_people": sum(int(o["object_id"]) in NAMED for o in people),
            "generic_people": sum(int(o["object_id"]) not in NAMED for o in people),
            "creatures": len(creatures),
            "objects": len(objects),
            "top_level_items": len(top_items),
            "containers": len(containers),
            "ground_non_container_items": len(top_items) - len(containers),
            "carried_inventory_entries": len(carried),
            "carried_inventory_quantity": sum(int(entry["quantity"]) for entry in carried),
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
    sync_tree(vault_dir, REPO)
    evidence_path = REPO / "workspace/output/maps-knowledge/boneyard-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated Boneyard package: {len(REGIONS)} regions, {evidence['character_notes']} character notes, {evidence['creature_objects']} creature objects, {len(TASKS)} task pages")


if __name__ == "__main__":
    main()
