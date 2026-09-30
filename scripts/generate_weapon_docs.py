#!/usr/bin/env python3
"""Generate Obsidian notes for Fallout 1 weapons and ammunition.

Input: workspace/output/items/catalog.json (build_item_catalog.py).

Writes an overview of all weapons, an ammunition/caliber reference, and one page per weapon or
ammunition type that the vault does not already cover (matched by `prototype_id` front matter).
Existing notes are left untouched unless --overwrite is given.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

DAMAGE_ZH = {"normal": "普通", "laser": "激光", "fire": "火焰", "plasma": "等离子",
             "electrical": "电击", "emp": "电磁脉冲", "explosion": "爆炸"}
SKILL_ZH = {"small_guns": "小型枪械", "big_guns": "大型枪械", "energy": "能量型武器",
            "unarmed": "肉搏", "melee": "近战武器", "throwing": "抛掷力", "none": "—"}
BIG_GUN_FLAG, TWO_HAND_FLAG = 0x0100, 0x0200
WEAPON_PERK = {-1: "无", 58: "长程（计算射程惩罚时每点感知抵消 4 格，普通武器只抵消 2 格）",
               59: "精准（命中 +20%）", 60: "穿透（无视目标的伤害阈值）", 61: "击退（击退距离加倍）"}


GENERATED_MARK = "<!-- generated: scripts/generate_weapon_docs.py -->"


LINKS: dict[int, str] = {}


def link(item: dict) -> str:
    """Wiki link target: an existing vault note keeps its own file name."""
    return LINKS.get(item["prototype_id"], name(item))


def skill_of(item: dict) -> str:
    """Mirrors item_w_skill: melee/unarmed/throwing by attack mode, then laser/plasma/electrical
    damage means energy weapons, otherwise the BigGun flag means big guns."""
    mode = item["weapon"]["attack_primary"]
    if mode in ("拳击", "踢击"):
        return "unarmed"
    if mode in ("挥击", "突刺"):
        return "melee"
    if mode == "投掷":
        return "throwing"
    if mode == "无":
        return "none"
    if item["weapon"]["damage_type"] in ("laser", "plasma", "electrical"):
        return "energy"
    if item["extended_flags"] & BIG_GUN_FLAG:
        return "big_guns"
    return "small_guns"


def ammo_for(item: dict, ammo_by_caliber: dict[int, list[dict]]) -> list[dict]:
    if not item["weapon"]["ammo_capacity"]:
        return []
    return ammo_by_caliber.get(item["weapon"]["caliber"], [])


def name(item: dict) -> str:
    """Display name; some prototypes have identical English and Chinese names (5mm AP…)."""
    en, zh = (item["name_en"] or "").strip(), (item["name_zh"] or "").strip()
    return en if en == zh or not zh else f"{en} {zh}".strip()


def damage_text(w: dict) -> str:
    return f'{w["min_damage"]}–{w["max_damage"]}'


def weapon_row(item: dict, ammo_by_caliber) -> str:
    w = item["weapon"]
    ammo = "、".join(link(a) for a in ammo_for(item, ammo_by_caliber)) or "—"
    burst = f'{w["rounds"]} 发' if w["rounds"] > 1 else "—"
    secondary = "—" if w["attack_secondary"] == "无" else f'{w["attack_secondary"]}／{w["ap_secondary"]} AP／{w["range_secondary"]} 格'
    return (f'| [[{link(item)}]] | {damage_text(w)} | {DAMAGE_ZH.get(w["damage_type"], w["damage_type"])} | '
            f'{w["attack_primary"]}／{w["ap_primary"]} AP／{w["range_primary"]} 格 | {secondary} | {burst} | '
            f'{w["ammo_capacity"] or "—"} | {ammo} | {w["min_strength"]} | {"双手" if w["two_handed"] else "单手"} | {item["cost"]} |')


def overview(weapons: list[dict], ammo_by_caliber) -> str:
    groups = defaultdict(list)
    for item in weapons:
        groups[skill_of(item)].append(item)
    blocks = []
    for key in ("small_guns", "big_guns", "energy", "melee", "unarmed", "throwing", "none"):
        rows = sorted(groups.get(key, []), key=lambda i: (-i["weapon"]["max_damage"], i["prototype_id"]))
        if not rows:
            continue
        blocks.append(f"### {SKILL_ZH[key]}\n\n"
                      "| 武器 | 伤害 | 伤害类型 | 主攻击 | 次攻击 | 连发 | 弹匣 | 可用弹药 | 力量 | 持握 | 价值 |\n"
                      "|---|---|---|---|---|---|---|---|---|---|---|\n"
                      + "\n".join(weapon_row(i, ammo_by_caliber) for i in rows))
    return f"""---
