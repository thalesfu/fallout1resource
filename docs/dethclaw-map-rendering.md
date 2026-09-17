# DETHCLAW 地图提取与渲染记录

## 资源身份

- 地图文件：`DETHCLAW.MAP`
- 地图显示名：`Lair`
- 当前中文名：`死亡爪的窝`
- 地图编号：37
- 使用楼层：0

该地图是哈勃城任务链使用的独立地图，不是 `HUBOLDTN.MAP` 楼层 1 的盗贼公会区域。

## 地图对象

楼层 0 只有两个 critter 对象：

| 对象 ID | 原型 ID | 脚本 | tile | 坐标 | 说明 |
|---:|---:|---|---:|---|---|
| 1003 | 186 | `DCMutant.int` | 24740 | X 140，Y 123 | 垂死的变种人 |
| 1036 | 51 | `DethClaw.int` | 25741 | X 141，Y 128 | 死亡爪 |

对象 1003 的库存中有两个嵌套物品：原型 196 `Mutant Transmissions` 和原型 100 `Radio`，数量各 1。它们的 tile 都是 `-1`，不具有独立地图坐标，因此不应绘制或标注成地面物品。

## 空图层兼容

`DETHCLAW.MAP` 楼层 0 没有门对象，也没有顶层物品对象。地图渲染器现在允许这两种合法的空图层：

- 门图层为空时，沿用墙壁图层的边界，生成透明门层和未改变的合成图。
- 顶层物品图层为空时，沿用场景物件图层的边界，生成透明物品层；人物库存中的嵌套物品只计入元数据，不参与绘制。
- 空图层仍写出元数据、PNG 和校验文件，以便后续场景物件与人物阶段使用统一流水线。

对应回归测试位于 `tests/test_map_render.py`：

- `test_writes_empty_door_layer_when_map_has_no_doors`
- `test_writes_empty_item_layer_when_map_has_no_top_level_items`

## 实际渲染结果

渲染输出目录为 `workspace/output/maps-rendered/DETHCLAW/`。楼层 0 的验证结果：

| 图层 | 验证对象数 | 可见对象数 |
|---|---:|---:|
| 地面 | 6393 | 6393 |
| 墙壁 | 670 | 399 |
| 门 | 0 | 0 |
| 非门场景物件 | 86 | 67 |
| 顶层物品 | 0 | 0 |
| 人物与生物 | 2 | 2 |

人物标注使用共享配置 `config/hub-critter-names.zh-CN.json`；嵌套物品译名记录在 `config/hub-item-names.zh-CN.json`。最终标注图为 `elevation-0-floor-walls-doors-scenery-items-critters-labeled-zh-CN.png`。

## 知识库图片裁切

这张洞穴地图的人物集中在南端，但从西侧入口到东北房间之间存在一条完整的可探索迷宫。不能使用人物标签包围框裁切，否则会只留下死亡爪附近的小区域。

`scripts/generate_hub_region_docs.py` 因此为 `DETHCLAW` 楼层 0 配置固定画布范围 `(750, 250, 4300, 2200)`。区域总图和人物定位图使用同一范围，完整保留西侧入口、北部通道、东北房间、中央通道和南端死亡爪区域，同时去掉地图画布最外围的大块空白。
