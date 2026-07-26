# Fallout 1 Resource

《辐射 1》资源研究工具。当前可盘点 Fallout 1 DAT1 档案与 `DATA/` 松散文件、安全提取选定资源，并将 `.MSG` 转换为可追溯的 UTF-8 JSON/CSV；不会修改或写回游戏安装目录。

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

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

项目不会附带或分发受版权保护的游戏资源。用户必须自行拥有合法的《辐射 1》副本。
