# Fallout 1 Resource

《辐射 1》资源研究工具。当前可盘点 Fallout 1 DAT1 档案与 `DATA/` 松散文件、安全提取选定资源，转换 `.MSG`、反汇编 `.INT`、使用 `.PAL` 将 `.FRM` 导出为 PNG、把 Interplay `.ACM` 解码为 PCM WAV，并检查 `.MVE` 后生成可预览影片；不会修改或写回游戏安装目录。

## 安全边界

- 游戏安装目录始终作为只读输入。
- 所有本地清单、缓存和后续提取物只能写入 `workspace/`。
- 当前 `workspace/` 快照纳入 Git，用于复现研究结果并避免重复提取；更新前应检查差异和容量。
- 原始 DAT 档案和游戏安装目录仍不提交；`workspace/index/derived.jsonl` 通过 Git LFS 保存。
- `DATA/SAVEGAME/` 默认排除。

## 运行

要求 Python 3.11 或更高版本，无第三方运行依赖。在仓库根目录执行：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m fallout1resource inventory `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --workspace "$PWD\workspace"
```

默认输出 `workspace/manifests/inventory.json`、`inventory.csv` 和 JSON 的 SHA-256 校验文件。加入 `--skip-source-hash` 可跳过两个 DAT 的完整哈希；加入 `--hash-loose` 可计算每个松散文件的哈希。

## 安全提取

`extract` 默认只显示计划，不写文件，而且必须提供至少一个路径、扩展名或资源类型筛选器：

```powershell
python -m fallout1resource extract `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --workspace "$PWD\workspace" `
  --path "TEXT/ENGLISH/DIALOG/HAROLD.MSG"
```

检查计划后加入 `--execute` 才会提取。输出按来源隔离在 `workspace/raw/master/` 或 `workspace/raw/critter/`。已有文件默认导致整个批次在写入前停止；只有明确加入 `--overwrite` 才会原子替换。当前支持 DAT1 `0x20` 未压缩条目和 `0x40` 分块 LZSS 条目，其他模式直接报错。

## MSG 转换

`convert-msg` 先严格解析整个源文件，默认只显示预览；加入 `--execute` 后才在 `workspace/` 内写入 UTF-8 JSON、带 BOM 的 UTF-8 CSV 和 JSON 校验文件：

```powershell
python -m fallout1resource convert-msg `
  --input "$PWD\workspace\raw\master\TEXT\ENGLISH\DIALOG\HAROLD.MSG" `
  --workspace "$PWD\workspace" `
  --output "output/text/master/TEXT/ENGLISH/DIALOG/HAROLD.json" `
  --execute
```

解析器支持 ASCII、UTF BOM、严格 UTF-8，并对 GBK、Big5、GB18030 候选做可审计检测；不确定时可用 `--encoding gbk` 明确指定。重复消息编号不会丢弃：全部出现项都写入导出文件，并以 `effective` 标记游戏实际采用的最后一项。已有输出默认拒绝覆盖，显式 `--overwrite` 才会原子替换。

已提取的 MSG 可用可恢复批处理统一转换。省略 `--execute` 时只统计文件；执行后逐文件记录成功、校验后跳过和失败状态，并将批次清单写入 `workspace/manifests/`：

```powershell
python -m fallout1resource convert-msg-batch `
  --workspace "$PWD\workspace" `
  --source master `
  --execute
```

再次运行时，只有来源哈希、工具版本、JSON 校验和及 CSV 哈希全部吻合的输出才会跳过。过期或不完整输出需显式加入 `--overwrite` 后恢复。

松散 `DATA/` 无需复制即可作为只读来源，并自动排除 `SAVEGAME/`：

```powershell
python -m fallout1resource convert-msg-batch `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --workspace "$PWD\workspace" `
  --source data `
  --execute
```

## INT 反汇编与消息关联

`disassemble-int` 只解析字节码，不执行脚本。可同时提供同名 MSG，让工具推断消息列表编号并关联最终生效文本：

