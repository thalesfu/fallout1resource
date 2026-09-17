#!/usr/bin/env python3
"""Generate Obsidian notes for every Fallout 1 critter prototype, with combat analysis.

Inputs: workspace/output/critters/catalog.json (build_critter_catalog.py),
workspace/output/rules/combat-tables.json (extract_combat_tables.py),
workspace/output/rules/encounter-loadouts.csv (scan_encounter_loadouts.py).

Prototypes that a vault note already covers (a note under 生物/, or a single-instance prototype
whose only placement already has a character note) are not recreated: their combat section is
appended to that note inside a regenerable marker block.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BEGIN, END = "<!-- 战斗资料:begin 由 fallout1resource/scripts/generate_critter_docs.py 生成 -->", "<!-- 战斗资料:end -->"
DAMAGE_ZH = {"normal": "普通", "laser": "激光", "fire": "火焰", "plasma": "等离子",
             "electrical": "电击", "emp": "电磁脉冲", "explosion": "爆炸"}
BODY_ZH = {"biped": "双足", "quadruped": "四足", "robotic": "机械"}
STAT_ROWS = [("ST", "力量"), ("PE", "感知"), ("EN", "耐力"), ("CH", "魅力"), ("IN", "智力"), ("AG", "敏捷"), ("LK", "幸运")]
COMBAT_SKILLS = [("SMALL_GUNS", "小型枪械"), ("BIG_GUNS", "大型枪械"), ("ENERGY_WEAPONS", "能量型武器"),
                 ("UNARMED", "肉搏"), ("MELEE_WEAPONS", "近战武器"), ("THROWING", "抛掷力")]
KILL_TYPE_KEYS = [
    "KILL_TYPE_MAN", "KILL_TYPE_WOMAN", "KILL_TYPE_CHILD", "KILL_TYPE_SUPER_MUTANT", "KILL_TYPE_GHOUL",
    "KILL_TYPE_BRAHMIN", "KILL_TYPE_RADSCORPION", "KILL_TYPE_RAT", "KILL_TYPE_FLOATER", "KILL_TYPE_CENTAUR",
    "KILL_TYPE_ROBOT", "KILL_TYPE_DOG", "KILL_TYPE_MANTIS", "KILL_TYPE_DEATH_CLAW", "KILL_TYPE_PLANT",
]
KILL_TYPE_DIR = {
    "KILL_TYPE_MAN": "Men 男性人类", "KILL_TYPE_WOMAN": "Women 女性人类", "KILL_TYPE_CHILD": "Children 儿童",
    "KILL_TYPE_SUPER_MUTANT": "Super Mutants 超级变种人", "KILL_TYPE_GHOUL": "Ghouls 尸鬼",
    "KILL_TYPE_BRAHMIN": "Brahmin 双头牛", "KILL_TYPE_RADSCORPION": "Radscorpions 辐射蝎",
    "KILL_TYPE_RAT": "Rats 老鼠", "KILL_TYPE_FLOATER": "Floaters 浮游者", "KILL_TYPE_CENTAUR": "Centaurs 半人马",
    "KILL_TYPE_ROBOT": "Robots 机器人", "KILL_TYPE_DOG": "Dogs 犬类", "KILL_TYPE_MANTIS": "Manti 螳螂",
    "KILL_TYPE_DEATH_CLAW": "Deathclaws 死亡爪", "KILL_TYPE_PLANT": "Master 大师",
}
# 人工撰写的族群战斗策略（结论基于本仓库解出的数值、暴击表与 AI 参数）
FAMILY_NOTES: dict[str, dict[str, list[str]]] = {
    "KILL_TYPE_MAN": {"打法": [
        "人类敌人大多穿护甲、拿枪，是全游戏最依赖“先手”的对手：优先用高战斗顺序抢第一回合，用瞄准射击直接打掉威胁最大的持枪者。",
        "瞄准眼睛（远程 −60 命中）是对人类收益最高的选择：暴击加成最高，容易打出致盲和击倒，之后对手几乎无法还手。命中不足时退而求其次打头部（−40）。",
        "人类会因残废或失明而逃跑（AI 的 `hurt_too_much`），打腿能让追击型敌人彻底失去威胁。",
        "多数人类没有伤害阈值，普通伤害就够用；穿动力装甲的敌人（伤害抗性极高）才需要等离子、电磁脉冲或高单发伤害武器。"]},
    "KILL_TYPE_WOMAN": {"打法": ["与男性人类共用同一套战斗逻辑和暴击结构，差别只在个体数值与装备。参见 [[Men 男性人类 战斗策略]]。"]},
    "KILL_TYPE_CHILD": {"打法": ["儿童不是战斗单位，10 点生命、无抗性。攻击儿童会带来严重的声望后果（“杀童者”），除非刻意扮演恶人，否则不要打。"]},
    "KILL_TYPE_SUPER_MUTANT": {"打法": [
        "超级变种人是中后期的主要压力来源：生命 40–250，普通伤害抗性 15–60%，还常带伤害阈值，小口径武器会被抗性吃掉大半。",
        "优先用高单发伤害（狙击枪、.223 手枪、火箭筒）或能量武器；连发小口径对高抗性目标效率很差。",
        "它们的暴击表不像人类那样容易被一击瘫痪，眼睛仍是最佳瞄准点，但更现实的做法是靠伤害硬砸。",
        "手持迷你机枪或火焰喷射器的变种人威胁最高，优先集火；注意它们的连发会波及队友。",
        "游玩中听来的传闻与见闻记在 [[Mutants 变种人]]。"]},
    "KILL_TYPE_GHOUL": {"打法": [
        "尸鬼没有伤害阈值也没有伤害抗性，任何武器都能打满伤害，是性价比最高的经验来源之一。",
        "生命 12–100，护甲等级低（4–9），命中率很高，瞄准眼睛几乎稳定触发暴击。",
        "大墓地的尸鬼多数可以用对话和平解决，动手前先确认是否影响任务与声望。"]},
    "KILL_TYPE_BRAHMIN": {"打法": ["双头牛是牲畜，生命 35–40、护甲等级偏高但不会主动攻击。杀死商队的牛会招来商队敌意。"]},
    "KILL_TYPE_RADSCORPION": {"打法": [
        "辐射蝎近战，速度快、护甲等级偏高（15–27），但生命只有 26–34，普通伤害抗性最多 20%。",
        "它们是纯近战：拉开距离用枪风筝是最稳的打法；沙荫镇早期用 10mm 手枪配子弹足够。",
        "打腿（残废）能让它追不上你。带 [[Animal Friend 动物之友]] 时它们不会主动攻击。",
        "尾刺造成毒素，战后注意用抗毒药或医生技能处理。",
        "NPC 对辐射蝎的说法和巢穴位置记在 [[Scorpions 辐射蝎]]。"]},
    "KILL_TYPE_RAT": {"打法": [
        "老鼠是最弱的敌人（生命 6–26），但成群出现，早期容易被围。站在走廊或门口，让它们一次只能上来一两只。",
        "近战武器就能一击一只，不必浪费子弹。发光变种老鼠等强化版本才需要认真对待。",
        "带 [[Animal Friend 动物之友]] 时不会主动攻击。"]},
    "KILL_TYPE_FLOATER": {"打法": [
        "浮游者生命 50–75，有伤害阈值 3–4 和 20–30% 伤害抗性，近战攻击会造成毒素。",
        "属于军事基地和闪光之地的中期怪，远程消耗是最安全的打法，避免被贴身连续攻击。"]},
    "KILL_TYPE_CENTAUR": {"打法": [
        "半人马生命 94–130、伤害抗性 30–40%，是变种人阵营中最耐打的杂兵。",
        "小口径武器几乎无效，用能量武器或高伤害单发；它们移动慢，可以边退边打。"]},
    "KILL_TYPE_ROBOT": {"打法": [
        "机器人有伤害阈值 4–12 和 20–30% 伤害抗性，低伤害武器可能完全破不了防。",
        "电磁脉冲（EMP）是针对机器人的伤害类型；没有 EMP 武器时用火箭筒、等离子等高单发伤害。",
        "机器人不会因残废逃跑，也不受致盲之外的多数减益影响，需要正面硬拼，建议先手集火。"]},
    "KILL_TYPE_DOG": {"打法": [
        "犬类速度快（行动点 7–13）、伤害抗性 15–25%，但生命偏低，属于“先手咬人”的骚扰型敌人。",
        "它们会迅速贴近，近战武器或霰弹枪比狙击更实用；打腿可以直接废掉机动性。"]},
    "KILL_TYPE_MANTIS": {"打法": ["螳螂生命 20，护甲等级低，威胁主要来自成群与突进。近战即可清理，注意别被包围。"]},
    "KILL_TYPE_DEATH_CLAW": {"打法": [
        "死亡爪是前期绝对不能硬碰的敌人：生命 60 起，伤害抗性 20–40%，行动点 10–13，近战伤害极高。",
        "唯一稳妥的打法是远程风筝：在它进入攻击距离前持续输出，利用地形和门阻断视线。",
        "打腿残废能大幅削弱它的追击能力，是最有价值的瞄准部位之一。",
        "哈勃城任务中的死亡爪巢穴还有垂死的变种人，可以先对话拿情报再动手。",
        "形象、素材与游玩记录见 [[Deathclaw 死亡爪]]。"]},
    "KILL_TYPE_PLANT": {"打法": [
        "大师生命 500、护甲等级 30、伤害阈值 5、伤害抗性 40%，是全游戏数值最高的单体，正面强攻需要顶级装备。",
        "更划算的结局是用对话：掌握变种人不育的证据后可以说服他自毁，同样完成流程。",
        "若选择强攻，先清掉周围随从，用高单发伤害武器，并准备大量治疗物品。"]},
}


def kt_key(kill_type) -> str:
    """catalog stores kill_type as the numeric id; family tables are keyed by name."""
    return KILL_TYPE_KEYS[kill_type] if isinstance(kill_type, int) else kill_type


def load(path: Path):
    return json.loads(path.read_text())


def slug(name: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "", name).strip()


def note_title(c: dict) -> str:
    en = (c["name_en"] or "Unnamed").strip()
    zh = (c["name_zh"] or "").strip()
    return slug(f"{en} {zh}（原型 {c['prototype_id']}）")


def resistance_table(stats: dict) -> tuple[str, list[str]]:
    rows, weak = [], []
    for key, zh in DAMAGE_ZH.items():
        suffix = key.upper() if key != "normal" else "NORMAL"
        dt, dr = stats[f"DT_{suffix}"], stats[f"DR_{suffix}"]
        rows.append((zh, dt, dr))
    table = "\n".join(f"| {zh} | {dt} | {dr}% |" for zh, dt, dr in rows)
    best = min(rows, key=lambda r: (r[2], r[1]))
    worst = max(rows, key=lambda r: (r[2], r[1]))
    weak.append(f"最吃伤害的类型：**{best[0]}**（阈值 {best[1]}、抗性 {best[2]}%）")
    if worst[2] >= 50:
        weak.append(f"最难打穿的类型：**{worst[0]}**（阈值 {worst[1]}、抗性 {worst[2]}%）")
    return table, weak


def crit_profile(crit_rows: list[dict], kill_type_id: int) -> tuple[str, list[str]]:
    rows = [r for r in crit_rows if r["kill_type_id"] == kill_type_id]
    lines, hints = [], []
    for r in sorted(rows, key=lambda r: r["hit_location_id"]):
        mults = [e["damage_multiplier"] for e in r["effects"]]
        flags = sorted({f["zh"] for e in r["effects"] for f in e["flags"]} |
                       {f["zh"] for e in r["effects"] for f in e["massive_flags"]})
        lines.append(f"| {r['hit_location_zh']} | {min(mults):g}–{max(mults):g} 倍 | {('、'.join(flags)) or '—'} |")
    if rows:
        best = max(rows, key=lambda r: sum(e["damage_multiplier"] for e in r["effects"]))
        deadly = [r for r in rows if any("立即死亡" in f["zh"] for e in r["effects"] for f in e["flags"] + e["massive_flags"])]
        hints.append(f"暴击收益最高的部位：**{best['hit_location_zh']}**")
        if deadly:
            hints.append("可能直接秒杀的部位：" + "、".join(r["hit_location_zh"] for r in deadly))
    return "\n".join(lines), hints


def weapon_line(item: dict, stats: dict) -> str:
    w = item["weapon"]
    melee = w["animation_code"] in (1, 2, 3, 4)  # punch/kick/swing/thrust 动作视为近战
    bonus = stats["MELEE_DAMAGE"] if melee else 0
    dmg = f"{w['min_damage']}–{w['max_damage'] + bonus}"
    shots = stats["MAX_AP"] // w["action_point_cost_1"] if w["action_point_cost_1"] else 0
    burst = f"，连发 {w['rounds']} 发" if w["rounds"] > 1 else ""
    return (f"| {item['name_zh'] or item['name_en']} | {dmg} | {DAMAGE_ZH.get(w['damage_type'], w['damage_type'])} | "
            f"{w['max_range_1']} 格 | {w['action_point_cost_1']} AP（约 {shots} 次/回合）{burst} | 力量需求 {w['min_strength']} |")


def render(c: dict, items: dict, combat: dict, loadouts: dict[int, list[int]], full: bool) -> str:
    stats, ai = c["stats"], c["ai"] or {}
    res_table, weak = resistance_table(stats)
    crit_table, crit_hints = crit_profile(combat["crit_succ_eff"], c["kill_type"])
    equipped = Counter()
    for inst in c["instances"]:
        for it in inst["inventory"]:
            if it["slot"] in ("right_hand", "left_hand"):
                equipped[it["pid"]] += it["quantity"]
    worn = Counter(it["pid"] for inst in c["instances"] for it in inst["inventory"] if it["slot"] == "worn")
    carried = Counter(it["pid"] for inst in c["instances"] for it in inst["inventory"] if it["slot"] is None)

    weapon_rows = [weapon_line(items[str(pid)], stats) for pid in equipped if items.get(str(pid), {}).get("weapon")]
    unarmed = f"| 徒手 | 1–{stats['MELEE_DAMAGE'] + 2} | 普通 | 1 格 | 3 AP（约 {stats['MAX_AP'] // 3} 次/回合） | — |"
    if not weapon_rows:
        weapon_rows = [unarmed]

    out = []
    if full:
        out += [
            "---", f"title: {note_title(c)}", "tags:", "  - 辐射1", "  - 生物",
            f"prototype_id: {c['prototype_id']}", f"pid: \"0x{c['pid'] & 0xFFFFFFFF:08X}\"",
            f"kill_type: {c['kill_type_zh']}", f"experience: {c['experience']}", "---", "",
            f"# {note_title(c)}", "",
            f"返回：[[{KILL_TYPE_DIR[kt_key(c["kill_type"])]} 战斗策略]] · [[生物 总览]]", "",
            "## 身份", "",
            "| 项目 | 内容 |", "|---|---|",
            f"| 英文名 | {c['name_en'] or '—'} |", f"| 中文名 | {c['name_zh'] or '—'} |",
            f"| 原型文件 | `{c['file']}`（ID {c['prototype_id']}，PID `0x{c['pid'] & 0xFFFFFFFF:08X}`） |",
            f"| 种类 | {c['kill_type_zh']}（{c['kill_type']}） |",
            f"| 体型 | {BODY_ZH.get(c['body_type'], c['body_type'])} |",
            f"| 原型脚本 | {'`' + c['script'] + '`' if c['script'] else '无'} |",
            f"| 击杀经验 | {c['experience']} |",
            f"| 描述文本 | {c['desc_zh'] or '游戏资源没有提供描述文本'} |", "",
        ]
    else:
        out += [BEGIN, "", "## 战斗资料", "",
                f"数值来自生物原型 `{c['file']}`（ID {c['prototype_id']}）。族群打法见 [[{KILL_TYPE_DIR[kt_key(c["kill_type"])]} 战斗策略]]。", ""]

    out += [
        "## 属性", "",
        "| 属性 | 值 | 派生 | 值 |", "|---|---|---|---|",
    ]
    derived = [("生命值", stats["MAX_HP"]), ("行动点", stats["MAX_AP"]), ("护甲等级", stats["AC"]),
               ("战斗顺序", stats["SEQUENCE"]), ("治疗速率", stats["HEALING_RATE"]), ("暴击率", f"{stats['CRITICAL_CHANCE']}%"),
               ("近战伤害", stats["MELEE_DAMAGE"])]
    for i, (key, zh) in enumerate(STAT_ROWS):
        d = derived[i] if i < len(derived) else ("", "")
        out.append(f"| {zh} | {stats[key]} | {d[0]} | {d[1]} |")
    out += ["", "## 抗性", "", "| 伤害类型 | 伤害阈值 | 伤害抗性 |", "|---|---|---|", res_table, ""]
    out += [f"- {w}" for w in weak]
    out += ["", "## 攻击手段", "", "| 武器 | 伤害 | 类型 | 射程 | 消耗 | 备注 |", "|---|---|---|---|---|---|"] + weapon_rows
    out += ["", "本表按原型行动点估算每回合攻击次数，未计入瞄准加成与 AI 的实际行为。", ""]

    skills = "、".join(f"{zh} {c['skill_values'][key]}%" for key, zh in COMBAT_SKILLS if c["skill_points"][key])
    out += ["## 技能", "", (f"有加点的战斗技能：{skills}。" if skills else "原型没有额外技能加点，战斗技能为属性推算的基础值。"), ""]

    if ai:
        out += ["## AI 行为", "",
                f"- AI 包：`{ai.get('name')}`（编号 {c['ai_packet']}）",
                f"- 生命低于 **{ai.get('min_hp')}** 点时逃跑",
                f"- 攻击所需最低命中率：{ai.get('min_to_hit')}%；脱离战斗距离：{ai.get('max_dist')} 格",
                f"- 侵略性：{ai.get('aggression')}；使用次要攻击方式的频率：1/{ai.get('secondary_freq')}；瞄准部位的频率：1/{ai.get('called_freq')}",
                f"- 受下列伤害时逃跑：{ai.get('hurt_too_much') or '无'}", ""]

    out += ["## 瞄准部位与暴击", "", "| 部位 | 伤害倍率 | 可能附加效果 |", "|---|---|---|", crit_table, ""]
    out += [f"- {h}" for h in crit_hints]
    out += ["", "瞄准命中惩罚：眼睛 −60、头部 −40、四肢 −30/−20、腹股沟 −30（近战与徒手减半）；瞄准时暴击率获得等额加成。", ""]

    if worn or carried or loadouts.get(c["prototype_id"]):
        out += ["## 携带物品", ""]
        if worn:
            out += ["- 穿戴：" + "、".join(f"{items[str(p)]['name_zh'] or items[str(p)]['name_en']}×{n}" for p, n in worn.items())]
        if carried:
            out += ["- 身上物品：" + "、".join(f"{items[str(p)]['name_zh'] or items[str(p)]['name_en']}×{n}" for p, n in carried.items())]
        if loadouts.get(c["prototype_id"]):
            names = "、".join(loadouts[c["prototype_id"]])
            out += [f"- 脚本生成时可能获得（候选，来自遭遇脚本扫描）：{names}"]
        out += [""]

    if c["instances"]:
        out += ["## 出现位置", "", "| 地图 | 楼层 | 对象 ID | 生命 | 脚本 | 对应笔记 |", "|---|---|---|---|---|---|"]
        for inst in sorted(c["instances"], key=lambda i: (i["map"], i["object_id"]))[:60]:
            note = f"[[{inst['note']}]]" if inst["note"] else "—"
            out.append(f"| {inst['map']} | {inst['elevation']} | {inst['object_id']} | {inst['hp']} | "
                       f"{'`' + inst['script'] + '`' if inst['script'] else '—'} | {note} |")
        if len(c["instances"]) > 60:
            out.append(f"\n（共 {len(c['instances'])} 处，表中只列前 60 处。）")
        out += [""]
    elif full:
        out += ["## 出现位置", "", "该原型不在任何地图文件里，由随机遭遇或剧情脚本动态生成。", ""]

    if full:
        out += ["## 来源", "",
                f"- 数值：`PROTO/CRITTERS/{c['file']}`；AI 参数：`DATA/AI.TXT`；名称：`PRO_CRIT.MSG`。",
                "- 暴击与瞄准数据：fallout1-ce 静态表，见代码仓库 `workspace/output/rules/combat-tables.json`。", ""]
    else:
        out += [END, ""]
    return "\n".join(out)


def render_family(kill_type: str, members: list[dict], combat: dict, link: dict[int, str]) -> str:
    title = KILL_TYPE_DIR[kt_key(kill_type)]
    crit_table, crit_hints = crit_profile(combat["crit_succ_eff"], members[0]["kill_type"])
    rows = "\n".join(
        f"| [[{link.get(m['prototype_id'], note_title(m))}]] | {m['stats']['MAX_HP']} | {m['stats']['AC']} | {m['stats']['MAX_AP']} | "
        f"{m['stats']['DT_NORMAL']}/{m['stats']['DR_NORMAL']}% | {m['experience']} | {len(m['instances'])} |"
        for m in sorted(members, key=lambda m: (-m["stats"]["MAX_HP"], m["prototype_id"]))
    )
    tips = "\n".join(f"- {t}" for t in FAMILY_NOTES[kt_key(kill_type)]["打法"])
    return f"""---
