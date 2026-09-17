#!/usr/bin/env python3
"""Generate Obsidian notes for Fallout 1 skills, perks and traits.

Input: workspace/output/rules/{skills,perks}.json (scripts/extract_skill_perk_rules.py).
Mechanics text below was verified against fallout1-ce source and INT disassembly;
see notes/规则挖掘/技能与Perk.md for the evidence trail.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

STAT_ZH = {"ST": "力量", "PE": "感知", "EN": "耐力", "CH": "魅力", "IN": "智力", "AG": "敏捷", "LK": "幸运"}

# ---------------------------------------------------------------- skills
SKILL_MECHANICS: dict[str, list[str]] = {
    "SMALL_GUNS": ["作为手枪、冲锋枪、步枪等武器的命中基础。命中公式在 `combat.cc` 的 `determine_to_hit_func`，尚未整理（待挖）。"],
    "BIG_GUNS": ["作为迷你机枪、火箭筒、火焰喷射器等武器的命中基础；命中公式待挖。"],
    "ENERGY_WEAPONS": ["作为激光、等离子武器的命中基础；命中公式待挖。"],
    "UNARMED": [
        "作为徒手攻击的命中基础；命中公式待挖。",
        "[[Slayer 杀手]] 要求肉搏 80%。",
    ],
    "MELEE_WEAPONS": ["作为刀、锤、矛等近战武器的命中基础；命中公式待挖。"],
    "THROWING": ["作为飞刀、手榴弹等投掷武器的命中基础。投掷最大射程 = 3 ×（力量 + 2 × [[Heave Ho! 飞刀手！]] 等级）（`item.cc`）。"],
    "FIRST_AID": [
        "对自己或他人使用。成功回复 `随机(1 + 2×医疗师等级, 5 + 5×医疗师等级)` 点生命，即无 Perk 时 1～5 点（`skill.cc` `skill_use`）。",
        "每 24 小时最多成功 3 次，第 4 次会提示“你已相当累了”等（`SKILLS_MAX_USES_PER_DAY = 3`）。",
        "每次使用耗时 30 分钟；对机器人必定失败；目标满血时不消耗次数、不给经验。",
        "成功使用获得 25 经验。",
    ],
    "DOCTOR": [
        "先逐一治疗残废部位（眼睛、左右臂、左右腿），每处单独检定；再做一次回血检定，成功回复 `随机(4 + 2×医疗师等级, 10 + 5×医疗师等级)` 点生命。",
        "与急救一样每 24 小时最多成功 3 次。耗时 1 小时，另加每个残废部位 1 小时；对机器人无效。",
        "成功使用获得 50 经验。",
    ],
    "SNEAK": [
        "默认跑步会退出潜行，[[Silent Running 衔枚疾走]] 可以边跑边潜行（`anim.cc`）。",
        "[[Ghost 神出鬼没]]：光照 ≤ 约 70% 时潜行 +20%。[[Master Thief 神偷]] +10%。",
        "潜行时从背后近战/徒手命中可触发 [[Silent Death 暗杀]]。",
    ],
    "LOCKPICK": [
        "开锁的具体难度由门、容器的对象脚本和锁的数据决定，引擎本身只负责技能检定（待挖）。",
        "受游戏难度修正；困难难度下成功会额外获得经验（经验 = 25 + |负修正|）。",
    ],
    "STEAL": [
        "成功率 = 偷窃技能 + 1 − 本次已偷件数 − 4 × 物品体积 − 25（面对面时）+ 20（目标倒地或昏迷时），上限 95%（`skill_check_stealing`）。",
        "[[Pickpocket 妙手空空]] 忽略物品体积和朝向修正。",
        "偷成功后还要过“是否被发现”检定：对方偷窃技能 − 上述修正（非生物容器按 30 − 修正）。大成功必不被发现，大失败必被发现。",
        "偷自己的队友必定成功。",
    ],
    "TRAPS": ["发现、拆除陷阱和设置炸药的具体效果都在对象脚本里；直接对空处使用时，引擎提示“你无法找到任何的陷阱”（待挖）。"],
    "SCIENCE": ["对电脑等对象使用的效果都由对象脚本决定；引擎默认提示“你无法学到任何的东西”（待挖）。"],
    "REPAIR": ["对机器、设备使用的效果都由对象脚本决定；引擎默认提示“你无法修理那个”（待挖）。"],
    "SPEECH": [
        "对话选项的智力门槛用智力判定，[[Smooth Talker 舌灿莲花]] 每级 +1 智力（仅对话）。口才检定都写在各 NPC 的对话脚本里（待挖）。",
    ],
    "BARTER": [
        "交易价值修正 = 100 + 玩家杀价 − 商人杀价 + 25（[[Master Trader 大奸商]]）+ 脚本修正，限制在 10～300（`inventry.cc` `barter_compute_value`）。",
        "已知 bug（fallout1-ce issue #48）：从对话里进入交易比点“交易”按钮价格更低。",
    ],
    "GAMBLING": ["赌场小游戏都在脚本中实现（迦克镇、哈勃城等，待挖）。"],
    "OUTDOORSMAN": [
        "随机遭遇脚本（`RNDDESRT`、`RNDDERT`、`RNDMTN`）会做野外生存检定，[[Survivalist 适者生存]] 在这些检定上每级 +20（`roll_vs_skill`）。",
        "[[Pathfinder 寻路者]]、[[Animal Friend 动物之友]]、[[Survivalist 适者生存]] 都以野外生存为前置条件。",
        "成功使用获得 100 经验。",
    ],
}


def skill_note_name(s: dict) -> str:
    return f"{s['name_en']} {s['name_zh']}"


def formula(s: dict) -> str:
    a, b, m = s["stat1"], s["stat2"], s["stat_multiplier"]
    if b:
        part = f"({a} + {b}) / 2" if m == 1 else f"({a} + {b}) × {m} / 2"
    else:
        part = a if m == 1 else f"{m} × {a}"
    return f"{s['base']}% + {part}"


def formula_zh(s: dict) -> str:
    a, b, m = STAT_ZH[s["stat1"]], s["stat2"] and STAT_ZH[s["stat2"]], s["stat_multiplier"]
    if b:
        part = f"（{a} + {b}）÷ 2"
    else:
        part = a if m == 1 else f"{m} × {a}"
    return f"{s['base']}% + {part}"


def render_skill(s: dict, perks_by_skill: dict[str, list[str]]) -> str:
    code_formula = formula(s)
    lines = [
        "---",
        "tags:",
        "  - 辐射1",
        "  - 技能",
        f"英文名: \"{s['name_en']}\"",
        f"中文名: \"{s['name_zh']}\"",
        f"编号: {s['id']}",
        f"初始值: \"{code_formula}\"",
        "---",
        "",
        f"# {skill_note_name(s)}",
        "",
        "返回：[[技能 总览]]",
        "",
        "## 游戏内说明",
        "",
        f"> {s['desc_zh']}",
        ">",
        f"> *{s['desc_en']}*",
        "",
        "## 初始值",
        "",
        f"**{formula_zh(s)}**（`{code_formula}`）",
        "",
        "之后每投 1 技能点 +1%；设为特长技能时立即 +20%，且每点 +2%。上限 200%。计算方式见 [[技能 总览]]。",
    ]
    msg_formula = s["formula_msg"].strip()
    if s["key"] == "FIRST_AID":
        lines += ["", f"> [!warning] 说明与代码不一致", "> 游戏界面写 `{msg_formula}`，但引擎代码实际按 `（感知 + 智力）÷ 2` 计算。".replace("{msg_formula}", msg_formula)]
    lines += ["", "## 机制", ""]
    lines += [f"- {t}" for t in SKILL_MECHANICS[s["key"]]]
    related = perks_by_skill.get(s["key"], [])
    if related:
        lines += ["", "## 相关 Perk", ""] + [f"- {r}" for r in related]
    lines += ["", "## 来源", "", "- 数值：fallout1-ce `src/game/skill.cc` `skill_data` / `skill_level`（对应 v1.1 引擎）。",
              "- 文本：`SKILL.MSG`（英文原版 + 本机汉化覆盖）。", ""]
    return "\n".join(lines)


def render_skill_overview(skills: list[dict]) -> str:
    rows = "\n".join(
        f"| [[{skill_note_name(s)}]] | {formula_zh(s)} | {s['use_experience'] or '—'} |" for s in skills
    )
    return f"""---