```powershell
python -m fallout1resource disassemble-int `
  --input "$PWD\workspace\raw\master\SCRIPTS\HAROLD.INT" `
  --msg "C:\Program Files (x86)\Steam\steamapps\common\Fallout\DATA\TEXT\ENGLISH\DIALOG\HAROLD.MSG" `
  --workspace "$PWD\workspace" `
  --output "output/scripts/master/SCRIPTS/HAROLD.json" `
  --execute
```

默认仍为 dry-run。执行后生成结构化 JSON、`.disasm.txt`、`.messages.csv` 和 JSON 校验文件。反汇编结果是分析产物，不是可重新编译的 SSL 源码；未知但位于 Fallout 1 操作码范围内的指令会保留数值并报告，不会被猜测成其他指令。

全量脚本使用可恢复批处理。它优先关联同名松散 `DATA` MSG，否则使用 DAT 英文 MSG；消息缺失或损坏只作为警告，INT 仍会独立反汇编：

```powershell
python -m fallout1resource disassemble-int-batch `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --workspace "$PWD\workspace" `
  --source master `
  --source data `
  --execute
```

## FRM/PAL 图像转换

`convert-frm` 严格验证 FRM 文件头、6 个逻辑方向、共享数据偏移和每帧像素大小，再用指定 PAL 的前 256 个颜色项生成索引 PNG：

```powershell
python -m fallout1resource convert-frm `
  --input "$PWD\workspace\raw\master\ART\HEADS\HARLDNG.FRM" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --workspace "$PWD\workspace" `
  --execute
```

默认只显示计划。执行后生成元数据 JSON、调色板预览、每个唯一方向序列的 PNG 帧和 JSON 校验文件。方向共享同一数据偏移时不会复制画面，但 6 个方向各自的全局偏移和序列映射仍写入 JSON。帧 PNG 将调色板索引 0 标为透明；原始 6 位颜色、无效颜色语义及 PAL 后续查找表长度均保留在元数据中。

`convert-frm-batch` 可恢复地处理 DAT 提取物和松散 `DATA/`，输出按来源与原扩展名隔离，避免 `.FRM` 与 `.FR0`–`.FR5` 冲突：

```powershell
python -m fallout1resource convert-frm-batch `
  --workspace "$PWD\workspace" `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --source master --source critter --source data `
  --execute
```

再次执行会复核源文件、调色板、元数据和所有 PNG 的大小与 SHA-256，仅跳过完整且属于当前转换器版本的产物。旧产物或被改动的文件必须显式加 `--overwrite` 才会替换。

## MAP/PRO/LST 结构化转换

`convert-map` 解析版本 19 MAP 的变量、100×100 地砖层、五类脚本和递归对象树，并通过 PID 的类型字节及低 24 位一基行号连接六类原型 LST 和 PRO：

```powershell
python -m fallout1resource convert-map `
  --input "$PWD\workspace\raw\master\MAPS\HUBOLDTN.MAP" `
  --prototype-root "$PWD\workspace\raw\master\PROTO" `
  --scripts-lst "$PWD\workspace\raw\master\SCRIPTS\SCRIPTS.LST" `
  --workspace "$PWD\workspace" `
  --execute
```

默认只显示摘要。执行后生成完整 JSON、扁平对象 CSV 和 JSON 校验文件。JSON 保留 LST 的物理顺序与原始行、全部地砖值、脚本索引、对象及背包层级，并包含本地图实际引用的 PRO 全字段。物品和场景对象的可变附加数据长度必须与其 PRO 子类型吻合，否则转换停止。

全量地图使用可恢复批处理；默认依赖 `workspace/raw/master/PROTO` 和 `SCRIPTS/SCRIPTS.LST`：

```powershell
python -m fallout1resource convert-map-batch `
  --workspace "$PWD\workspace" `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --source master `
  --execute
```

复跑会重新解析地图和实际引用的 PRO，并核对六类 LST、脚本列表、对象 CSV 与 JSON 哈希；依赖或派生物变化后需显式 `--overwrite` 才会替换。

## MAP 地面、墙壁、场景与物品渲染

