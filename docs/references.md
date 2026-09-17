# 外部参考清单

2026-09-17 调研。"已验证"=实际打开过仓库/源码；"未打开"=仅搜索摘要。

## 引擎重实现（规则公式首选来源）

- **fallout1-ce** <https://github.com/alexbatalov/fallout1-ce>（Sustainable Use License，可读可本地用）— 已验证。基于 fallout1-re，对应 **v1.1**（1997.11），README 把升级到 1.2 列为 TODO。规则在 `src/game/`：`combat.cc`（`determine_to_hit_func`、`compute_damage`、暴击表 `crit_succ_eff`、`hit_location_penalty`）、`combatai.cc`、`skill.cc`、`perk.cc`、`trait.cc`、`stat.cc`、`critter.cc`、`party.cc`、`reaction.cc`、`roll.cc`、`queue.cc`、`worldmap.cc`、`endgame.cc`、`loadsave.cc`、`lip_sync.cc`、`fontmgr.cc`、`int/intrpret.cc`。
  - F1 与 F2 差异（源码确认）：伤害不读弹药 DR 修正/倍率；随机/特殊遭遇硬编码在 `worldmap.cc`（无 worldmap.txt）；结局硬编码在 `endgame.cc`，按 GVAR 选幻灯片；存档 27 个处理段，队列在第 15 段。
- **fallout1-re** <https://github.com/alexbatalov/fallout1-re> — 已验证，无 SPDX 许可证。更贴近原版行为，与 CE 对照。
- fallout2-ce <https://github.com/alexbatalov/fallout2-ce> — F2，对比用。
- OpenVault <https://github.com/V4nnura/OpenVault> — F1 C++ 重写，成熟度不明。

## 脚本反编译与脚本源码

- **int2ssl** <https://github.com/falltergeist/int2ssl>（GPL-3.0，F1/F2）；sfall 分支 <https://github.com/sfall-team/int2ssl>。INT→SSL 反编译。
- **fixtsrc**（Fallout Fixt）<https://github.com/Sduibek/fixtsrc> — 已验证，无许可证。`SCRIPTS/` 约 1036 个整理过的反编译 SSL；`Excel/` 含随机遭遇概率表与遭遇地图。**Fixt 改了大量数值，不能当原版数据。**
- **Fo1in2** <https://github.com/rotators/Fo1in2> — 已验证，活跃。`Mapper/source/scripts/` ~1096 个 ssl + `headers/`；`mods/fo1_base/data/` 有转成 F2 格式的 `WORLDMAP.TXT`、`party.txt`、`endgame.txt`。已按 F2 引擎改写，只作交叉核对。

## 格式文档

- **fodev / rotators fallout2-docs** <https://fodev.net/files/fo2/>、<https://github.com/rotators/fallout2-docs> — 已验证。aaf/acm/dat/fon/frm/gam/int/lip/lst/map/msg/pro/savegame/sve/ssl/endings/worldmap；存档页注明 F1 差异（头 0x7563 字节、版本 `1.1R`）。
- Vault-Tec Labs：<https://falloutmods.fandom.com/wiki/SAVE.DAT_File_Format>、<https://falloutmods.fandom.com/wiki/Fallout_engine_calculations> — 未打开。

## 其他实现（格式解析对照）

- Falltergeist <https://github.com/falltergeist/falltergeist>（GPL-3.0，F2）
- DarkFO <https://github.com/darkf/darkfo>（Apache-2.0，已归档）
- klamath <https://github.com/adamkewley/klamath>（F1/2 资源工具，已归档）

## 数据 / 攻略维基（未打开，需要时再核）

- Nukapedia：<https://fallout.fandom.com/wiki/Fallout_random_encounters>、<https://fallout.fandom.com/wiki/Fallout_combat>
- fallout.wiki：<https://fallout.wiki/wiki/Fallout_and_Fallout_2_combat>、<https://fallout.wiki/wiki/Fallout_patches>（抓取被 403）
- 时间限制分析：<https://lilura1.blogspot.com/2021/02/Fallout-1-Retrospective-Review-Time-based-Reactivity.html>
- NMA：F1 参考表 <https://www.nma-fallout.com/threads/fallout-1-reference-tables-for-scripts-stats-critters.194479/>；遭遇 <https://www.nma-fallout.com/threads/random-special-and-unique-encounters.164852/>

## 已知版本差异与 bug

- CE 代码是 v1.1，但按 1.2 格式读 MSG（issue #28）。
- 交易价格 bug：对话进交易比按钮进交易更便宜；Beth/Zack"折扣"实为涨价（issue #48）。
- 未找到 v1.1↔v1.2 完整数值差异清单；本机为 Steam 版（见 notes 的"本机游戏版本与补丁基线"）。

## 取数原则

规则公式以 fallout1-ce / fallout1-re 为准，名称与描述以本机 `TEXT/ENGLISH/GAME/*.MSG` 为准；Fixt Excel、Fo1in2 数据只作交叉核对。
