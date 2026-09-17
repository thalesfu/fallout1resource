# INT 反汇编阶段结果

关联：[[资源提取设计方案]] · [[工作计划 Checklist]] · [[MSG 转换阶段结果]]

## 已实现能力

`fallout1resource` 已增加 `disassemble-int` 命令。它以只读方式验证 42 字节启动代码、24 字节过程项、命名空间、静态字符串空间、启动尾代码和过程体，随后按大端 16 位操作码反汇编。整数、浮点与字符串常量的 4 字节参数会被解析，其他操作码按栈式指令保留。

工具只分析字节，不执行脚本。输出是研究用反汇编，不是可重新编译的 SSL；未命名但处于 Fallout 1 合法范围内的操作码会保留数值并报告，不会被猜测替换。

可选的 `--msg` 参数会关联 `message_str`、`gsay_reply`、`gsay_option`、`gsay_message` 和 `giq_option`。工具可恢复消息编号、智力条件、反应值及选项目标过程，并通过实际命中数量推断消息列表编号。动态编号和其他消息列表会保持未关联状态。

## HAROLD.INT 验证

| 项目 | 结果 |
|---|---:|
| 源文件大小 | 13,314 字节 |
| 源 SHA-256 | `666832095A324E8507110CFFC1AF55311B1334124EDD8499C3350E7E4B77A579` |
| 过程表项目 | 90 |
| 实际过程体 | 89 |
| 标识符 | 93 |
| 指令总数 | 2,700 |
| 未知操作码 | 0 |
| 消息调用 | 155 |
| 成功关联中文 MSG | 154 |
| 关联到的唯一消息编号 | 150 |
| 已解析选项目标 | 87 / 87 |

工具从字面消息编号的匹配情况唯一推断 `message_list_id = 45` 对应 HAROLD.MSG。剩余 1 个调用位于 `Goodbyes`，编号表达式为 `random(100, 105)`，因此保持动态状态，没有被错误关联。消息调用组成：51 个回复、87 个智力条件选项、15 个结束式消息和 2 个消息字符串查询。

## 输出位置

- `workspace/output/scripts/master/SCRIPTS/HAROLD.json`
- `workspace/output/scripts/master/SCRIPTS/HAROLD.disasm.txt`
- `workspace/output/scripts/master/SCRIPTS/HAROLD.messages.csv`
- `workspace/output/scripts/master/SCRIPTS/HAROLD.json.sha256`

JSON、INT 源和 MSG 源哈希均已复核一致。输出全部位于 Git 忽略的本地工作区。

## 安全与测试

49 项自动测试通过；另有 3 项符号链接逃逸测试因当前 Windows 账户没有创建符号链接权限而跳过。测试覆盖错误启动签名、截断过程表、非法操作码、错误元数据跳转、路径越界、覆盖拒绝、原子覆盖和防止派生文件替换源文件。

格式依据主要来自 Fallout Community Edition 的解释器源码；另下载并审阅 Anchorite 的历史 `int2ssl` 源码包，SHA-256 为 `492FC0B3AD3A107090A7112632D14EB29CE36ECBF9E324091A81C78DA818D5EB`。未编译或运行第三方程序。

## 本地提交

本阶段代码已提交为 `678fddc feat(int): add safe script disassembly`。提交仅保存在本地，尚未推送到远端；游戏资源、提取物和转换产物均未进入 Git。
