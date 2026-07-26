# Fallout 1 DAT1 格式笔记

## 已核对的目录结构

DAT1 从文件开头读取，整数使用大端序。根表包含目录数量及三个 32 位字段，随后是长度为 1 字节的目录名。每个目录依次包含文件数量、三个 32 位字段，以及若干文件条目。文件条目由长度前缀文件名、压缩模式、数据偏移、原始大小和压缩大小组成。

已知压缩模式为：`0x20`（未压缩）和 `0x40`（分块 LZSS）；社区引擎还将 `0x10` 作为单段 LZSS 处理，但本机 `MASTER.DAT` 与 `CRITTER.DAT` 中没有观察到该模式。目录清单会识别并报告 `0x10`，提取器只接受已由真实档案验证的 `0x20` 和 `0x40`。

## 交叉来源

- [Fallout Community Edition](https://github.com/alexbatalov/fallout1-ce) 的 `src/plib/assoc/assoc.cc` 与 `src/plib/db/db.cc`：游戏运行时的 DAT 目录读取逻辑；本次核对提交为 `0609bcfd0ec40ff0571d0f57fab2821eb461dc8b`。
- [wipe2238/fo](https://github.com/wipe2238/fo/tree/master/dat) 的 `dat1.go`：MIT 许可的独立 DAT1 解析实现；本次核对提交为 `e659864d4c8dd5a53036252f5a1d15cbb1b21f21`。
- [Go package documentation](https://pkg.go.dev/github.com/wipe2238/fo/dat)：公开接口和字段语义。

本项目重新实现最小只读解析器，不复制上述项目代码。后续增加解压前，必须继续核对 LZSS 变体和异常输入处理。