`render-map-floor` 把结构化 MAP JSON 的一个楼层与 `TILES.LST`、地砖 FRM 和主调色板合成为等距 PNG。默认 dry-run；执行前会验证所有地砖编号和素材，并从实际非透明像素范围计算画布：

```powershell
python -m fallout1resource render-map-floor `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

输出位于 `workspace/output/maps-rendered/<地图>/`，包括地面 PNG、记录坐标原点、画布、输入哈希和所用地砖的 JSON，以及 JSON 校验文件。

`render-map-walls` 在同一坐标系中加入 MAP 墙对象，同时保留墙壁透明层和地面墙壁合成图：

```powershell
python -m fallout1resource render-map-walls `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --walls-list "$PWD\workspace\raw\master\ART\WALLS\WALLS.LST" `
  --walls-dir "$PWD\workspace\raw\master\ART\WALLS" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

墙壁按游戏的六角格锚点和 `OBJECT_FLAT` 两阶段顺序绘制。

`render-map-doors` 继续加入门对象，并把墙和门放回统一的游戏对象顺序；输出门透明层和地面墙壁门合成图：

```powershell
python -m fallout1resource render-map-doors `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --walls-list "$PWD\workspace\raw\master\ART\WALLS\WALLS.LST" `
  --walls-dir "$PWD\workspace\raw\master\ART\WALLS" `
  --scenery-list "$PWD\workspace\raw\master\ART\SCENERY\SCENERY.LST" `
  --scenery-dir "$PWD\workspace\raw\master\ART\SCENERY" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

门严格使用 MAP 保存的方向、动画帧和开关标志；当前不执行地图脚本，也不绘制屋顶或人物。算法与实践记录见 `docs/map-rendering.md`。

`render-map-scenery` 加入全部非门场景对象（楼梯、电梯、梯子和通用场景物件），输出独立场景物件层及地面、墙、门、场景物件的合成图：

```powershell
python -m fallout1resource render-map-scenery `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --walls-list "$PWD\workspace\raw\master\ART\WALLS\WALLS.LST" `
  --walls-dir "$PWD\workspace\raw\master\ART\WALLS" `
  --scenery-list "$PWD\workspace\raw\master\ART\SCENERY\SCENERY.LST" `
  --scenery-dir "$PWD\workspace\raw\master\ART\SCENERY" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

门与其他场景物件会一起按 `OBJECT_FLAT`、六角格和 MAP 源顺序绘制。

`render-map-items` 继续加入地图顶层的容器、武器和杂项物品，同时排除容器或人物库存中没有独立地图坐标的嵌套物品：

```powershell
python -m fallout1resource render-map-items `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --walls-list "$PWD\workspace\raw\master\ART\WALLS\WALLS.LST" `
  --walls-dir "$PWD\workspace\raw\master\ART\WALLS" `
  --scenery-list "$PWD\workspace\raw\master\ART\SCENERY\SCENERY.LST" `
  --scenery-dir "$PWD\workspace\raw\master\ART\SCENERY" `
  --items-list "$PWD\workspace\raw\master\ART\ITEMS\ITEMS.LST" `
  --items-dir "$PWD\workspace\raw\master\ART\ITEMS" `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

该命令输出物品透明层、地面/墙/门/场景物件/物品的统一顺序合成图，以及用 2 像素黄色轮廓勾勒所有物品的 `*-items-highlighted.png`。原始合成图不会被描边覆盖。

`render-map-critters` 再加入 MAP 中保存的人物与生物。人物 FID 会解析为基础造型、动作、武器姿态和分方向 FRM；渲染严格使用对象保存的方向与帧：

```powershell
python -m fallout1resource render-map-critters `
  --map-json "$PWD\workspace\output\maps\master\MAPS\HUBOLDTN\HUBOLDTN.json" `
  --tiles-list "$PWD\workspace\raw\master\ART\TILES\TILES.LST" `
  --tiles-dir "$PWD\workspace\raw\master\ART\TILES" `
  --walls-list "$PWD\workspace\raw\master\ART\WALLS\WALLS.LST" `
  --walls-dir "$PWD\workspace\raw\master\ART\WALLS" `
  --scenery-list "$PWD\workspace\raw\master\ART\SCENERY\SCENERY.LST" `
  --scenery-dir "$PWD\workspace\raw\master\ART\SCENERY" `
  --items-list "$PWD\workspace\raw\master\ART\ITEMS\ITEMS.LST" `
  --items-dir "$PWD\workspace\raw\master\ART\ITEMS" `
  --critters-list "$PWD\workspace\raw\critter\ART\CRITTERS\CRITTERS.LST" `
  --critters-dir "$PWD\workspace\raw\critter\ART\CRITTERS" `
  --critter-names-msg "$PWD\workspace\raw\master\TEXT\ENGLISH\GAME\PRO_CRIT.MSG" `
  --critter-name-translations "$PWD\config\huboldtn-critter-names.zh-CN.json" `
  --item-names-msg "$PWD\workspace\raw\master\TEXT\ENGLISH\GAME\PRO_ITEM.MSG" `
  --item-name-translations "$PWD\config\huboldtn-item-names.zh-CN.json" `
  --label-font "C:\Windows\Fonts\msyh.ttc" `
  --label-font-size 28 `
  --palette "$PWD\workspace\raw\master\COLOR.PAL" `
  --elevation 0 `
  --workspace "$PWD\workspace" `
  --execute
```