tags:
  - 辐射1
  - 物品
  - 武器
---

# 武器 总览

《辐射 1》共 {len(weapons)} 件武器原型（含拳套、手雷、信号弹等）。数值直接取自游戏的物品原型文件，伤害与射程都由**武器自身**决定。

另见：[[弹药与口径对照]] · [[战斗公式]] · [[技能 总览]]

> [!important] 换子弹不会改变伤害和射程
> 《辐射 1》的引擎**根本不读取弹药的护甲修正和伤害倍率**，这些字段只在《辐射 2》里才生效。同口径的不同子弹（比如 10mm JHP 和 10mm AP）在本作中打出来的效果完全一样，伤害类型也由武器决定。详见 [[弹药与口径对照]]。

## 读表说明

- **主攻击／次攻击**：格式为「模式／行动点／射程」。瞄准部位额外 +1 AP。
- **连发**：一次攻击消耗的子弹数，只有连发和连续射击武器才有；连发不吃瞄准的暴击加成，而且会沿弹道误伤。
- **可用弹药**：同口径的弹药可以混用，见 [[弹药与口径对照]]。
- **力量**：低于该值时每差 1 点命中 −20%。
- **持握**：双手武器在选了 [[One Hander 单枪客]] 特性时命中 −40%，单手 +20%。

{(chr(10) * 2).join(blocks)}
"""


def ammo_page(ammo: list[dict], weapons: list[dict]) -> str:
    by_caliber = defaultdict(list)
    for a in ammo:
        by_caliber[a["ammo"]["caliber"]].append(a)
    guns = defaultdict(list)
    for w in weapons:
        if w["weapon"]["ammo_capacity"]:
            guns[w["weapon"]["caliber"]].append(w)
    blocks = []
    for caliber in sorted(by_caliber):
        rows = "\n".join(
            f'| [[{link(a)}]] | {a["ammo"]["quantity"]} | {a["ammo"]["ac_modifier"]:+d} | '
            f'{a["ammo"]["dr_modifier"]:+d} | ×{a["ammo"]["damage_multiplier"]}／÷{a["ammo"]["damage_divisor"]} | {a["cost"]} |'
            for a in by_caliber[caliber])
        users = "、".join(f"[[{link(w)}]]" for w in guns.get(caliber, [])) or "（本作没有武器使用）"
        blocks.append(f"### 口径 {caliber}\n\n使用的武器：{users}\n\n"
                      "| 弹药 | 每包数量 | 护甲等级修正 | 伤害抗性修正 | 伤害倍率 | 价值 |\n"
                      "|---|---|---|---|---|---|\n" + rows + "\n")
    multi = [c for c in by_caliber if len(by_caliber[c]) > 1]
    multi_text = "\n".join(
        f'- **口径 {c}**：' + "、".join(f'{a["name_zh"]}' for a in by_caliber[c]) +
        f'（{"、".join(w["name_zh"] for w in guns.get(c, [])) or "无武器使用"}）'
        for c in sorted(multi))
    return f"""---
tags:
  - 辐射1
  - 物品
  - 弹药
---

# 弹药与口径对照

武器能用哪种子弹，只看**口径**：口径相同就能互换。本作共 {len(ammo)} 种弹药、{len(by_caliber)} 种口径。

另见：[[武器 总览]] · [[战斗公式]]

## 一枪多弹的情况

有 {len(multi)} 种口径存在多于一种子弹：

{multi_text}

> [!important] 在《辐射 1》里换子弹没有任何数值差别
> 表中的「护甲等级修正」「伤害抗性修正」「伤害倍率」三列是原型文件里的字段，但 **fallout1-ce 源码显示引擎从不读取它们**：这四个字段只出现在读写 `.pro` 文件的代码里，命中计算 `determine_to_hit_func` 和伤害计算 `compute_damage` 完全没有引用。
>
> 也就是说：
>
> - 10mm JHP 和 10mm AP 打在同一个目标上，伤害与命中**完全相同**；
> - 伤害类型由武器决定，不是由子弹决定（激光枪打激光伤害，因为枪是激光武器）；
> - 射程同样只看武器。
>
> 这些字段要到《辐射 2》才真正生效。所以本作里选子弹只需要考虑**哪种便宜、哪种好买**。

## 按口径分组

