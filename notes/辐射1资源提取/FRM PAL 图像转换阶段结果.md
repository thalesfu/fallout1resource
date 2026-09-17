# FRM/PAL 图像转换阶段结果

关联：[[资源提取设计方案]] · [[工作计划 Checklist]]

## 已实现能力

`fallout1resource` 已增加 `convert-frm` 命令。它以只读方式验证 FRM 版本、62 字节文件头、6 个方向偏移、共享方向序列、12 字节帧头和像素数量，并使用指定 PAL 生成标准索引 PNG。工具只读取源文件，不修改 FRM、PAL 或游戏目录。

方向共享相同数据偏移时只输出一组 PNG，JSON 仍保留全部 6 个逻辑方向的全局 X/Y 偏移和序列映射。每帧的宽高、像素数、文件偏移和局部 X/Y 偏移也完整记录。帧 PNG 使用索引 0 作为透明色。

PAL 前 768 字节按 256 个 6 位 RGB 三元组解析；任一分量超过 63 的颜色按游戏逻辑映射为黑色，同时保留原值和有效状态。后续颜色查找表不解析、不修改，只记录长度和源哈希。

## 真实样本验证

| 项目 | `HARLDNG.FRM` | `MADDOGAA.FRM` |
|---|---:|---:|
| 源 SHA-256 | `43AC813C571105DA5921B2C402AD99293AB4E33D6DE3976ED4FD2F253A1EFE56` | `7304D0EB170F2A68C1DB7FB954481FE977C2985580AE12F31FF8B0DC2F84BF81` |
| 逻辑方向 | 6 | 6 |
| 唯一方向序列 | 1 | 6 |
| 每方向帧数 | 8 | 10 |
| 导出 PNG 数 | 8 | 60 |
| 帧哈希错误 | 0 | 0 |

`COLOR.PAL` SHA-256 为 `315E06106C42646067117BC84CFDB11C992A5A3A5E058FCAAF24D5C0531A5DF9`。两组 JSON 校验文件和全部 PNG 的记录哈希均已复核一致；哈罗德头像及六方向角色动画已人工查看，透明背景、颜色和像素排列正常。

## 输出位置

- `workspace/output/images/master/ART/HEADS/HARLDNG.FRM/`
- `workspace/output/images/critter/ART/CRITTERS/MADDOGAA.FRM/`

输出全部位于 Git 忽略的本地工作区。早期两个样本目录已在全量结果验证同源哈希后移到 `workspace/archive/pre-full-batch/images/`，避免统一索引重复认领；可恢复且未删除。原始提取文件分别保存在 `workspace/raw/master/` 和 `workspace/raw/critter/`，并有提取清单和源哈希可追溯。

## 安全与测试

66 项自动测试通过；另有 4 项符号链接逃逸测试因当前 Windows 账户没有创建符号链接权限而跳过。FRM/PAL 测试覆盖截断文件头、错误版本、动作帧越界、数据大小不符、像素数量不符、方向偏移乱序、PAL 截断、PNG CRC、绝对路径、父目录穿越、符号链接逃逸、覆盖拒绝和原子覆盖。

本阶段代码已提交为 `ba40325 feat(frm): add safe palette PNG export`。提交仅保存在本地，尚未推送；游戏资源和转换产物均未进入 Git。