该命令输出人物透明层、完整静态合成图，以及同时用 2 像素黄色轮廓标出物品、用 2 像素亮绿色轮廓标出人物的 `*-critters-highlighted.png`。提供名称消息、中文映射和含中文字形的 TrueType/OpenType 字体后，还会生成 `*-critters-labeled-zh-CN.png`：人物优先用脚本文件名区分万斯、斯来匹等复用通用原型的专名，否则读取 `PRO_CRIT.MSG`；配置中显式声明的专名显示“中文名 / English Name”，通用角色类别保持纯中文。物品读取 `PRO_ITEM.MSG`，容器标题下每件 MAP 直接库存各占一行并缩进显示中文名称与数量，空容器则缩进显示“（空）”。人物和物品标签共享自动避让空间，分别使用绿色与黄色细连接线、边框和深色底框。macOS 可把字体参数换成 `/System/Library/Fonts/Hiragino Sans GB.ttc`。

名称来源、英文原名、中文译名、对象 ID、地图格位、标签框位置、容器库存明细和字体 SHA-256 均写入元数据。两种轮廓不会覆盖物品或人物自身的原始像素。命令不运行移动、动画或人物脚本，也不添加运行时玩家角色；缺失的原始人物素材会记录在元数据中而不使用其他造型替换。后续计划依次加入可开关屋顶层、阻挡格与出口调试层、环境光及知识库标注。HUBOLDTN 尚有 776 块有效屋顶地砖，以及 739 个不进入正常美术合成的阻挡格或出口控制对象；详细边界与实施顺序见 `docs/map-rendering.md`。

批量处理哈勃城其他区域时，可将上例中的地图名和楼层替换为 `HUBENT/0`、`HUBDWNTN/0`、`HUBDWNTN/1`、`HUBHEIGT/0`、`HUBWATER/0` 或 `HUBMIS1/0`，并把两项译名参数改为共享的 `config/hub-critter-names.zh-CN.json` 与 `config/hub-item-names.zh-CN.json`。共享配置覆盖这些地图的全部人物、脚本专名、物品和容器库存名称；各区域的实测数量、缺图记录和最终哈希见 `docs/map-rendering.md`。

## ACM 音频转换

`convert-acm` 以只读方式校验并解码 Interplay ACM，输出标准 16 位小端 PCM WAV：

```powershell
python -m fallout1resource convert-acm `
  --input "$PWD\workspace\raw\master\SOUND\SPEECH\HARLD\HROLD1.ACM" `
  --workspace "$PWD\workspace" `
  --execute
