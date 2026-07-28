# Fallout INT 格式与反汇编

## 文件布局

经典 Fallout INT 使用大端序。文件依次包含 42 字节启动代码、过程数量、每项 24 字节的过程表、命名空间、静态字符串空间、启动尾代码和过程体。过程项包含名称偏移、标志、定时值、条件地址、过程体地址与参数数量。命名空间和非空字符串空间由长度、若干“16 位偶数字节长度 + 零结尾字符串”记录及 `0xFFFFFFFF` 终止符组成；空空间直接写入 `0xFFFFFFFF`。

指令使用 16 位大端操作码。整数、浮点和静态字符串常量分别为 `0xC001`、`0xA001`、`0x9001`，其后再跟 4 字节参数；其他指令没有内联参数，而是操作运行时栈。解析器验证固定启动序列、元数据跳转、表边界、字符串终止、过程入口及每个过程的指令边界，但绝不执行字节码。

主要依据为 [Fallout Community Edition `intrpret.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/int/intrpret.cc) 与 [`intrpret.h`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/int/intrpret.h)。同时核对了 Anchorite 的 [int2ssl 源码包](https://fodev.net/files/mirrors/teamx-utils/int2ssl_src.rar)，下载包 SHA-256 为 `492FC0B3AD3A107090A7112632D14EB29CE36ECBF9E324091A81C78DA818D5EB`；该源码只用于格式交叉验证，没有编译或运行其中程序。

## MSG 关联

反汇编器识别 `message_str`、`gsay_reply`、`gsay_option`、`gsay_message` 和 `giq_option`。它从栈式表达式恢复消息列表编号、消息编号、智力条件、反应值和目标过程。提供 MSG 后，工具按“在该 MSG 中命中的字面消息编号数量”推断唯一的消息列表编号，再只关联该列表；动态编号、其他列表和缺失编号会单独标记，避免误配。

## 输出与限制

JSON 保留完整布局、过程、指令、十六进制偏移、来源哈希和消息引用；文本文件提供逐过程反汇编；CSV 便于筛选对话边。输出仍限制在 `workspace/`，默认拒绝覆盖并保护 INT/MSG 输入不被同名派生文件替换。

`disassemble-int-batch` 可同时扫描已提取来源和只读松散 `DATA/`，按“松散 DATA 同名 MSG、同来源、DAT 英文 MSG”的顺序关联唯一候选。消息缺失或损坏只记警告，不阻断 INT 自身。批次复跑会核对 INT 哈希、关联 MSG 哈希、组件版本，以及反汇编和消息 CSV 的大小与 SHA-256。

当前输出不是高层 SSL 反编译结果，也不重建局部变量名或完整控制流。已知操作码显示名称，尚未命名但位于 Fallout 1 范围内的操作码以 `op_XXXX` 保留并汇总。
