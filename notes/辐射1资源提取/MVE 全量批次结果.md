# MVE 全量批次结果

## 结论

**已验证：** 已从 `MASTER.DAT` 提取并转换本机 Fallout 1 的全部 13 个 MVE，0 失败。每个影片均生成原生结构 JSON、完整段 CSV、首帧 PNG 和 MPEG-4/AAC 预览；11 个有音轨的影片另生成 16 位 PCM WAV。最终复跑 13 个全部为 `skipped_verified`。

## 批次数据

| 项目 | 数值 |
|---|---:|
| 源文件 | 13 个，146,016,598 字节 |
| 派生输出 | 76 个文件，135,526,901 字节 |
| 结构 | 9,200 个块；68,942 个操作段 |
| 视频 | 全部 432×320、8 位、数据格式 `0x11` |
| 可解码帧 | 8,563 帧；572.415592 秒 |
| 显示事件 | 8,978 次；按计时累计 600.497480 秒 |
| 音轨 | 11 个双声道 DPCM、22,050 Hz；2 个静音影片 |
| 音频段 | 7,918 个音频段；8,085 个静音段 |

最终转换清单：`batch-mve-20260728T152018593844Z.json`。最终哈希复跑清单：`batch-mve-20260728T152047201673Z.json`，13 个全部验证后跳过、0 失败。

## 帧计数修正

首轮有 6 个影片因“原生帧数与 ffprobe 不同”失败。调查确认 `0x07` 是显示缓冲事件，不保证伴随新视频数据；这 6 个文件的 `display_count` 大于实际视频数据段数。FFmpeg 解码帧数与 `0x06/0x10/0x11` 数据段数逐个一致。

工程现分别保存 `display_count` 与 `frame_count`，并以 `frame_display_indices` 把解码帧恢复到原生显示事件时间戳。13 个影片中 6 个两者不同，不能再互相替代。修正后所有 MP4 视频时长与显示计时完全一致；11 个 PCM 音轨与显示时长的最大差为 0.002581 秒。

## 工具链与可恢复性

执行前重新核对固定 FFmpeg、ffprobe、7 个 DLL 及运行库组合哈希，全部与 `config/ffmpeg-mve.json` 一致。批处理复跑同时核对源哈希、转换器版本、工具链哈希及 JSON/CSV/PNG/WAV/MP4 的大小和 SHA-256。

旧 `BOIL3` 示例在源哈希相同后移动到 `workspace/archive/pre-full-batch/video/BOIL3/`。诊断用 `CATHEXP.mp4` 移到 `workspace/archive/investigation/mve-frame-probe/`，均未删除。

批处理提交：`8d3fc8a feat(mve): add recoverable full conversion`；显示时间轴修复：`df2120a fix(mve): preserve native display timing`。全套自动测试 156 项通过，7 项仅因当前 Windows 账户无符号链接权限而跳过。

## 待人工抽查

- [ ] 试听 11 个有声影片的开头、中段、结尾，检查声画同步。
- [ ] 查看 2 个静音影片，确认静音符合内容而非音轨丢失。
- [x] 结构与时长抽查 `display_count != frame_count` 的 6 个影片；停帧位置已写入 `frame_display_indices`，MP4 时长全部吻合。
