# Fallout 1 世界地图提取与标注

本文记录 `WORLDMAP.FRM` 的转换结果、固定地点坐标、中英文标签来源和标注地图复现方式。面向玩家的知识库只使用最终地图图片；资源路径、坐标公式、哈希和生成步骤统一保留在本仓库。

## 产物

| 产物 | 路径 |
|---|---|
| 原始世界地图 PNG 副本 | `docs/assets/world-map-original.png` |
| 中英文标注 SVG | `docs/assets/world-map-bilingual.svg` |
| 中英文标注 PNG | `docs/assets/world-map-bilingual.png` |
| 地点坐标与汉化名称 | `config/world-map-locations.zh-CN.csv` |
| FRM 转换元数据 | `workspace/output/images/master/ART/INTRFACE/WORLDMAP.frm/WORLDMAP.frm.json` |

## 图像来源

| 项目 | 路径或值 |
|---|---|
| 原始图像 | `workspace/raw/master/ART/INTRFACE/WORLDMAP.FRM` |
| 主调色板 | `workspace/raw/master/COLOR.PAL` |
| FRM 转换输出 | `workspace/output/images/master/ART/INTRFACE/WORLDMAP.frm/WORLDMAP.frm.frames/sequence-00/frame-000.png` |
| 转换器 | `fallout1resource 0.4.0`，FRM 组件版本 2 |
| 图像尺寸 | `1400 × 1500` |

英文地点名称和顺序来自原版 `WMAPLABS.FRM`。中文地点标签来自本机汉化覆盖的 `DATA/ART/INTRFACE/WMAPLABS.FRM`，并以 `DATA/TEXT/ENGLISH/GAME/MAP.MSG` 交叉核对。其中世界地图标签使用“歹徒”，地图描述使用“歹徒营地”；`Boneyard` 的生效汉化是“晒骨场”。

## 固定地点坐标

引擎 `city_location` 表定义 12 个固定地点所在的世界地图网格。世界地图为 `28 × 30` 个 `50 × 50` 像素网格，地点使用所在网格中心：

```text
pixel_x = 50 × grid_column + 25
pixel_y = 50 × grid_row + 25
```

坐标参考：[Fallout Community Edition `worldmap.cc`](https://github.com/alexbatalov/fallout1-ce/blob/main/src/game/worldmap.cc#L353-L366)。计算结果与 `WORLDMAP.FRM` 中 12 个绿色地点圆标的中心逐一吻合。

| 序号 | 英文名称 | 汉化标签 | 网格（列, 行） | 像素中心（x, y） | 发现变量 |
|---:|---|---|---:|---:|---:|
| 0 | Vault 13 | 13号避难所 | `16, 1` | `825, 75` | `67` |
| 1 | Vault 15 | 15号避难所 | `25, 1` | `1275, 75` | `70` |
| 2 | Shady Sands | 沙荫镇 | `21, 1` | `1075, 75` | `68` |
| 3 | Junktown | 迦克镇 | `17, 10` | `875, 525` | `71` |
| 4 | Raiders | 歹徒 | `22, 3` | `1125, 175` | `69` |
| 5 | Necropolis | 大墓地 | `22, 13` | `1125, 675` | `72` |
| 6 | The Hub | 哈勃城 | `17, 14` | `875, 725` | `73` |
| 7 | Brotherhood | 钢铁兄弟会 | `12, 9` | `625, 475` | `74` |
| 8 | Military Base | 军事基地 | `3, 1` | `175, 75` | `78` |
| 9 | The Glow | 闪光之地 | `24, 25` | `1225, 1275` | `76` |
| 10 | Boneyard | 晒骨场 | `15, 18` | `775, 925` | `75` |
| 11 | Cathedral | 大教堂 | `15, 20` | `775, 1025` | `77` |

机器可读版本见 `config/world-map-locations.zh-CN.csv`。

## 复现标注图

SVG 保留原始底图引用、连接线、地点中心和中英文标签。使用 librsvg 2.62.1 从仓库根目录执行：

```powershell
rsvg-convert --width 1400 --height 1500 `
  --output docs/assets/world-map-bilingual.png `
  docs/assets/world-map-bilingual.svg
```

## 校验值

| 文件 | SHA-256 |
|---|---|
| `WORLDMAP.FRM` | `0b22e4fe6c218d7dfb90e4bd6512798c8afcbbee20cfbc3f819f9c2a5debef94` |
| `COLOR.PAL` | `315e06106c42646067117bc84cfdb11c992a5a3a5e058fcaaf24d5c0531a5df9` |
| `docs/assets/world-map-original.png` | `b1f1dcf93944b5a6032d22c698829c53cbd674a928c51b632e9620eca6b4121f` |
| `config/world-map-locations.zh-CN.csv` | `f40a26563d6129adacbe8369e0d8b5d90f3211999bee720334c0d8487539d4b1` |
| `docs/assets/world-map-bilingual.svg` | `16b8d5954f177506c8e42db970a051908a46eeaaaab543347499a887a2d0024e` |
| `docs/assets/world-map-bilingual.png` | `9c67f8817f0857001cd5aac9da0ab74c0295a25af01cda5801ded21093f45bf8` |

同一 SVG 重新渲染所得 PNG 与上述标注 PNG 的 SHA-256 完全一致。
