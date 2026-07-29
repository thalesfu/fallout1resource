# Fallout 1 场景地图渲染设计与实践

## 目标与边界

本阶段把已结构化的 `.MAP` 数据与原始 FRM 合成为可查看的 PNG。首个样板是哈勃旧城区 `HUBOLDTN`：先完成地面，再加入墙壁独立层和地面墙壁合成图；屋顶、场景物件、人物、光照和脚本状态分阶段加入。游戏安装目录、提取后的 `.MAP`、`.FRM`、`.PAL` 和既有 JSON 均作为只读输入，新产物固定写入 `workspace/output/maps-rendered/`。

“完整地图”需要区分三个层次：

1. 地面底图：每个楼层的 100×100 个方形地砖。
2. 静态场景图：地面、屋顶及按深度排序的墙体和物件。
3. 游戏时态图：再考虑门的开关、人物帧、脚本改变和屋顶遮挡。离线渲染首先追求前两层，不执行游戏脚本。

## 数据链路

- `workspace/output/maps/<source>/MAPS/<name>/<name>.json`：楼层、打包地砖、对象和脚本。
- `workspace/raw/master/ART/TILES/TILES.LST`：地砖 FID 低位编号到 FRM 文件名的零基映射。
- `workspace/raw/master/ART/TILES/*.FRM`：调色板索引像素；0 号颜色透明。
- `workspace/raw/master/ART/WALLS/WALLS.LST`：墙壁 FID 低 12 位到 FRM 文件名的零基映射。
- `workspace/raw/master/ART/WALLS/*.FRM`：墙壁各方向、帧和方向锚点偏移。
- `workspace/raw/master/COLOR.PAL`：Fallout 主调色板。

渲染器验证 JSON 结构、数组长度、地砖编号范围和所有输入文件，再进行任何写入。默认 dry-run，只有 `--execute` 才原子生成 PNG、元数据 JSON 和校验文件。

## 坐标与绘制顺序

地图保存 100×100 个方形地砖。对存储索引 `i`：

```text
column = 99 - (i mod 100)
row    = i div 100
screen_x = 48 × column + 32 × row
screen_y = -12 × column + 24 × row
```

该公式对应 Fallout Community Edition 固定提交 `0609bcf` 的 `square_coord`。地面按存储行、再按列递增绘制，与 `square_render_floor` 一致。地砖标志最低位为 1 时跳过；地砖编号取打包值低 12 位。画布边界由实际包含非透明像素的地砖帧计算，最后平移到非负坐标，避免保留无意义的大块透明区域。

参考：[`tile.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/tile.cc)。

墙壁附着在 200×200 六角格上。渲染器先把六角格换算到与地面相同的全局坐标，再按游戏对象锚点定位：

```text
anchor_x = hex_x + 16 + direction_x_offset + object_x
anchor_y = hex_y + 8  + direction_y_offset + object_y
left = anchor_x - frame_width div 2
top  = anchor_y - (frame_height - 1)
```

墙体 FID 类型必须为 3，低 12 位作为 `WALLS.LST` 的零基索引；跳过 `OBJECT_HIDDEN`。绘制顺序复现 `obj_render_pre_roof`：先按六角格编号递增绘制带 `OBJECT_FLAT` 的墙，再按相同顺序绘制普通墙；同格对象保留 MAP 中的先后次序。首轮不模拟玩家周围的半透明“蛋形”遮挡，也不应用环境光，便于单独验证素材、坐标和遮挡。

参考：[`object.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/object.cc)、[`object_types.h`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/object_types.h)。

## HUBOLDTN 首轮验收

- [x] elevation 0 的全部有效地砖均能解析。
- [x] `TILES.LST` 编号没有越界或缺失 FRM。
- [x] 相邻道路、建筑地面没有交错、翻转或周期性错位。
- [x] 输出边缘不裁掉任何非透明像素。
- [x] 重复运行得到相同 PNG 像素与 SHA-256。
- [x] 记录画布尺寸、使用地砖数、唯一地砖数和透明跳过数。

## HUBOLDTN 墙壁验收

- [x] 867 个 elevation 0 墙对象和 374 个 elevation 1 墙对象均完成校验。
- [x] 所有墙体 FID 均能映射到 `WALLS.LST` 和现存 FRM。
- [x] 门洞、墙角和室内隔墙与地面轮廓对齐，没有整层平移或奇偶行错位。
- [x] 平墙先于普通墙绘制，同格重叠顺序稳定。
- [x] 墙壁透明层与合成图使用同一画布原点，可逐像素叠加。
- [x] 重复运行得到相同 PNG 像素与 SHA-256，并记录墙数、唯一素材数和画布范围。

## 后续迭代

