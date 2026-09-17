# MVE 动画转换阶段结果

## 结论

`fallout1resource` 已加入原生 Interplay MVE 容器解析器和 `convert-mve` 命令。dry-run 仅依靠 Python 标准库即可核对文件头、块、操作段、计时、画面参数和音轨参数；实际像素与 DPCM 解码使用显式指定、固定版本和哈希的 FFmpeg。

外部工具不会从 `PATH` 自动发现，也不直接写最终产物。FFmpeg 先写入 `workspace/` 内临时目录，工程再核对源与产物的宽高、帧数、声道和采样率，最后原子落盘。游戏目录始终只读。

## 代表样本

| 项目 | 值 |
|---|---|
| 档案内路径 | `ART/CUTS/BOIL3.MVE` |
| 源大小 | 2,768,806 字节 |
| 源 SHA-256 | `E23BF26613AD14B81128FED81A8C14227E00C89373D7E46CD41F27C2A76372B3` |
| 容器结构 | 168 个块、1,238 个操作段 |
| 画面 | 432×320、8 位调色板、150 帧 |
| 帧率 | `125000/8341`，约 14.986213 fps |
| 时长 | 10.0092 秒 |
| 音轨 | Interplay DPCM、16 位、双声道、22,050 Hz |
| 视频数据格式 | 操作码 `0x11` |

## 外部工具审计

- FFmpeg 源提交：`acf6b520c1e73707190c0a591735ee8c7fbe8f58`
- BtbN 发布：`autobuild-2026-07-27-14-00`
- 包名：`ffmpeg-N-125781-gacf6b520c1-win64-lgpl-shared.zip`
- 发布包 SHA-256：`F70F968D389E163D9A21F1149D160EE6E00A4C240FF7B6565BD3FF499D5942F3`
- `ffmpeg.exe` SHA-256：`15D736F24C54DBA2AB2B8DA8E207190519155C009DADDB338F0B4BBE6DE5A99B`
- `ffprobe.exe` SHA-256：`380C34ED327C2E46F23E46BC8B773E6D78C31D7A7C16B17CC6A2BE7F9BD0F1AB`
- 7 个运行库组合清单 SHA-256：`D392AD546E1FA7E7436FAA09EB03EE8444C24751CF7275848E1ADD4702B46BB1`

下载包与解压目录只位于本机临时研究目录，不进入 Git。机器无关配置保存于代码工程 `config/ffmpeg-mve.json`。

## 输出

目录：`fallout1resource/workspace/output/video/BOIL3/`

- `BOIL3.json`：原生解析、FFmpeg/运行库哈希、转换前后 probe 与派生文件哈希。
- `BOIL3.segments.csv`：全部 1,238 个操作段的位置、大小、版本和名称。
- `BOIL3.poster.png`：432×320 首帧，SHA-256 `A01DD4A8C49717911B94754DEE938DD3A589EB4B76D191B178CA05775A699F51`。
- `BOIL3.audio.wav`：PCM 16 位、双声道、22,050 Hz、220,700 帧，SHA-256 `97E208C321439CE098CE4369223081BAF2DE1578BA2437CACA5017E0672E150D`。
- `BOIL3.preview.mp4`：MPEG-4 Part 2/AAC 便捷预览，150 帧，SHA-256 `B55A5B618EBAE6BE424BC9BDCCC97D215B604E3F050A5731A679ED8AAFC8D2BA`。此文件经过有损转码，不作为保存格式。

## 验证

- 107 项自动测试通过；7 项符号链接逃逸测试因当前 Windows 用户无创建链接权限而跳过。
- MVE 新增 14 项测试，覆盖有/无音轨、计时、帧计数、截断、块/段越界、异常调色板、路径逃逸、覆盖拒绝、源碰撞和外部工具缺失。
- 原生解析得到的宽高、帧数、声道和采样率与 ffprobe 完全一致。
- 首帧 PNG 已目视确认能够正常还原 Fallout 过场画面。
- 阶段结束后 `MASTER.DAT` 与 `CRITTER.DAT` SHA-256 仍分别为 `A79090E035E33C178AEE23FE72F7EF0A5F3BE76F733C252522983AAD22F87364`、`66800803FC06030573561B4D25ED7A9F0EA7A4B84B734E6D18A9FEFAEEB990A9`。
- 本地 Git 里程碑：`738f08e feat(mve): add audited preview conversion`，未推送远端。
