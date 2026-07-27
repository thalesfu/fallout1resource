# 工具评估记录

## 当前决定

DAT1、MSG、INT、FRM、PAL、MAP、PRO、LST、ACM 和 MVE 容器结构均由 Python 标准库代码自行读取。MVE 的块预测视频解码使用显式指定、固定版本和哈希的 FFmpeg；工程不搜索 `PATH`，不把第三方二进制提交到 Git，也不让外部工具直接写最终目标。解析器先独立验证来源，FFmpeg 只写 `workspace/` 内临时目录，产物通过尺寸、帧数、声道和采样率复核后再原子落盘。

## 候选参考

| 项目 | 用途 | 许可/状态 | 当前处理 |
|---|---|---|---|
| Fallout Community Edition | 与游戏行为交叉核验 | Sustainable Use License | 仅作行为参考 |
| `alexbatalov/adecode` v1.0.0（`e4a8b0f`） | Interplay ACM 文件头、码带与逆变换参考 | MIT | 算法移植为纯 Python；保留完整许可声明，不引入二进制或运行依赖 |
| FFmpeg `acf6b520c1` / BtbN LGPL shared build | Interplay MVE 视频、DPCM 音频解码与预览转码 | LGPL v3 构建，Windows 包由 FFmpeg 官方下载页列出 | 显式本地路径调用；记录发布包、EXE、ffprobe 和 DLL 哈希，不提交二进制 |
| `wipe2238/fo` | DAT1/DAT2 与 LZSS 参考 | MIT，接口标为不稳定 | 仅作格式交叉核验 |
| Anchorite `int2ssl` 源码 | INT 布局、过程边界与常量参数参考 | 2007 年历史源码包，许可信息未明确 | 仅下载源码审阅，不编译、不执行；包 SHA-256：`492FC0B3AD3A107090A7112632D14EB29CE36ECBF9E324091A81C78DA818D5EB` |
| 传统 UNDAT/DAT Explorer | 人工解包比较 | 版本和来源需进一步确认 | 暂不下载、不执行 |

所有最终写入仍由本项目控制。第三方资料用于交叉核对已观察到的格式；ACM 算法的 MIT 来源和许可文本见 `docs/third-party-notices.md`。FFmpeg 是 MVE 转换的显式外部工具，不属于 Python 运行依赖；下载来源和固定哈希见 `config/ffmpeg-mve.json`。