墙壁确认后依次增加：屋顶层（整体上移 96 像素）、场景物件与物品、人物、环境光和地图标注。每轮都保留独立图层，避免把坐标问题、素材问题和光照问题混在一次调试中。

## 实践记录

### 2026-07-29：设计基线

确认 72 张 MAP 全部结构化成功；HUBOLDTN 有 elevation 0 和 1，分别各含 10,000 个地砖记录。项目已有只读 FRM/PAL 解析和索引 PNG 编码，可直接复用，无需 Pillow。当前 `output/maps/` 没有合成 PNG，因此本轮新增独立渲染模块，而不修改 MAP 解析结果。

### 2026-07-29：HUBOLDTN 地面首图

新增 `render-map-floor` 命令，保持 dry-run、工作区路径约束、拒绝覆盖和原子写入。渲染直接读取结构化 MAP JSON，按零基地砖 ID 查询 `TILES.LST`；Windows 上通过大小写不敏感索引找到实际大写 FRM 文件，同时拒绝目录穿越、非 FRM 条目、重复文件名和缺失素材。

真实结果：

| 楼层 | 可见地砖 | 全透明占位 | 唯一地砖 | 画布 | 原始坐标原点 | PNG SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| 0 | 7,456 | 2,544 | 148 | 6,656×3,000 | (800, -864) | `89250EB…B11A` |
| 1 | 2,494 | 7,506 | 18 | 2,640×1,668 | (3376, -168) | `3B5C52…C8BC` |

目视检查表明 elevation 0 的荒地、道路、建筑地面和房间轮廓连续，未见隔行翻转、重复错位或裁边；elevation 1 的长通道及房间也连续。不同楼层分别裁切，因此 PNG 左上角不能直接对齐；元数据保留的原始坐标原点用于未来把楼层或对象放回统一坐标系。

首轮发现并固化的经验：

- `TILES.LST` 的数组位置就是 FID 地砖编号；文件内显示的一基行号不能直接用于 FID。
- ID 1 的 `grid000.frm` 是全透明占位。先检查帧像素再计算边界，可把 100×100 理论画布裁到有效区域。
- 地面 FRM 的绘制位置就是 `square_coord` 返回的左上角，不应用 FRM 方向偏移；这与游戏的 `floor_draw` 调用一致。
- 输出必须保留透明背景。当前查看器用黑色显示透明区，但 PNG 中 0 号调色板索引仍带透明信息。

### 2026-07-30：墙壁渲染设计

HUBOLDTN 的结构化对象中共有 1,241 面墙：elevation 0 为 867 面，elevation 1 为 374 面；全部使用 rotation 0、frame 0、对象偏移 `(0, 0)`，没有隐藏墙。213 面底层墙和 56 面上层墙带 `OBJECT_FLAT`，底层另有 7 个同格重叠对象，因此不能只按屏幕纵坐标排序。

FID 的类型字节均为墙体类型 3，低 12 位可以直接零基查询 1,219 项的 `WALLS.LST`，全部引用均找到实际 FRM。实现将输出同尺寸的 `elevation-<n>-walls.png` 与 `elevation-<n>-floor-walls.png`，共享元数据中的原始坐标原点；这样可以分别检查墙体透明层和最终遮挡，同时不改动已经验收的地面 PNG。

### 2026-07-30：HUBOLDTN 墙壁首图

新增 `render-map-walls` 命令，复用地面坐标和调色板，校验对象 FID、`WALLS.LST`、方向、帧、六角格与全部引用 FRM 后，原子写出墙壁透明层、地面墙壁合成图、元数据和校验文件。真实结果：

| 楼层 | 校验墙对象 | 可见墙 | 全透明占位 | 可见唯一墙 FRM | 画布 | 墙层 SHA-256 | 合成图 SHA-256 |
|---|---:|---:|---:|---:|---:|---|---|
| 0 | 867 | 654 | 213 | 102 | 6,656×3,000 | `618FE3…5F6A` | `AA14A7…0EBF` |
| 1 | 374 | 318 | 56 | 36 | 2,640×1,668 | `E45830…4A47` | `15C51B…19B5` |

所有带 `OBJECT_FLAT` 的墙恰好都是全透明占位，仍按对象和素材完整校验，但不会扩大画布或覆盖可见像素。两层墙都没有隐藏对象，墙体边界也没有超出已裁切的地面范围，因此合成图沿用地面画布尺寸与原始坐标原点。

目视检查显示 elevation 0 的门洞、墙角、围栏和室内隔墙贴合道路与房间地面，elevation 1 的长走廊及各房间连续；未见整层平移、奇偶行错位、错误交叠或裁边。覆盖复跑后四张 PNG 的 SHA-256 均保持不变。当前图仍是未应用动态光照、门状态和玩家遮挡的静态资源视图。