tags:
  - 辐射1
  - 生物
  - 战斗策略
---

# {title} 战斗策略

返回：[[生物 总览]]

共 {len(members)} 个生物原型。数值、AI 参数和暴击表均来自游戏资源与引擎静态表，详见各原型页。

## 打法要点

{tips}

## 瞄准部位与暴击（本族群共用）

| 部位 | 伤害倍率 | 可能附加效果 |
|---|---|---|
{crit_table}

{chr(10).join('- ' + h for h in crit_hints)}

## 原型一览

| 原型 | 生命 | 护甲等级 | 行动点 | 阈值/抗性 | 经验 | 地图实例 |
|---|---|---|---|---|---|---|
{rows}
"""


def render_index(groups: dict[str, list[dict]]) -> str:
    rows = "\n".join(
        f"| [[{KILL_TYPE_DIR[kt_key(kt)]} 战斗策略]] | {len(ms)} | {min(m['stats']['MAX_HP'] for m in ms)}–{max(m['stats']['MAX_HP'] for m in ms)} | "
        f"{min(m['experience'] for m in ms)}–{max(m['experience'] for m in ms)} |"
        for kt, ms in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    )
    return f"""---
tags:
  - 辐射1
  - 生物
---

# 生物 总览

《辐射 1》共 {sum(len(v) for v in groups.values())} 个生物原型，按引擎的“击杀种类”分成 {len(groups)} 类。暴击效果表按种类区分，所以同族群的弱点是共通的，战斗策略按族群整理。

