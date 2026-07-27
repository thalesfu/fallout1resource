# Fallout 1 Resource

《辐射 1》资源研究工具。当前可盘点 Fallout 1 DAT1 档案与 `DATA/` 松散文件、安全提取选定资源，转换 `.MSG`、反汇编 `.INT`，并使用 `.PAL` 将 `.FRM` 导出为可追溯的 PNG；不会修改或写回游戏安装目录。

## 安全边界

- 游戏安装目录始终作为只读输入。
- 所有本地清单、缓存和后续提取物只能写入 `workspace/`。
- `workspace/`、DAT、游戏资源和第三方二进制不会提交到 Git。
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

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

项目不会附带或分发受版权保护的游戏资源。用户必须自行拥有合法的《辐射 1》副本。