tags:
  - 辐射1
  - 技能
---

# 技能 总览

《辐射 1》共 18 项技能。本页的数字来自引擎重实现 fallout1-ce（对应 v1.1 引擎代码）和本机游戏文本；逆向过程记录在代码仓库 `fallout1resource/notes/规则挖掘/技能与Perk.md`。

另见：[[Perk 总览]]

## 技能一览

| 技能 | 初始值 | 使用成功经验 |
|---|---|---|
{rows}

## 技能值怎么算

**技能值 = 初始值 + 投入点数 + 特长加成 + 特性修正 + Perk 修正 + 难度修正**，上限 200%。

- **投入点数**：每 1 技能点固定 +1%，**不会随技能变高而变贵**。汉化界面说“等级越高所需点数越多”，与 v1.1 代码不符。
- **特长技能**（开局选 3 个，[[Tag! 增加特长技能]] 可加第 4 个）：立即 +20%，并且投入的点数再算一遍，也就是每点 +2%。
- **难度修正**：只影响非战斗技能（急救到野外生存这 12 项），简单 +20%，困难 −10%，普通 0。战斗技能不受影响。
- **特性修正**：
  - [[Gifted 天赋异禀]]：全部技能 −10%。汉化说明写 5%，英文原文和代码都是 10%。
  - [[Skilled 专家]]：全部技能 +10%。汉化说明写“每次升级多 5 点”，英文原文和代码都是开局技能 +10%，代价是每 4 级才给一个 Perk。
  - [[Good Natured 烂好人]]：6 项战斗技能 −10%；急救、医疗、口才、杀价 +15%。
