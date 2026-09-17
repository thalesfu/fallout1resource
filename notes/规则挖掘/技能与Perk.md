# 技能与 Perk 规则挖掘

日期：2026-09-17

攻略产出：Vault `07 游戏/辐射1/技能/`（18 篇 + 总览）和 `07 游戏/辐射1/Perk/`（53 篇可选 Perk + 总览）。

## 数据来源

| 内容 | 来源 | 证据等级 |
|---|---|---|
| 技能初始值、属性系数、使用经验 | fallout1-ce `src/game/skill.cc` `skill_data`（commit `0609bcfd0e`） | 工具推断：CE 基于 fallout1-re，对应 v1.1 引擎；本机是 Steam 版，版本差异未核 |
| Perk 等级、前置条件、属性加成 | fallout1-ce `src/game/perk.cc` `perk_data` | 同上 |
| Perk 实际效果 | 在 CE 全源码中 grep `PERK_*` 的每处使用，逐个阅读 | 同上 |
| 仅由脚本处理的 Perk | 本仓库 INT 反汇编中的 `has_trait(0, dude_obj, id)` 调用 | 已验证（本机资源） |
| 中英文名称和说明 | `workspace/output/text/{master,data}/TEXT/ENGLISH/GAME/{SKILL,PERK,TRAIT}.csv` 中 `effective=True` 的条目 | 已验证 |

CE 源码克隆在 `~/codes/github.com/alexbatalov/fallout1-ce`，只读参考，不进本仓库。

## 可复现命令

```bash
python3 scripts/extract_skill_perk_rules.py \
  --ce-root ~/codes/github.com/alexbatalov/fallout1-ce \
  --text-root workspace/output/text \
  --output-dir workspace/output/rules

python3 scripts/scan_has_trait.py \
  --scripts-root workspace/output/scripts \
  --output workspace/output/rules/has-trait-calls.csv

python3 scripts/generate_skill_perk_docs.py \
  --rules-dir workspace/output/rules \
  --vault-game-root "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Thales/07 游戏/辐射1" \
  --overwrite
```

生成器里的机制文字是人工核对后写死在 `PERK_EFFECTS` / `SKILL_MECHANICS` 中的。改结论时先改这里再重新生成，不要直接改 Vault。

## 关键结论

### 技能

- 技能值 = 初始值 + 属性加成 + 投入点数 × 1 + [特长：20 + 投入点数] + 特性 + Perk + 难度，上限 200（`skill_level`）。
- **加点每点固定 1 技能点**（`skill_inc_point`），v1.1 没有 F2 那种高技能加点变贵的机制。汉化 `EDITOR.MSG` 131 的说法不准。
- 双属性技能按 `(s1 + s2) × 系数 / 2` 计算。急救在 `SKILL.MSG` 306 写 `+ (PE + IN)`，与代码不符。
- 难度只影响非战斗技能：简单 +20，困难 −10（`skill_game_difficulty`）。
- 特性：Gifted −10、Skilled +10、Good Natured 战斗 −10 / 急救医疗口才杀价 +15（`trait_adjust_skill`）。汉化 `TRAIT.MSG` 214/215 把 Skilled 译成“每级多 5 点”、Gifted 译成“−5%”，英文原文与代码一致，是汉化错误。
- 升级技能点 = 5 + 2 × 基础智力（含特性，不含 bonus）+ 2 × Educated；Gifted −5；未用点数上限 99（`editor.cc` `UpdateLevel`）。
- 升级 HP = 基础耐力 / 2 + 2 + 4 × Lifegiver（`stat_pc_add_experience`）。
- 每 3 级一个 Perk（Skilled 为 4 级）；已有不同 Perk ≥ 7 种时不再给（`PerkCount`）。
- 急救、医疗每 24 小时各 3 次成功（`SKILLS_MAX_USES_PER_DAY`）；回复量见 Vault 笔记。
- 偷窃公式见 `skill_check_stealing`，已整理进 Vault。

### 说明与代码不一致的 Perk

