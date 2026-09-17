#!/usr/bin/env python3
"""从 fallout1-ce 源码里抽取《辐射1》战斗相关的静态表，导出为 JSON。

数据来源（只读）：
  src/game/combat.cc     hit_location_penalty / crit_succ_eff / pc_crit_succ_eff / cf_table
  src/game/object_types.h  Dam 伤害结果标志枚举
  src/game/stat_defs.h     Stat 枚举（暴击的属性检定用到）
  src/game/combat_defs.h   HitLocation 枚举
  src/game/proto_types.h   KILL_TYPE 生物种类枚举

可选：--text-root 指向 workspace/output/text，会把暴击/大失败用到的
combat.msg 文本（英文 master + 中文 data 覆盖包）一起写进 JSON。

用法：
  python3 scripts/extract_combat_tables.py \
      --ce-root ~/codes/github.com/alexbatalov/fallout1-ce \
      --output workspace/output/rules/combat-tables.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

# ---------------------------------------------------------------- 中文对照表

HIT_LOCATION_ZH = {
    "HIT_LOCATION_HEAD": "头部",
    "HIT_LOCATION_LEFT_ARM": "左臂",
    "HIT_LOCATION_RIGHT_ARM": "右臂",
    "HIT_LOCATION_TORSO": "躯干",
    "HIT_LOCATION_RIGHT_LEG": "右腿",
    "HIT_LOCATION_LEFT_LEG": "左腿",
    "HIT_LOCATION_EYES": "眼睛",
    "HIT_LOCATION_GROIN": "腹股沟（裆部）",
    "HIT_LOCATION_UNCALLED": "非瞄准（普通攻击）",
}

KILL_TYPE_ZH = {
    "KILL_TYPE_MAN": "男性人类",
    "KILL_TYPE_WOMAN": "女性人类",
    "KILL_TYPE_CHILD": "儿童",
    "KILL_TYPE_SUPER_MUTANT": "超级变种人",
    "KILL_TYPE_GHOUL": "尸鬼",
    "KILL_TYPE_BRAHMIN": "双头牛",
    "KILL_TYPE_RADSCORPION": "辐射蝎",
    "KILL_TYPE_RAT": "鼠",
    "KILL_TYPE_FLOATER": "浮空怪",
    "KILL_TYPE_CENTAUR": "半人马怪",
    "KILL_TYPE_ROBOT": "机器人",
    "KILL_TYPE_DOG": "狗",
    "KILL_TYPE_MANTIS": "螳螂",
    "KILL_TYPE_DEATH_CLAW": "死亡爪",
    "KILL_TYPE_PLANT": "植物（尖叫者/蔓藤）",
}

DAM_FLAG_ZH = {
    "DAM_KNOCKED_OUT": "击晕（昏迷，若干秒后醒来）",
    "DAM_KNOCKED_DOWN": "击倒在地",
    "DAM_CRIP_LEG_LEFT": "左腿残废",
    "DAM_CRIP_LEG_RIGHT": "右腿残废",
    "DAM_CRIP_ARM_LEFT": "左臂残废",
    "DAM_CRIP_ARM_RIGHT": "右臂残废",
    "DAM_BLIND": "致盲",
    "DAM_DEAD": "立即死亡",
    "DAM_HIT": "命中",
    "DAM_CRITICAL": "暴击（大成功/大失败）",
    "DAM_ON_FIRE": "着火",
    "DAM_BYPASS": "无视护甲 DT/DR（EMP 伤害除外）",
    "DAM_EXPLODE": "武器爆炸",
    "DAM_DESTROY": "武器损毁",
    "DAM_DROP": "武器掉落",
    "DAM_LOSE_TURN": "失去下一回合",
    "DAM_HIT_SELF": "打中自己",
    "DAM_LOSE_AMMO": "弹匣内弹药全失",
    "DAM_DUD": "哑火（子弹未发射）",
    "DAM_HURT_SELF": "自伤 1d5",
    "DAM_RANDOM_HIT": "随机命中视野内另一个目标",
    "DAM_CRIP_RANDOM": "随机部位残废（四肢四选一）",
    "DAM_BACKWASH": "爆炸反噬攻击者",
    "DAM_PERFORM_REVERSE": "动画反向播放",
}

STAT_ZH = {
    "STAT_STRENGTH": "力量 ST",
    "STAT_PERCEPTION": "感知 PE",
    "STAT_ENDURANCE": "耐力 EN",
    "STAT_CHARISMA": "魅力 CH",
    "STAT_INTELLIGENCE": "智力 IN",
    "STAT_AGILITY": "敏捷 AG",
    "STAT_LUCK": "幸运 LK",
}

CRIT_FAIL_ROLL_BANDS = [
    {"max_roll": 20, "effect_index": 0},
    {"max_roll": 50, "effect_index": 1},
    {"max_roll": 75, "effect_index": 2},
    {"max_roll": 95, "effect_index": 3},
    {"max_roll": None, "effect_index": 4},
]

CRIT_SUCCESS_ROLL_BANDS = [
    {"max_roll": 20, "effect_index": 0},
    {"max_roll": 45, "effect_index": 1},
    {"max_roll": 70, "effect_index": 2},
    {"max_roll": 90, "effect_index": 3},
    {"max_roll": 100, "effect_index": 4},
    {"max_roll": None, "effect_index": 5},
]

# ---------------------------------------------------------------- 解析工具


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def enum_names(lines: list[str], first: str, stop: str) -> list[str]:
    """从 `enum {` 块里按顺序取常量名（到 stop 为止，不含 stop）。"""
    out: list[str] = []
    started = False
    for line in lines:
        name = line.strip().rstrip(",").split(" ")[0]
        if name == first:
            started = True
        if started:
            if name == stop:
                break
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                out.append(name)
    return out


def dam_flags(lines: list[str]) -> dict[str, int]:
    flags: dict[str, int] = {}
    inside = False
    for line in lines:
        if "typedef enum Dam" in line:
            inside = True
            continue
        if inside:
            if line.startswith("}"):
                break
            m = re.match(r"\s*(DAM_[A-Z_]+) = (0x[0-9A-Fa-f]+),", line)
            if m:
                flags[m.group(1)] = int(m.group(2), 16)
    return flags


def decode_flags(expr: str, flags: dict[str, int]) -> tuple[int, list[dict]]:
    """把 `DAM_A | DAM_B` 形式的表达式拆成数值和中文说明。"""
    expr = expr.strip()
    if expr == "0":
        return 0, []
    names = [t.strip() for t in expr.split("|")]
    value = 0
    detail = []
    for name in names:
        value |= flags[name]
        detail.append({"flag": name, "value": flags[name], "zh": DAM_FLAG_ZH.get(name, "")})
    return value, detail


def int_array(lines: list[str], name: str) -> tuple[list[int], int]:
    """读取 `static int name[...] = { ... };` 形式的一维数组，返回值和起始行号。"""
    for i, line in enumerate(lines):
        if re.search(r"\b%s\[" % re.escape(name), line) and "=" in line:
            body = []
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("};"):
                    break
                body.append(lines[j])
            values = [int(t) for t in re.findall(r"-?\d+", " ".join(body))]
            return values, i + 1
    raise SystemExit("找不到数组 %s" % name)


def table_bounds(lines: list[str], name: str) -> tuple[int, int]:
    start = next(i for i, line in enumerate(lines) if name + "[" in line and "=" in line)
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("};"))
    return start, end


ENTRY_RE = re.compile(r"\{\s*(-?\d+),\s*([^,]+),\s*(-?\d+|STAT_[A-Z_]+),\s*(-?\d+),\s*([^,]+),\s*(-?\d+),\s*(-?\d+)\s*\}")


def parse_crit_entry(line: str, lineno: int, flags: dict[str, int]) -> dict:
    m = ENTRY_RE.search(line)
    if not m:
        raise SystemExit("第 %d 行解析失败: %s" % (lineno, line))
    mult, flag_expr, stat, stat_mod, massive_expr, msg_id, massive_msg_id = m.groups()
    flag_value, flag_detail = decode_flags(flag_expr, flags)
    massive_value, massive_detail = decode_flags(massive_expr, flags)
    stat = stat.strip()
    entry = {
        "damage_multiplier_x2": int(mult),
        "damage_multiplier": int(mult) / 2,
        "flags": flag_detail,
        "flags_value": flag_value,
        "massive_stat": None if stat in ("-1",) else stat,
        "massive_stat_zh": STAT_ZH.get(stat),
        "massive_stat_modifier": int(stat_mod),
        "massive_flags": massive_detail,
        "massive_flags_value": massive_value,
        "message_id": int(msg_id),
        "massive_message_id": int(massive_msg_id),
        "source_line": lineno,
    }
    return entry


def parse_crit_table(lines: list[str], name: str, flags: dict[str, int],
                     kill_types: list[str], hit_locations: list[str],
                     has_kill_type: bool) -> list[dict]:
    start, end = table_bounds(lines, name)
    result: list[dict] = []
    kill_index = -1
    loc_index = -1
    effects: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current, effects
        if current is not None:
            current["effects"] = effects
            result.append(current)
        current, effects = None, []

    for i in range(start + 1, end):
        raw = lines[i]
        text = raw.strip()
        lineno = i + 1
        if text.startswith("// KILL_TYPE_"):
            flush()
            kill_index += 1
            loc_index = -1
            continue
        if text.startswith("// HIT_LOCATION_"):
            flush()
            loc_index += 1
            current = {
                "hit_location_id": loc_index,
                "hit_location": hit_locations[loc_index],
                "hit_location_zh": HIT_LOCATION_ZH[hit_locations[loc_index]],
            }
            if has_kill_type:
                current["kill_type_id"] = kill_index
                current["kill_type"] = kill_types[kill_index]
                current["kill_type_zh"] = KILL_TYPE_ZH[kill_types[kill_index]]
            continue
        if text.startswith("{ ") and text.endswith(("},", "}")):
            if current is None:  # pc_crit_succ_eff：没有部位注释，靠 `{` 分块
                loc_index += 1 if not effects else 0
                current = {
                    "hit_location_id": loc_index,
                    "hit_location": hit_locations[loc_index],
                    "hit_location_zh": HIT_LOCATION_ZH[hit_locations[loc_index]],
                }
            effects.append(parse_crit_entry(raw, lineno, flags))
            if len(effects) == 6:
                flush()
    flush()
    return result


def parse_cf_table(lines: list[str], flags: dict[str, int]) -> list[dict]:
    start, end = table_bounds(lines, "cf_table")
    rows = []
    for i in range(start + 1, end):
        text = lines[i].strip()
        if not text.startswith("{"):
            continue
        body = text[text.index("{") + 1: text.rindex("}")]
        effects = []
        for k, expr in enumerate(body.split(",")):
            value, detail = decode_flags(expr, flags)
            effects.append({
                "effect_index": k,
                "flags": detail,
                "flags_value": value,
                "roll_band": CRIT_FAIL_ROLL_BANDS[k],
            })
        rows.append({"crit_fail_table_id": len(rows), "effects": effects, "source_line": i + 1})
    return rows


def load_msg(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as fh:
        return {int(r["number"]): r["text"] for r in csv.DictReader(fh) if r["effective"] == "True"}


def attach_messages(entries: list[dict], en: dict[int, str], zh: dict[int, str]) -> None:
    for block in entries:
        for effect in block["effects"]:
            for key, target in (("message_id", "message"), ("massive_message_id", "massive_message")):
                mid = effect[key]
                if mid in en:
                    effect[target + "_en"] = en[mid]
                if mid in zh:
                    effect[target + "_zh"] = zh[mid]


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="抽取《辐射1》战斗静态表（fallout1-ce 源码）")
    ap.add_argument("--ce-root", type=Path, required=True, help="fallout1-ce 仓库根目录（只读）")
    ap.add_argument("--output", type=Path, required=True, help="输出 JSON 路径")
    ap.add_argument("--text-root", type=Path, default=None,
                    help="可选：workspace/output/text，用于补 combat.msg 英文/中文文本")
    args = ap.parse_args()

    game = args.ce_root / "src/game"
    combat = read(game / "combat.cc")
    flags = dam_flags(read(game / "object_types.h"))
    hit_locations = enum_names(read(game / "combat_defs.h"), "HIT_LOCATION_HEAD", "HIT_LOCATION_COUNT")
    kill_types = enum_names(read(game / "proto_types.h"), "KILL_TYPE_MAN", "KILL_TYPE_COUNT")

    commit = subprocess.run(["git", "-C", str(args.ce_root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()

    penalties, penalty_line = int_array(combat, "hit_location_penalty")
    hit_location_penalty = [
        {
            "hit_location_id": i,
            "hit_location": hit_locations[i],
            "hit_location_zh": HIT_LOCATION_ZH[hit_locations[i]],
            "to_hit_penalty_ranged": penalties[i],
            "to_hit_penalty_melee_unarmed": penalties[i] // 2,
            "critical_chance_bonus_when_aimed": -penalties[i],
        }
        for i in range(len(penalties))
    ]

    crit = parse_crit_table(combat, "crit_succ_eff", flags, kill_types, hit_locations, True)
    pc_crit = parse_crit_table(combat, "pc_crit_succ_eff", flags, kill_types, hit_locations, False)
    cf = parse_cf_table(combat, flags)

    if args.text_root:
        en = load_msg(args.text_root / "master/TEXT/ENGLISH/GAME/COMBAT.csv")
        zh = load_msg(args.text_root / "data/TEXT/ENGLISH/GAME/COMBAT.csv")
        attach_messages(crit, en, zh)
        attach_messages(pc_crit, en, zh)

    data = {
        "_schema": {
            "source": "fallout1-ce（《辐射1》引擎重实现，对应原版 v1.1）源码静态表，只读抽取",
            "ce_commit": commit,
            "generator": "scripts/extract_combat_tables.py",
            "字段说明": {
                "hit_location_penalty": "瞄准部位的命中惩罚。to_hit_penalty_ranged=远程/投掷武器直接加这个负值；"
                                        "to_hit_penalty_melee_unarmed=近战与徒手取一半（C 整数除法，向零取整）；"
                                        "critical_chance_bonus_when_aimed=单发攻击时暴击率的额外加成"
                                        "（determine_to_hit_func / compute_attack 里用 -penalty）",
                "crit_succ_eff": "暴击效果表：按【生物种类 × 命中部位 × 暴击档位(0-5)】索引，"
                                 "用于防御方不是玩家时（combat.cc attack_crit_success）",
                "pc_crit_succ_eff": "玩家被暴击时使用的另一张表，只按【命中部位 × 档位】索引",
                "damage_multiplier_x2": "源码里的原始值，实际倍率 = 该值 / 2（compute_damage 中先乘后除 2）",
                "damage_multiplier": "换算后的伤害倍率",
                "flags": "该档位必定附加的效果标志（DAM_*）",
                "massive_stat": "若不为 null，防御方要做一次 d10 属性检定（stat_result）；"
                                "掷 1d10 > 属性值 + massive_stat_modifier 即检定失败，追加 massive_flags 效果",
                "massive_stat_modifier": "检定时加到防御方属性上的修正（负值=更难抵抗）",
                "message_id": "combat.msg 的消息编号（普通效果）",
                "massive_message_id": "combat.msg 的消息编号（追加效果触发时）",
                "crit_success_roll_bands": "掷 1d100 + STAT_BETTER_CRITICALS 后落入的档位区间",
                "cf_table": "大失败效果表：按【武器 criticalFailureType(0-6) × 效果档位(0-4)】索引；"
                            "档位由 1d100 - 5×(幸运-5) 决定（见 crit_fail_roll_bands）",
                "roll_band": "该档位对应的掷骰区间上限（max_roll 为 null 表示更高都算这一档）",
                "source_line": "在 fallout1-ce 源文件中的行号",
            },
            "sources": {
                "hit_location_penalty": "src/game/combat.cc:%d" % penalty_line,
                "crit_succ_eff": "src/game/combat.cc:%d" % (table_bounds(combat, "crit_succ_eff")[0] + 1),
                "pc_crit_succ_eff": "src/game/combat.cc:%d" % (table_bounds(combat, "pc_crit_succ_eff")[0] + 1),
                "cf_table": "src/game/combat.cc:%d" % (table_bounds(combat, "cf_table")[0] + 1),
                "dam_flags": "src/game/object_types.h（typedef enum Dam）",
                "roll_logic": "src/game/combat.cc attack_crit_success / attack_crit_failure，src/game/roll.cc roll_check",
            },
        },
        "dam_flags": [
            {"flag": name, "value": value, "zh": DAM_FLAG_ZH.get(name, "")}
            for name, value in flags.items()
        ],
        "hit_location_penalty": hit_location_penalty,
        "crit_success_roll_bands": CRIT_SUCCESS_ROLL_BANDS,
        "crit_fail_roll_bands": CRIT_FAIL_ROLL_BANDS,
        "crit_succ_eff": crit,
        "pc_crit_succ_eff": pc_crit,
        "cf_table": cf,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("写出 %s：暴击表 %d 组 / 玩家暴击表 %d 组 / 大失败表 %d 行" %
          (args.output, len(crit), len(pc_crit), len(cf)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