- **Perk 修正**：[[Medic 医学常识]]、[[Mr. Fixit 维修大师]]、[[Speaker 发言人]] 各 +20%；[[Master Thief 神偷]] +10%；[[Ghost 神出鬼没]] 暗处潜行 +20%。

## 升级获得的技能点

每升一级获得 **5 + 2 × 智力 + 2 × [[Educated 知识份子]] 等级** 点。天赋异禀再 −5 点；未分配的点数最多攒 99。

这里的智力是基础智力：含特性影响，不含药物或装备的临时加成。所以想靠嗑曼他特临时多拿技能点是行不通的。

## 技能检定

检定用 `技能值 + 情境修正` 对比随机数，暴击率参与大成功、大失败的判定。对抗检定（如偷窃被发现）是双方各自检定后比较差值。

## 待挖

- 战斗技能的命中公式（`combat.cc`）。
- 开锁、陷阱、科技、修理、口才、赌博在各对象和对话脚本里的具体检定值。
"""


# ---------------------------------------------------------------- perks
PERK_EFFECTS: dict[str, dict] = {
    "AWARENESS": {"effect": ["查看（Examine）活着的生物时，额外显示对方的当前/最大生命值；若右手持武器，还显示武器名和剩余弹药（`protinst.cc`）。",
                             "另有 18 个角色脚本在“详细查看”时做感知检定 `do_check(玩家, 感知, 有无此 Perk)`，等于感知 +1，通过后显示该角色的额外描述文字。例如伊恩会多出一句“他非常自信，也总摆出一副那种身经百战的战士才有的轻松姿态。”"]},
    "BONUS_HTH_ATTACKS": {"effect": ["近战和徒手攻击的 AP 消耗 −1（`item.cc`）。"]},
    "BONUS_HTH_DAMAGE": {"effect": ["近战伤害属性每级 +2。"], "name_note": "汉化名“额外的空手伤害”，实际加的是近战伤害属性，徒手和持近战武器攻击都生效。"},
    "BONUS_MOVE": {"effect": ["战斗中每回合额外获得 2 × 等级 点 AP，只能用于移动（`combat.cc`）。"],
                   "name_note": "汉化名“额外的出手机会”容易误解：它不增加攻击次数，只给免费移动格数。"},
    "BONUS_RANGED_DAMAGE": {"effect": ["远程攻击**每发子弹**的伤害每级 +2，在暴击倍率、战斗难度、伤害阈值和伤害抗性之前加入（`combat.cc` `compute_damage`），所以连发武器收益更大。"],
                            "name_note": "汉化名“额外的攻击距离”是误译：它加的是伤害，不是射程。"},
    "BONUS_RATE_OF_FIRE": {"effect": ["远程武器攻击的 AP 消耗 −1（`item.cc`）。"]},
    "EARLIER_SEQUENCE": {"effect": ["战斗顺序（Sequence）每级 +2。"]},
    "FASTER_HEALING": {"effect": ["治疗速率（Healing Rate）每级 +1。"]},
    "MORE_CRITICALS": {"effect": ["暴击率每级 +5%。"]},
    "NIGHT_VISION": {"effect": ["计算玩家所见环境光时，每级加最大亮度的 10%（`light.cc`）。"]},
    "PRESENCE": {"effect": ["NPC 对你的初始反应每级 +10（`reaction.cc`）。",
                            "约 270 个角色脚本也检查此 Perk，多数是统一的反应计算，细节待挖。"]},
    "RAD_RESISTANCE": {"effect": ["辐射抗性每级 **+15%**。"], "diff": "游戏说明写每级 +10%，代码实际是 +15%。"},
    "TOUGHNESS": {"effect": ["普通伤害抗性（DR）每级 +10%，不加激光、火焰等其他伤害类型的抗性。"]},
    "STRONG_BACK": {"effect": ["负重每级 +50 磅。"]},
    "SHARPSHOOTER": {"effect": ["计算射程惩罚时，有效距离每级减 2 格（`combat.cc`）。",
                                "普通武器每点感知抵消 2 格距离，所以每级约等于感知 +1；带“长程”属性的武器每点感知抵消 4 格，每级约等于感知 +0.5。"],
                     "diff": "游戏说明写“每级感知 +2（仅用于射程）”，代码折算下来效果只有说明的一半左右。"},
    "SILENT_RUNNING": {"effect": ["潜行状态下跑步不会退出潜行（`anim.cc`）。"]},
    "SURVIVALIST": {"effect": ["**不会**提高角色面板上的野外生存数值。",
                               "只在随机遭遇脚本（`RNDDESRT`、`RNDDERT`、`RNDMTN`）的野外生存检定中每级 +20：`roll_vs_skill(玩家, 野外生存, 20 × 等级)`。"],
                    "diff": "说明写“野外生存 +20%”，实际只在随机遭遇脚本的检定里生效，面板数值不变。"},
    "MASTER_TRADER": {"effect": ["玩家作为买方时，交易价值修正 +25。这和杀价技能差值是同一刻度，最终修正限制在 10～300（`inventry.cc` `barter_compute_value`）。"],
                      "diff": "汉化说明写“七五折”，英文写 25% 折扣；代码是 +25 点交易修正，实际省多少取决于双方杀价，不是固定七五折。"},
    "EDUCATED": {"effect": ["每级在选取时立即 +2 技能点，此后每次升级额外 +2 技能点（`editor.cc`）。越早拿收益越大。"]},
    "HEALER": {"effect": ["急救回复从 `1～5` 变为 `1 + 2×等级 ～ 5 + 5×等级`；医疗回复从 `4～10` 变为 `4 + 2×等级 ～ 10 + 5×等级`（`skill.cc`）。"]},
    "FORTUNE_FINDER": {"effect": ["随机遭遇脚本（车队、哈勃城、城市、海岸、沙漠、山地等 9 个）在生成瓶盖时检查此 Perk。",
                                  "`RNDDESRT` 中一处为 `随机(7,30) × (1 + 2 × 有无此 Perk)`，即 3 倍；另一处无 Perk 时只给 1 瓶盖，有 Perk 时为 `随机(1,20) + 1`。"]},
    "BETTER_CRITICALS": {"effect": ["掷暴击效果表时 +20，让暴击更容易落在高伤害档；不影响暴击率。"]},
    "EMPATHY": {"effect": ["深入对话时显示对方对你的反应（对话选项着色）（`gdialog.cc`）。"]},
    "SLAYER": {"effect": ["玩家的近战和徒手攻击只要命中，就自动升级为暴击（`combat.cc`）。"]},
    "SNIPER": {"effect": ["玩家的远程攻击命中后，若 `1d10 ≤ 幸运` 则升级为暴击（`combat.cc`）。幸运 10 时每次命中都是暴击。"]},
    "SILENT_DEATH": {"effect": ["潜行中从背后用近战或徒手命中，且对方上一次受到的攻击不是来自你时，伤害倍率翻倍（2 → 4）（`combat.cc`）。"]},
    "ACTION_BOY": {"effect": ["最大 AP 每级 +1。"]},
    "MENTAL_BLOCK": {"effect": ["`REVULSE.INT` 是通往大师的走廊上的精神干扰。没有这个 Perk 时，每推进一段会播放一段恐怖描述，并造成 `随机(1, 玩家感知)` 点伤害，**无视护甲**（`critter_damage` 带 0x100 标志），且后面几段会在前一次的基础上累加；同行队友按各自感知同样受伤。",
                               "感知越高挨得越多，高感知角色尤其吃亏。",
                               "有这个 Perk 时整段逻辑被跳过：不掉血，也不显示那些幻觉描述。"]},
    "LIFEGIVER": {"effect": ["选取时立即 +4 最大生命值；之后每次升级，额外获得 4 × 等级 点生命（`editor.cc`、`stat.cc`）。"],
                  "diff": "说明只写“获得额外 4 点生命”，代码中还会让以后每次升级多得生命，越早拿越值。"},
    "DODGER": {"effect": ["护甲等级（AC）每级 +5。"]},
    "SNAKEATER": {"effect": ["毒抗性 +25%。"]},
    "MR_FIXIT": {"effect": ["科技、修理 +20%，只加一次（`perk_adjust_skill`）。"]},
    "MEDIC": {"effect": ["急救、医疗 +20%，只加一次。"]},
    "MASTER_THIEF": {"effect": ["潜行、开锁、偷窃、陷阱 +10%，只加一次。"]},
    "SPEAKER": {"effect": ["口才、杀价 +20%，只加一次。"]},
    "HEAVE_HO": {"effect": ["投掷最大射程 = 3 ×（力量 + 2 × 等级），仅影响射程（`item.cc`）。"],
                 "name_note": "汉化名“飞刀手！”容易误解：它不加命中和伤害，只加投掷射程。"},
    "FRIENDLY_FOE": {"effect": ["战斗中与你同队伍的角色显示为绿色轮廓，其他仍为红色（`combat.cc`）。"]},
    "PICKPOCKET": {"effect": ["偷窃时忽略物品体积（−4%/单位）和面对面（−25%）两项修正（`skill.cc`）。"]},
    "GHOST": {"effect": ["所在处光照 ≤ 45875/65536（约 70% 亮度）时潜行 +20%。"]},
    "CULT_OF_PERSONALITY": {"effect": ["计算 NPC 反应时，负声望按绝对值当作正声望计入（`reaction.cc`），好人坏人都对你有好感。",
                                       "约 270 个角色脚本同时检查此 Perk，待挖。"]},
    "SCROUNGER": {"effect": ["随机遭遇脚本（9 个）检查此 Perk；`RNDDESRT` 中已确认有 Perk 时会额外生成 .223 FMJ 弹药放进物品栏。其他遭遇的规则待挖。"]},
    "EXPLORER": {"effect": ["触发随机遭遇后判定是否改为特殊遭遇：`3d6 − 5 + 幸运 + 2 × 探险家等级 ≥ 18` 才会去抽特殊遭遇（`worldmap.cc`）。",
                            "特殊遭遇共 6 种，每种只出现一次。"]},
    "FLOWER_CHILD": {"effect": ["药物成瘾几率减半，戒断持续时间减半（`item.cc`）。"],
                     "name_note": "汉化名“高免役力”容易误解：只影响药物成瘾和戒断，不影响毒素和辐射。"},
    "PATHFINDER": {"effect": ["世界地图旅行耗时每级 −25%（`worldmap.cc`）。"]},
    "ANIMAL_FRIEND": {"effect": ["辐射蝎和变异老鼠的脚本（`RADRAT`、`RADSCORP`、`RADSCOR2`、`WANRATS`、`WANRAT2`）在“看见玩家”时判断：没有这个 Perk 才会发起攻击。",
                                "也就是说这些生物不会主动扑上来；但你先动手后它们照样反击，其他种类的怪物不受影响。"]},
    "SCOUT": {"effect": ["世界地图上揭开周围格子的范围从 3×3 扩大到 5×5（`worldmap.cc`）。"]},
    "MYSTERIOUS_STRANGER": {"effect": ["随机遭遇脚本中，若全局变量 `STRANGER_STATUS`（601）为 0，每次遭遇有 50% 几率刷出神秘陌生人。"]},
    "RANGER": {"effect": ["随机遭遇脚本开头把等级存入计数器，布置遭遇时若掷到敌对遭遇类型（脚本里的 1、2、3、4、7 号），就把遭遇类型改成 0（不发生），同时计数器减 1。",
                          "也就是每级可以取消一次敌对遭遇，计数器在每次遭遇脚本运行时重置。遭遇类型编号的具体含义待确认。"]},
    "QUICK_POCKETS": {"effect": ["战斗中打开物品栏的 AP 消耗 = 4 − 等级（`inventry.cc`）。"]},
    "SMOOTH_TALKER": {"effect": ["对话选项的智力门槛判定时，智力每级 +1（`intextra.cc`）。"]},
    "SWIFT_LEARNER": {"effect": ["获得的经验每级 +5%（`stat.cc`）。"]},
    "TAG": {"effect": ["立即再选一个特长技能：该技能立即 +20%，之后每点 +2%。"]},
    "MUTATE": {"effect": ["立即把一个特性换成另一个（`editor.cc`）。"]},
}

SPECIAL_PERK_DESC = {
    "NUKA_COLA_ADDICTION": "核子可乐成瘾，无属性变化",
    "BUFFOUT_ADDICTION": "力量 −2、耐力 −2、敏捷 −3",
    "MENTATS_ADDICTION": "智力 −3、敏捷 −2",
    "PSYCHO_ADDICTION": "智力 −2",
    "RADAWAY_ADDICTION": "辐射抗性 −20%",
    "WEAPON_LONG_RANGE": "武器属性：计算射程时每点感知抵消 4 格（普通武器 2 格）",
    "WEAPON_ACCURATE": "武器属性：命中修正（`combat.cc`，待挖）",
    "WEAPON_PENETRATE": "武器属性：穿甲，伤害阈值处理（`combat.cc`，待挖）",
    "WEAPON_KNOCKBACK": "武器属性：击退（`combat.cc`）",
    "POWERED_ARMOR": "表数据为辐射抗性 +30%、力量 +3",
    "COMBAT_ARMOR": "表数据为辐射抗性 +20%",
}


def perk_note_name(p: dict) -> str:
    return f"{p['name_en']} {p['name_zh']}"


def requirements(p: dict, skills: dict[str, dict]) -> list[str]:
    req = [f"角色等级 ≥ {p['min_level']}"]
    for k, v in p["primary_stats"].items():
        req.append(f"{STAT_ZH[k]} ≥ {v}")
    if p["required_skill"]:
        s = skills[p["required_skill"]["skill"]]
        req.append(f"[[{skill_note_name(s)}]] ≥ {p['required_skill']['level']}%")
    return req


def render_perk(p: dict, skills: dict[str, dict]) -> str:
    info = PERK_EFFECTS[p["key"]]
    req = requirements(p, skills)
    lines = [
        "---",
        "tags:",
        "  - 辐射1",
        "  - Perk",
        f"英文名: \"{p['name_en']}\"",
        f"中文名: \"{p['name_zh']}\"",
        f"编号: {p['id']}",
        f"最高等级: {p['max_rank']}",
        f"最低角色等级: {p['min_level']}",
        "---",
        "",
        f"# {perk_note_name(p)}",
        "",
        "返回：[[Perk 总览]]",
        "",
        "## 游戏内说明",
        "",
        f"> {p['desc_zh']}",
        ">",
        f"> *{p['desc_en']}*",
        "",
        "## 获得条件",
        "",
        f"- 可选 {p['max_rank']} 级",
    ] + [f"- {r}" for r in req] + ["", "## 实际效果", ""] + [f"- {t}" for t in info["effect"]]
    if info.get("diff"):
        lines += ["", "> [!warning] 与游戏说明不一致", f"> {info['diff']}"]
    if info.get("name_note"):
        lines += ["", "> [!note] 译名提示", f"> {info['name_note']}"]
    lines += ["", "## 来源", "",
              "- 条件与数值：fallout1-ce `src/game/perk.cc` `perk_data`；效果依据正文中标注的源码文件或脚本反汇编。",
              "- 文本：`PERK.MSG`（英文原版 + 本机汉化覆盖）。", ""]
    return "\n".join(lines)


def render_perk_overview(perks: list[dict], skills: dict[str, dict]) -> str:
    selectable = sorted([p for p in perks if p["selectable"]], key=lambda p: (p["min_level"], p["name_en"]))
    rows = []
    for p in selectable:
        req = "、".join(r.replace("[[", "").replace("]]", "") for r in requirements(p, skills)[1:]) or "—"
        short = PERK_EFFECTS[p["key"]]["effect"][0].replace("|", "\\|")
        flag = " ⚠️" if PERK_EFFECTS[p["key"]].get("diff") else ""
        rows.append(f"| {p['min_level']} | [[{perk_note_name(p)}]]{flag} | {p['max_rank']} | {req} | {short} |")
    special = "\n".join(
        f"| {p['name_en']} | {p['name_zh']} | {SPECIAL_PERK_DESC[p['key']]} |" for p in perks if not p["selectable"]
    )
    return f"""---
