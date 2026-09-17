# MSG 转换阶段结果

关联：[[资源提取设计方案]] · [[工作计划 Checklist]] · [[安全提取阶段结果]]

## 已实现能力

`fallout1resource` 已增加 `convert-msg` 命令。它严格读取源文件，识别 ASCII、UTF BOM、UTF-8、GBK、Big5 与 GB18030，并把检测方法、置信度和候选评分写入 JSON。用户也可用 `--encoding` 明确指定编码；解码错误会直接停止，不会静默插入替换字符。

代码已保存为本地提交 `a8b06c2 feat(msg): add safe text conversion`，尚未推送到 GitHub。

解析遵循游戏消息加载器的三字段结构 `{编号}{语音}{文本}`：忽略字段外内容，移除字段内换行，限制单字段为 1023 个源编码字节。重复编号全部保留，但只有最后一次出现标记为 `effective: true`，与游戏的覆盖行为一致。

命令默认 dry-run。`--execute` 只在 `workspace/` 内生成 UTF-8 JSON、带 BOM 的 UTF-8 CSV 和 JSON 的 SHA-256 校验文件；已有输出默认拒绝覆盖，显式 `--overwrite` 才执行原子替换。

## HAROLD.MSG 验证

| 来源 | 源编码 | 出现次数 | 唯一编号 | 最终生效 | 源 SHA-256 |
|---|---|---:|---:|---:|---|
| `MASTER.DAT` 英文原文 | ASCII | 192 | 192 | 192 | `E61BC2CF5505D97D1C0D51D81AD90C0B4ECA46D4191C922FAA157BBFE138E40B` |
| `DATA/` 中文覆盖文件 | GBK（中置信度） | 377 | 194 | 194 | `F1761BCAAB038952D18602A8E907AF4C53E8FA198AD8928933EB180FCA43325F` |

中文文件存在大量相邻的重复编号，符合“原文记录后追加译文记录”的结构。导出结果按来源隔离在：

- `workspace/output/text/master/TEXT/ENGLISH/DIALOG/HAROLD.json`
- `workspace/output/text/loose-data/TEXT/ENGLISH/DIALOG/HAROLD.json`

对应 CSV 和校验文件位于同目录。两份 JSON 的侧载 SHA-256 均已验证匹配。

## 安全复核

37 项自动测试通过；另有 2 项符号链接逃逸测试因当前 Windows 账户没有创建符号链接权限而跳过。`MASTER.DAT` 与 `CRITTER.DAT` 的 SHA-256 操作后仍与基线一致。游戏目录只被读取，所有派生文件都在代码工程的忽略目录 `workspace/` 中，不会进入 Git。
