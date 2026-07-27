# Fallout MSG 格式与转换

## 解析规则

MSG 文件由连续三字段记录组成：`{number}{audio}{text}`。解析器依据 Fallout Community Edition 的消息加载逻辑实现：字段外字符会被跳过，字段内换行不进入游戏文本，单字段最多 1023 个源编码字节。孤立的 `}`、未闭合字段、无效编号和不完整三字段记录均会报错。

重复编号具有运行时语义：游戏保留最后一次出现的内容。导出器不会提前去重，而是保留每次出现的位置、原始编号、源文本换行及次序，并通过 `effective` 标记最后一项。这样既能复现游戏行为，也能审计汉化文件中常见的“原文后接译文”结构。

主要核对来源为 [Fallout Community Edition `message.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/message.cc) 与 [`message.h`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/message.h)。本项目重新实现解析逻辑，不复制其代码。

## 编码策略

源字节始终保持不变。检测顺序为 BOM、纯 ASCII、严格 UTF-8，再对 GBK、Big5（必要时 GB18030）做严格解码与中文字符评分；无法可靠识别时使用可逆的 Latin-1 低置信度回退。JSON 会记录所选编码、检测方法、置信度和候选评分。`--encoding` 可覆盖自动检测，且仍采用严格解码，错误不会被替换字符掩盖。

## 输出与安全

`convert-msg` 默认 dry-run。`--execute` 只允许写入指定 `workspace/`，输出 JSON、CSV 和 `json.sha256`；JSON 使用 UTF-8，CSV 使用带 BOM 的 UTF-8 以方便表格软件打开。写入前先解析完整文件并检查全部目标，现有文件默认拒绝覆盖；`--overwrite` 使用原子替换。

JSON 的 `derived.csv` 同时记录 CSV 的工作区相对路径、大小和 SHA-256，因此批处理可以验证三个输出是否仍与来源及当前工具版本一致。`convert-msg-batch` 扫描 `workspace/raw/<来源>/`，保持来源隔离并将逐文件结果写入 `manifests/batch-msg-*.json`；单个文件失败不会中断其余文件。

真实 `HAROLD.MSG` 验证结果：DAT 英文文件为 ASCII，192 条且无重复编号；`DATA/` 中文覆盖文件识别为 GBK，共 377 次出现、194 个唯一编号，最终生效 194 条。中文文件的大量重复编号被完整保留。