另见：[[技能 总览]] · [[Perk 总览]] · [[特性 总览]]

| 族群 | 原型数 | 生命范围 | 击杀经验 |
|---|---|---|---|
{rows}

## 怎么读这些页面

每个原型页给出：属性、七种伤害类型的阈值与抗性、攻击手段与每回合攻击次数、AI 的逃跑血线与行为频率、按部位的暴击倍率，以及它在哪些地图上出现、身上带什么。

数值取自游戏原型文件，地图实例取自地图文件；随机遭遇脚本动态生成的敌人没有地图实例，装备只能从脚本扫描得到候选值，已在页面中标注。
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--combat-tables", type=Path, required=True)
    ap.add_argument("--loadouts", type=Path, required=True)
    ap.add_argument("--vault-game-root", type=Path, required=True)
    ap.add_argument("--apply", action="store_true", help="write notes (default: report only)")
    args = ap.parse_args()

    cat = load(args.catalog)
    critters, items = cat["critters"], cat["items"]
    combat = load(args.combat_tables)
    loadouts: dict[int, list[int]] = defaultdict(list)
    with args.loadouts.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = int(row["item_pid"])
            name = items.get(str(pid), {}).get("name_zh") or items.get(str(pid), {}).get("name_en") or f"物品 {pid}"
            proto_id = int(row["critter_prototype_id"])
            if name not in loadouts[proto_id]:
                loadouts[proto_id].append(name)

    existing: dict[int, Path] = {}
    for path in args.vault_game_root.rglob("*.md"):
        if "人物" not in path.parts and "生物" not in path.parts:
            continue
        if re.search(r"（原型 \d+）$", path.stem):
            continue  # this generator's own prototype pages
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^prototype_id:\s*(\d+)\s*$", text[:600], re.M)
        if not m:
            continue
        proto_id = int(m.group(1))
        if "生物" in path.parts:
            existing[proto_id] = path
        elif proto_id not in existing:
            existing.setdefault(proto_id, path)

    root = args.vault_game_root / "生物"
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in critters:
        groups[c["kill_type"]].append(c)

    new_notes: dict[Path, str] = {}
    appended: list[tuple[Path, str]] = []
    appended_targets: dict[int, Path] = {}
    for c in critters:
        target = existing.get(c["prototype_id"])
        single_named = target is not None and ("生物" in target.parts or len(c["instances"]) <= 1)
        if single_named:
            appended.append((target, render(c, items, combat, loadouts, full=False)))
            appended_targets[c["prototype_id"]] = target
        else:
            new_notes[root / KILL_TYPE_DIR[kt_key(c["kill_type"])] / f"{note_title(c)}.md"] = render(c, items, combat, loadouts, full=True)
    link = {proto_id: path.stem for proto_id, path in appended_targets.items()}
    for kt, members in groups.items():
        new_notes[root / KILL_TYPE_DIR[kt_key(kt)] / f"{KILL_TYPE_DIR[kt_key(kt)]} 战斗策略.md"] = render_family(kt, members, combat, link)
    new_notes[root / "生物 总览.md"] = render_index(groups)

    print(f"新建/覆盖 {len(new_notes)} 篇，追加战斗资料到 {len(appended)} 篇已有笔记")
    if not args.apply:
        for path in list(new_notes)[:5]:
            print("  例:", path)
        for path, _ in appended[:5]:
            print("  追加:", path)
        return 0

    for path, text in new_notes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for path, block in appended:
        text = path.read_text(encoding="utf-8")
        if BEGIN in text:
            text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", block, text, flags=re.S)
        else:
            text = text.rstrip() + "\n\n" + block
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