- Rad Resistance：说明 +10%/级，代码 +15。
- Sharpshooter：说明感知 +2/级，代码是有效距离 −2 格/级，折合普通武器感知 +1。
- Survivalist：不改面板值，只在 `RNDDESRT`/`RNDDERT`/`RNDMTN` 中 `roll_vs_skill(dude, 17, 20 × rank)`。
- Master Trader：是交易修正 +25，不是固定折扣。
- Lifegiver：选取时 +4，之后每次升级额外 +4 × rank。

### 汉化名误导

Bonus Move“额外的出手机会”、Bonus Ranged Damage“额外的攻击距离”、Heave Ho!“飞刀手！”、Flower Child“高免役力”。

### 脚本端 Perk（has_trait 扫描）

脚本扫描共发现 949 次 `has_trait` 调用。类型 0 是 Perk，1 是对象标志，2 是特性。其中 Perk 相关的 id 分布如下：

| id | Perk | 脚本数 | 已读懂的用法 |
|---|---|---|---|
| 0 | Awareness | 18 | 待挖 |
| 10 | Presence | 270 | 疑似通用反应头文件，待反编译确认 |
| 16 | Survivalist | 4 | `roll_vs_skill(dude, OUTDOORSMAN, 20 × has_trait)` |
| 20 | Fortune Finder | 9 | `RNDDESRT`：`item_caps_adjust(obj, random(7,30) × (2 × has + 1))`；另一处 `random(1,20) × has + 1` |
| 27 | Mental Block | 1 | `REVULSE`，待挖 |
| 39 | Cult of Personality | 270 | 同 Presence |
| 40 | Scrounger | 8 | `RNDDESRT`：有 Perk 时 `create_object_sid(34)` 即 .223 FMJ，并 `add_obj_to_inven` |
| 44 | Animal Friend | 5 | 鼠、辐射蝎脚本，待挖 |
| 46 | Mysterious Stranger | 8 | `has && STRANGER_STATUS(601) == 0 && random(0,1)` 时刷出 |
| 47 | Ranger | 6 | 结果存入脚本变量 11，后续用法待挖 |

操作码对照（CE `intextra.cc`）：`0x80AC roll_vs_skill`、`0x80B7 create_object_sid`、`0x80D8 add_obj_to_inven`、`0x80F3 has_trait`、`0x810B metarule`。

## 踩坑

- Perk 表的 `stat` 字段是 `Stat` 枚举序号（0 起），不是 MSG 编号。7 = MAX_HP，8 = MAX_AP，11 = MELEE_DAMAGE，24 = 普通 DR，31 = 辐射抗性，32 = 毒抗性。
- 对 `max_rank == -1` 的内部 Perk（成瘾、护甲），`required_stat_levels` 表示直接施加的属性变化，而不是前置条件。
- 反汇编里 `store_global` / `fetch_global` 操作的是**脚本自己的变量**，不是游戏 GVAR；游戏 GVAR 用 `global_var` / `set_global_var`，名字查 `raw/master/DATA/VAULT13.GAM`。
- `raw/master/MAPS/VAULT13.GAM` 是地图变量，不是全局变量表。
- int2ssl 反编译器已克隆到 `~/codes/github.com/falltergeist/int2ssl`，但编译第三方代码的操作被权限拦截，尚未构建。这台机器上 `/usr/local/bin/cmake` 是 x86 版本，无法运行。

## 待挖

- 战斗命中公式（`determine_to_hit_func`）和暴击表（`crit_succ_eff`），以便补全 6 项战斗技能笔记。
- 反编译通用反应头文件，确认 Presence 和 Cult of Personality 在脚本里的作用。
- Awareness、Animal Friend、Ranger、Mental Block 的脚本端行为。
- 特性（Traits）目录：数据已在 `trait.cc` / `TRAIT.MSG`，可以按同样方式生成。
- 核对 Steam 版 falloutw.exe 与 v1.1 CE 的数值是否一致（如对照 exe 中 `skill_data` 表的字节）。