{(chr(10) * 2).join(blocks)}
"""


def placement_rows(item: dict) -> str:
    kind_zh = {"critter": "人物携带", "container": "位于容器内", "ground": "位于地面", "scenery": "位于场景对象内"}
    rows = []
    for p in sorted(item["placements"], key=lambda p: (p["location"] or "", p["region"] or "", p["object_id"])):
        holder = (p["holder"] or {}).get("name") or ("地面" if p["holder_kind"] == "ground" else "—")
        holder_id = (p["holder"] or {}).get("object_id")
        holder_text = f'{holder}（ID {holder_id}）' if holder_id else holder
        rows.append(f'| {p["location"] or p["map"]} | {p["region"] or "—"} | {holder_text} | {p["object_id"]} | '
                    f'{p["quantity"]} | {kind_zh.get(p["holder_kind"], "—")}。 |')
    return "\n".join(rows)


def weapon_page(item: dict, ammo_by_caliber) -> str:
    w = item["weapon"]
    ammo = ammo_for(item, ammo_by_caliber)
    ammo_rows = "\n".join(
        f'| [[{link(a)}]] | {a["ammo"]["quantity"]} | {a["cost"]} 瓶盖 |' for a in ammo) or "| —  | — | — |"
    secondary = "无" if w["attack_secondary"] == "无" else f'{w["attack_secondary"]}（{w["ap_secondary"]} AP，{w["range_secondary"]} 格）'
    return f"""---
title: "{name(item)}"
aliases:
  - "{item["name_en"]}"
  - "{item["name_zh"]}"
tags:
  - "辐射1/物品/武器"
prototype_id: {item["prototype_id"]}
---

# 名称和描述

| 语言 | 名称 | 描述 |
| --- | --- | --- |
| 英文 | {item["name_en"]} | {item["desc_en"] or "—"} |
| 中文 | {item["name_zh"]} | {item["desc_zh"] or "—"} |

# 游戏数据

| 项目 | 数据 |
| --- | --- |
| 物品原型 ID | {item["prototype_id"]}（`0x{item["pid"] & 0xFFFFFFFF:08X}`） |
| 类型 | 武器 |
| 使用技能 | {SKILL_ZH[skill_of(item)]} |
| 持握方式 | {"双手" if w["two_handed"] else "单手"} |
| 基础伤害 | {damage_text(w)} |
| 伤害类型 | {DAMAGE_ZH.get(w["damage_type"], w["damage_type"])} |
| 主要攻击 | {w["attack_primary"]}（{w["ap_primary"]} AP，{w["range_primary"]} 格） |
| 次要攻击 | {secondary} |
| 每次攻击弹数 | {w["rounds"]} |
| 弹匣容量 | {w["ammo_capacity"] or "—"} |
| 口径 | {w["caliber"] if w["ammo_capacity"] else "—"} |
| 最低力量 | {w["min_strength"]} |
| 武器特性 | {WEAPON_PERK.get(w["perk"], w["perk"])} |
| 武器动画 | {w["animation_zh"]} |
| 重量 | {item["weight"]} |
| 体积 | {item["size"]} |
| 基础价值 | {item["cost"]} 瓶盖 |
| 严重失败表 ID | {w["critical_failure_type"]} |

近战与徒手类武器的伤害还会加上角色的近战伤害属性；投掷武器不加。详见 [[战斗公式]]。

# 可用弹药

同口径的弹药可以互换，且在本作中**没有任何数值差异**，详见 [[弹药与口径对照]]。

| 弹药 | 每包数量 | 价值 |
| --- | --- | --- |
{ammo_rows}

# 出现位置

静态地图资料中共有 {len(item["placements"])} 个{item["name_zh"]}对象，初始数量合计 {item["total_quantity"]}。人物所携物品能否取得，取决于该人物是否开放交易、能否被偷窃，或被击败后能否搜取；容器和地面对象是否能够取得，则取决于玩家能否抵达并操作对应对象。

| 地点 | 区域 | 持有者或容器 | 物品对象 ID | 数量 | 说明 |
| --- | --- | --- | ---: | ---: | --- |
{placement_rows(item) or "| — | — | — | — | — | 静态地图中没有该物品，由脚本或商人库存生成。 |"}

{GENERATED_MARK}
"""


def ammo_item_page(item: dict, weapons: list[dict]) -> str:
    a = item["ammo"]
    users = "、".join(f'[[{link(w)}]]' for w in weapons if w["weapon"]["ammo_capacity"] and w["weapon"]["caliber"] == a["caliber"]) or "本作没有武器使用"
    return f"""---
title: "{name(item)}"
aliases:
  - "{item["name_en"]}"
  - "{item["name_zh"]}"
tags:
  - "辐射1/物品/弹药"
prototype_id: {item["prototype_id"]}
---

# 名称和描述