```

省略 `--execute` 时只显示计划。默认输出到 `workspace/output/audio/<名称>/`，包括 WAV、记录源文件 SHA-256、采样率、声道、样本数和时长的 JSON，以及 JSON 校验文件。少数双声道 ACM 以不完整声道帧结束；解码样本全部保留，WAV 只补足所需的末尾静音样本，并在元数据中记录数量。

全量音频使用可恢复批处理；DAT 提取物与游戏目录中的松散 `DATA/` 分来源保存：

```powershell
python -m fallout1resource convert-acm-batch `
  --workspace "$PWD\workspace" `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Fallout" `
  --source master --source data `
  --execute
```

复跑会重新解码源文件，并核对转换器版本、元数据、WAV 大小和 SHA-256；只有完全一致的输出才会标记为 `skipped_verified`。过期或被修改的派生物必须显式加入 `--overwrite` 才会替换。

## MVE 动画检查与预览

`convert-mve` 先由工程内解析器校验 MVE 头、分块、操作段、计时、视频和音轨参数。dry-run 不需要外部工具：

```powershell
python -m fallout1resource convert-mve `
  --input "$PWD\workspace\raw\master\ART\CUTS\BOIL3.MVE" `
  --workspace "$PWD\workspace"
```

实际转换需要显式指定审计过的 FFmpeg。工程不搜索 `PATH`，也不经 shell 拼接命令：

```powershell
python -m fallout1resource convert-mve `
  --input "$PWD\workspace\raw\master\ART\CUTS\BOIL3.MVE" `
  --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" `
  --workspace "$PWD\workspace" `
  --execute
```

输出位于 `workspace/output/video/<名称>/`：结构 JSON、全部段 CSV、首帧 PNG、PCM WAV 和 MPEG-4/AAC 预览 MP4。MP4 仅供查看并会重新编码；PNG 和 WAV 是独立的解码抽查产物。JSON 记录 FFmpeg/ffprobe 及同目录运行库的哈希，并保存转换前后的探测结果。预览按原生显示事件恢复可变帧时间戳，避免无新视频数据的停帧被压缩掉。当前验证构建见 `config/ffmpeg-mve.json`。

全部影片可用相同的可恢复批处理转换；执行前应先独立核对 `config/ffmpeg-mve.json` 中的工具哈希：

```powershell
python -m fallout1resource convert-mve-batch `
  --workspace "$PWD\workspace" `
  --source master `
  --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" `
  --execute
```

复跑会校验源、工具链、JSON、CSV、PNG、WAV 和 MP4；只有当前且完整的输出才标记为 `skipped_verified`。派生物被修改或版本过期时需显式加入 `--overwrite`。

## 统一资源索引

`build-index` 读取 inventory、提取清单和各转换器元数据，为每个来源资源生成稳定且不依赖本机路径的 ID，并按不区分大小写的内部路径报告来源冲突：

```powershell
python -m fallout1resource build-index `
  --workspace "$PWD\workspace"
```

默认只显示资源数、提取/转换状态、冲突数和失败数，不创建文件。确认计划后加入 `--execute`，生成 `workspace/index/resources.jsonl`、`derived.jsonl`、`failures.jsonl`、`collisions.csv`、`summary.json` 和组合校验清单。重复执行默认拒绝覆盖；使用 `--execute --overwrite` 时会先完整暂存新索引，再整体替换受管理的索引目录。批次 ID 由全部输入哈希和索引器版本计算，同一输入可重复得到相同输出。当前不会自动裁定松散 `DATA/` 与 DAT 的覆盖关系，冲突来源均保留为待审核状态。

## 测试

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\scripts\check.ps1
```

统一检查会依次验证 Ruff 格式、静态规则和全部 `unittest`。需要自动整理导入和格式时运行 `.\scripts\check.ps1 -Fix`，随后再次运行无参数检查。Ruff 固定为 0.15.22，避免不同机器产生不一致结果。

项目不会附带或分发受版权保护的游戏资源。用户必须自行拥有合法的《辐射 1》副本。

## 许可证

工程代码采用 MIT License。第三方算法说明与外部工具许可分别记录在 `docs/third-party-notices.md`；游戏资源不属于本许可证，也不会随仓库分发。
