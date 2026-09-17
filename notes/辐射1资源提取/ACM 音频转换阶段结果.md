# ACM 音频转换阶段结果

## 结论

`fallout1resource` 已加入纯 Python Interplay ACM 解码器和 `convert-acm` 命令。游戏安装目录始终只读；代表样本先由 DAT1 安全提取器复制到工程 `workspace/raw/`，WAV、JSON 和校验文件只写入 `workspace/output/audio/`。

算法按 Fallout Community Edition 固定使用的 `alexbatalov/adecode` v1.0.0（提交 `e4a8b0f3b66826e0b7779a25d79df8497f8f8087`）核对并移植，来源为 MIT 许可。工程没有引入第三方可执行文件或运行依赖。

## 真实样本

| 源资源 | ACM SHA-256 | 声道 | 采样率 | 解码样本 | WAV 时长 |
|---|---|---:|---:|---:|---:|
| `SOUND/SFX/IB1P1XX1.ACM` | `7AEED2BC2169CB14EEAEEAF5B973E9890751C4768AFBF60CB15E6DB4C51FC1AF` | 1 | 22,050 Hz | 1,516 | 0.068753 秒 |
| `SOUND/SPEECH/HARLD/HROLD1.ACM` | `004EEF674549B179E132BF659C245541D78A9C8A46AEE1250CCB8E3F1EAD0299` | 2 | 22,050 Hz | 98,327 | 2.229660 秒 |

哈罗德语音的交错样本数为奇数，不能整除双声道。解码器保留全部 98,327 个源样本，只在 WAV 末尾补 1 个静音样本以组成完整声道帧，并在 JSON 的 `partial_frame_samples` 与 `wav_padding_samples` 中明确记录。

两个样本合计实际覆盖码带格式 0、3–10、17、18、20–24、26、27、29，其中哈罗德语音跨 25 个解码块；未出现但同属直接量化路径的格式 11–16 由合成测试覆盖，保留格式会被明确拒绝。

## 产物

- `workspace/output/audio/IB1P1XX1/IB1P1XX1.wav`
- `workspace/output/audio/HROLD1/HROLD1.wav`
- 同目录 JSON 保存源路径、源哈希、ACM 头字段、时长和 WAV 哈希。
- 哈罗德 WAV SHA-256：`F7B61925F1CEF653E402B42E9490BFDB10D49FAB3306AE38AF7667BFF0247C5D`

## 验证

- 93 项自动测试通过，6 项符号链接逃逸测试因当前 Windows 用户无创建链接权限而跳过；ACM 新增 14 项覆盖全部直接量化格式、截断、保留格式、路径越界、覆盖和末帧补样本。
- WAV 由标准库重新读取确认：声道数、22,050 Hz 采样率、帧数和数据长度一致。
- 阶段结束后 `MASTER.DAT` 与 `CRITTER.DAT` SHA-256 仍分别为 `A79090E035E33C178AEE23FE72F7EF0A5F3BE76F733C252522983AAD22F87364`、`66800803FC06030573561B4D25ED7A9F0EA7A4B84B734E6D18A9FEFAEEB990A9`。
- 本地 Git 里程碑：`5817cb2 feat(acm): add safe WAV decoding`，未推送远端。