tags:
  - 辐射1
  - Perk
---

# Perk 总览

Perk 在汉化版界面里叫“特别技能”，英文 Perks。本页数据来自 fallout1-ce（对应 v1.1 引擎）和游戏脚本反汇编；逆向过程记录在代码仓库 `fallout1resource/notes/规则挖掘/技能与Perk.md`。

另见：[[技能 总览]]

## 获得规则

- 每升 **3 级**可选一个 Perk；选了 [[Skilled 专家]] 特性则改为每 **4 级**一个。
- 角色等级上限 **21**，所以正常最多 7 个，专家最多 5 个。
- 已拥有的不同 Perk 达到 7 种后不再给新的选择机会（`editor.cc` `PerkCount`）。
- 选择条件：角色等级、七项基础属性下限、部分还要求某项技能达标。属性按当前值判断，含特性和装备加成。
- 升到下一级所需总经验 = 1000 × 当前等级的三角数：2 级 1000、3 级 3000、4 级 6000……21 级 210000。

标 ⚠️ 的是实际效果和游戏说明不一致的 Perk，详情见各自页面。

## 可选 Perk（按最低等级排序）

| 等级 | Perk | 最高级 | 其他条件 | 实际效果 |
|---|---|---|---|---|
{chr(10).join(rows)}

