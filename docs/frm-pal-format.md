# Fallout 1 FRM/PAL 格式说明

## FRM 布局

FRM 使用大端整数。62 字节文件头依次包含首字段、帧率、动作帧、每方向帧数、6 个方向的 X/Y 全局偏移、6 个方向数据偏移和数据区大小。本批原版资源中首字段绝大多数为 4，`ART/INVEN/OKNIFE.FRM` 为 3；Fallout 1 CE 的原版逻辑还原会读取但不校验该字段。因此解析器接受实际出现的 3 和 4，并继续严格验证所有尺寸和偏移。

每个方向数据偏移相对 62 字节文件头之后的位置。多个相邻方向可以共享同一偏移，因此导出器只写一份共享 PNG 序列，并在 JSON 中保留全部 6 个逻辑方向的映射。每帧由 12 字节头和索引像素组成：宽、高、像素数、X/Y 帧偏移；像素数必须等于宽乘高。

critter 档案还包含 `.FR0`–`.FR5` 分方向成员。每个文件只保存扩展名所指方向的数据，且六个数据偏移均为 0。头部 `dataSize` 通常是六个成员有效载荷的总和，但少数原版家族成员彼此不一致，另有六个只出现 `.FR0` 的资源以本文件载荷作为该值。因此解析器按单方向读取，分别记录“头部声明量”和“本文件实际存储量”，不把前者猜测为单文件边界。

## PAL 与 PNG

`COLOR.PAL` 前 768 字节是 256 个 RGB 三元组，每通道有效范围为 0–63。游戏读到任一分量大于 63 的三元组时将该颜色映射为黑色；导出器保留原值和 `mapped` 状态，并用 `(value << 2) | (value >> 4)` 扩展为 8 位颜色。其余字节属于游戏颜色查找表，只记录长度和源文件哈希，不作修改。

PNG 使用索引色并保持原像素索引；帧图将索引 0 标为透明，调色板预览保持全部颜色不透明。元数据记录源 FRM/PAL 路径、大小、SHA-256、方向、帧偏移以及每个 PNG 的大小和 SHA-256。

## 交叉核验

- [Fallout Community Edition `art.h`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/art.h)：运行时 FRM 与帧结构。
- [Fallout Community Edition `art.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/art.cc)：大端字段读取、共享方向与帧遍历行为；首字段只读取和写回，不做版本判断。
- [Fallout Community Edition `color.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/plib/color/color.cc)：PAL 三元组范围和无效颜色处理。

本项目重新实现最小只读解析器，不复制引擎源码，也不调用第三方图像转换程序。