| 语言 | 名称 | 描述 |
| --- | --- | --- |
| 英文 | {item["name_en"]} | {item["desc_en"] or "—"} |
| 中文 | {item["name_zh"]} | {item["desc_zh"] or "—"} |

# 游戏数据

| 项目 | 数据 |
| --- | --- |
| 物品原型 ID | {item["prototype_id"]}（`0x{item["pid"] & 0xFFFFFFFF:08X}`） |
| 类型 | 弹药 |
| 口径 | {a["caliber"]} |
| 每包数量 | {a["quantity"]} |
| 护甲等级修正 | {a["ac_modifier"]:+d}（本作不生效） |
| 伤害抗性修正 | {a["dr_modifier"]:+d}（本作不生效） |
| 伤害倍率 | ×{a["damage_multiplier"]}／÷{a["damage_divisor"]}（本作不生效） |
| 重量 | {item["weight"]} |
| 基础价值 | {item["cost"]} 瓶盖 |

> [!note] 三项修正在《辐射 1》中不生效
> 引擎从不读取弹药的这三项字段，同口径子弹的实战效果完全一致，详见 [[弹药与口径对照]]。

# 使用该弹药的武器

{users}

# 出现位置

静态地图资料中共有 {len(item["placements"])} 个{item["name_zh"]}对象，初始数量合计 {item["total_quantity"]}。

| 地点 | 区域 | 持有者或容器 | 物品对象 ID | 数量 | 说明 |
| --- | --- | --- | ---: | ---: | --- |
{placement_rows(item) or "| — | — | — | — | — | 静态地图中没有该物品，由脚本或商人库存生成。 |"}

{GENERATED_MARK}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--vault-game-root", type=Path, required=True)
    ap.add_argument("--overwrite-handwritten", action="store_true",
                    help="also rewrite notes without the generated marker (hand-written pages)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    catalog = json.loads(args.catalog.read_text())["items"]
    weapons = [i for i in catalog if i["type"] == "weapon"]
    ammo = [i for i in catalog if i["type"] == "ammo"]
    ammo_by_caliber = defaultdict(list)
    for a in ammo:
        ammo_by_caliber[a["ammo"]["caliber"]].append(a)

    existing: dict[int, Path] = {}
    generated: set[int] = set()
    for path in (args.vault_game_root / "物品").rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^prototype_id:\s*(\d+)\s*$", text[:600], re.M)
        if m:
            existing[int(m.group(1))] = path
            if GENERATED_MARK in text:
                generated.add(int(m.group(1)))

    LINKS.update({pid: path.stem for pid, path in existing.items()})
    weapon_dir = args.vault_game_root / "物品/Weapon 武器"
    ammo_dir = args.vault_game_root / "物品/Ammo 弹药"
    out: dict[Path, str] = {
        weapon_dir / "武器 总览.md": overview(weapons, ammo_by_caliber),
        ammo_dir / "弹药与口径对照.md": ammo_page(ammo, weapons),
    }
    taken = {p.stem for p in existing.values()}

    def note_name(item: dict) -> str:
        """Two prototypes can share a display name (e.g. both Flare entries); keep them apart.
        A note that already belongs to this prototype is not a collision."""
        base = name(item)
        own = existing.get(item["prototype_id"])
        if base not in taken or (own and own.stem == base):
            return base
        return f'{base}（原型 {item["prototype_id"]}）'

    created = []
    for item in weapons:
        if item["prototype_id"] in existing and item["prototype_id"] not in generated and not args.overwrite_handwritten:
            continue
        LINKS[item["prototype_id"]] = note_name(item)
        created.append(note_name(item))
    for item in ammo:
        if item["prototype_id"] in existing and item["prototype_id"] not in generated and not args.overwrite_handwritten:
            continue
        LINKS[item["prototype_id"]] = note_name(item)
        created.append(note_name(item))

    for item in weapons:
        if item["prototype_id"] in existing and item["prototype_id"] not in generated and not args.overwrite_handwritten:
            continue
        out[weapon_dir / f"{LINKS[item['prototype_id']]}.md"] = weapon_page(item, ammo_by_caliber)
    for item in ammo:
        if item["prototype_id"] in existing and item["prototype_id"] not in generated and not args.overwrite_handwritten:
            continue
        out[ammo_dir / f"{LINKS[item['prototype_id']]}.md"] = ammo_item_page(item, weapons)
    out[weapon_dir / "武器 总览.md"] = overview(weapons, ammo_by_caliber)
    out[ammo_dir / "弹药与口径对照.md"] = ammo_page(ammo, weapons)

    print(f"总览 2 篇；新建 {len(created)} 篇：{'、'.join(created)}")
    if not args.apply:
        return 0
    for path, text in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