## 实现方式分类

- **引擎直接改属性**：额外的空手伤害、先发制人、快速恢复、更多的致命一击、辐射抵抗力、强悍过人、善背、更强的致命一击、活力小子、闪躲高手、吃蛇人。
- **引擎规则里判断**：战斗（杀手、狙击手、暗杀、神射手、额外开火速度等）、交易、治疗、潜行、世界地图（探险家、寻路者、斥侯）、对话（神入、舌灿莲花）。
- **只在游戏脚本里判断**：适者生存、寻宝者、搜寻者、神秘陌生人、野外专家、动物之友、意志力。这些不会体现在面板上，只在特定遭遇或地点生效。

## 内部 Perk（不可选择）

以下条目也在 Perk 表里，用于成瘾状态和武器/护甲属性，不能通过升级选择。

| 英文 | 汉化名 | 表数据 |
|---|---|---|
{special}

## 待挖

- 搜寻者在其他 7 个遭遇脚本里的规则（沙漠遭遇已确认给 .223 FMJ）。
- 现身和八面玲珑被约 270 个脚本检查，需要反编译通用反应头文件确认。
- 野外专家涉及的遭遇类型编号具体对应哪些遭遇。
"""


# ---------------------------------------------------------------- traits
TRAIT_EFFECTS: dict[str, dict] = {
    "FAST_METABOLISM": {"effect": ["治疗速率 +2。", "辐射抗性和毒抗性的**基础值归零**，只剩装备、Perk 等额外加成（`trait_adjust_stat`）。"]},
    "BRUISER": {"effect": ["力量 +2。", "最大 AP −2。"]},
    "SMALL_FRAME": {"effect": ["敏捷 +1。", "负重 −10 × 基础力量（负重本身按力量计算，相当于每点力量少带 10 磅）。"]},
    "ONE_HANDER": {"effect": ["玩家使用单手武器命中率 +20%，双手武器命中率 −40%（`combat.cc` 命中计算）。"]},
    "FINESSE": {"effect": ["暴击率 +10%。", "玩家造成伤害时，目标伤害抗性（DR）按 +30% 计算（`compute_damage`），即每次命中伤害明显变低。"]},
    "KAMIKAZE": {"effect": ["护甲等级（AC）的基础值归零（只剩护甲提供的 AC）。", "战斗顺序 +5。"]},
    "HEAVY_HANDED": {"effect": ["近战伤害属性 +4（徒手和近战武器都生效）。", "暴击效果表掷骰 −30，暴击多落在低档效果。"]},
    "FAST_SHOT": {"effect": ["所有持武器的攻击 AP −1（`item_w_mp_cost`），包括近战武器，徒手不减。", "**完全不能瞄准部位**（`item_w_called_shot` 直接返回不可瞄准），徒手攻击也一样。"],
                  "diff": "说明只提到枪和投掷武器；代码对近战武器同样减 AP，而且不能瞄准的限制对所有攻击生效。"},
    "BLOODY_MESS": {"effect": ["玩家击杀目标时总是播放最血腥的死亡动画（`actions.cc`）。纯演出效果，不影响数值。", "`OBJ_DUDE` 脚本也检查此特性（待挖）。"]},
    "JINXED": {"effect": ["**任何人**（包括玩家和队友）的攻击判定为普通失败时，有 50% 几率改为大失败（`combat.cc`）。"]},
    "GOOD_NATURED": {"effect": ["小型枪械、大型枪械、能量型武器、肉搏、近战武器、抛掷力 −10%。", "急救、医疗、口才、杀价 +15%（`trait_adjust_skill`）。", "13 号避难所开场洞穴脚本 `V13CAVE` 检查此特性（待挖）。"]},
    "CHEM_RELIANT": {"effect": ["药物成瘾几率 ×2。", "戒断症状持续时间减半（默认 10080 分钟，即 7 天，减半为 3.5 天）（`item.cc`）。"]},
    "CHEM_RESISTANT": {"effect": ["药物成瘾几率减半。", "药效持续时间减半（`item.cc` `insert_drug_effect`）。"]},
    "NIGHT_PERSON": {"effect": ["游戏时间 **18:00–23:59** 感知、智力各 +1；**0:00–17:59** 各 −1（`trait_adjust_stat`）。"],
                     "diff": "说明写“太阳下山后提升”，但代码只把 18:00 到午夜算作夜晚，凌晨 0:00–5:59 反而按白天 −1。"},
    "SKILLED": {"effect": ["全部技能 +10%（`trait_adjust_skill`）。", "Perk 改为每 4 级一个，21 级最多 5 个。"],
                "diff": "汉化说明写“每次升级多得到五个技能点数”，英文原文和代码都是技能 +10%，升级不多给技能点。"},
    "GIFTED": {"effect": ["七项基础属性各 +1。", "全部技能 −10%。", "每次升级少 5 技能点。", "13 号避难所开场洞穴脚本 `V13CAVE` 检查此特性（待挖）。"],
               "diff": "汉化说明写技能 −5%，英文原文和代码都是 −10%。"},
}


def trait_note_name(t: dict) -> str:
    return f"{t['name_en']} {t['name_zh']}"


def render_trait(t: dict) -> str:
    info = TRAIT_EFFECTS[t["key"]]
    lines = [
        "---", "tags:", "  - 辐射1", "  - 特性",
        f"英文名: \"{t['name_en']}\"", f"中文名: \"{t['name_zh']}\"", f"编号: {t['id']}", "---", "",
        f"# {trait_note_name(t)}", "", "返回：[[特性 总览]]", "", "## 游戏内说明", "",
        f"> {t['desc_zh']}", ">", f"> *{t['desc_en']}*", "", "## 实际效果", "",
    ] + [f"- {x}" for x in info["effect"]]
    if info.get("diff"):
        lines += ["", "> [!warning] 与游戏说明不一致", f"> {info['diff']}"]
    lines += ["", "## 来源", "", "- fallout1-ce `src/game/trait.cc`（`trait_adjust_stat`、`trait_adjust_skill`）及正文标注的源码位置。",
              "- 文本：`TRAIT.MSG`（英文原版 + 本机汉化覆盖）。", ""]
    return "\n".join(lines)


def render_trait_overview(traits: list[dict]) -> str:
    rows = "\n".join(
        f"| [[{trait_note_name(t)}]]{' ⚠️' if TRAIT_EFFECTS[t['key']].get('diff') else ''} | {'；'.join(x.rstrip('。') for x in TRAIT_EFFECTS[t['key']]['effect']).replace('|', chr(92) + '|')} |"
        for t in traits
    )
    return f"""---
