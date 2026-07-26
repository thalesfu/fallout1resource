# Fallout 1 Resource

《辐射 1》资源研究工具。当前里程碑只读取 Fallout 1 DAT1 档案目录和 `DATA/` 松散文件，生成可追溯的 JSON/CSV 清单；不会解包、修改或写回游戏安装目录。

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

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

项目不会附带或分发受版权保护的游戏资源。用户必须自行拥有合法的《辐射 1》副本。