tags:
  - 辐射1
  - 特性
---

# 特性 总览

特性（Traits，汉化界面叫“人物特徵”）在建角色时选择，最多 2 个，有利有弊。之后只有 [[Mutate! 突变！]] 能换掉其中一个。数据来自 fallout1-ce（v1.1 引擎）；标 ⚠️ 的是与游戏说明不一致的特性。

另见：[[技能 总览]] · [[Perk 总览]]

| 特性 | 实际效果 |
|---|---|
{rows}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-dir", type=Path, required=True)
    ap.add_argument("--vault-game-root", type=Path, required=True, help="…/07 游戏/辐射1")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    skills = json.loads((args.rules_dir / "skills.json").read_text())["skills"]
    perks = json.loads((args.rules_dir / "perks.json").read_text())["perks"]
    traits = json.loads((args.rules_dir / "traits.json").read_text())["traits"]
    by_key = {s["key"]: s for s in skills}

    perks_by_skill: dict[str, list[str]] = {}
    extra = {"FIRST_AID": ["HEALER", "MEDIC"], "DOCTOR": ["HEALER", "MEDIC"], "SNEAK": ["SILENT_RUNNING", "GHOST", "MASTER_THIEF", "SILENT_DEATH"],
             "LOCKPICK": ["MASTER_THIEF"], "STEAL": ["MASTER_THIEF", "PICKPOCKET"], "TRAPS": ["MASTER_THIEF"],
             "SCIENCE": ["MR_FIXIT"], "REPAIR": ["MR_FIXIT"], "SPEECH": ["SPEAKER", "SMOOTH_TALKER"], "BARTER": ["SPEAKER", "MASTER_TRADER"],
             "OUTDOORSMAN": ["SURVIVALIST", "PATHFINDER", "ANIMAL_FRIEND"], "THROWING": ["HEAVE_HO"], "UNARMED": ["SLAYER", "BONUS_HTH_ATTACKS"],
             "MELEE_WEAPONS": ["BONUS_HTH_ATTACKS", "BONUS_HTH_DAMAGE"], "SMALL_GUNS": ["SNIPER", "BONUS_RATE_OF_FIRE", "BONUS_RANGED_DAMAGE"]}
    perk_by_key = {p["key"]: p for p in perks}
    for skill_key, keys in extra.items():
        perks_by_skill[skill_key] = [f"[[{perk_note_name(perk_by_key[k])}]]" for k in keys]

    outputs: dict[Path, str] = {}
    skill_dir, perk_dir = args.vault_game_root / "技能", args.vault_game_root / "Perk"
    outputs[skill_dir / "技能 总览.md"] = render_skill_overview(skills)
    for s in skills:
        outputs[skill_dir / f"{skill_note_name(s)}.md"] = render_skill(s, perks_by_skill)
    outputs[perk_dir / "Perk 总览.md"] = render_perk_overview(perks, by_key)
    for p in perks:
        if p["selectable"]:
            outputs[perk_dir / f"{perk_note_name(p)}.md"] = render_perk(p, by_key)

    trait_dir = args.vault_game_root / "特性"
    outputs[trait_dir / "特性 总览.md"] = render_trait_overview(traits)
    for t in traits:
        outputs[trait_dir / f"{trait_note_name(t)}.md"] = render_trait(t)

    existing = [p for p in outputs if p.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"refusing to overwrite {len(existing)} existing notes, e.g. {existing[0]}")
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"wrote {len(outputs)} notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
