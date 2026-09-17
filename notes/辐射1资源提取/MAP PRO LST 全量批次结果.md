# MAP/PRO/LST 全量批次结果

关联：[[MAP PRO LST 结构化阶段结果]] · [[工作计划 Checklist]] · [[经验总结与待决策]]

## 已验证结论

从 `MASTER.DAT` 提取的 72 个 MAP 全部严格解析并转换成功，失败为 0；松散 `DATA/` 中没有非存档 MAP、PRO 或 LST 覆盖。依赖集合包含 4,306 个 PRO 和 inventory 中全部 23 个 LST，其中 `SCRIPTS/SCRIPTS.LST` 同时承担脚本编号连接。

地图结果汇总：

| 指标 | 数量 |
|---|---:|
| MAP | 72 |
| 对象（含递归背包） | 132,961 |
| 活动脚本记录 | 2,146 |
| 按地图去重的原型引用 | 9,217 |
| 缺失 PID / 未知子类型 / 结构失败 | 0 |

输出为 72 组 JSON、对象 CSV 与校验文件，共 216 个文件、297,140,345 字节。首次转换耗时 11.636 秒；断点复跑耗时 6.379 秒，72 项全部验证后跳过：

- 首次：`workspace/manifests/batch-map-20260728T134542121930Z.json`
- 复跑：`workspace/manifests/batch-map-20260728T134607202678Z.json`

## 依赖与恢复语义

每次复跑都会重新解析 MAP，并核对源地图、六类原型 LST、`SCRIPTS.LST`、本地图实际引用的所有 PRO、对象 CSV 和 JSON 校验和。任一依赖或派生文件变化都会标为 stale；只有显式 `--overwrite` 才允许恢复。

早期 `HUBOLDTN` 样本与新全量产物的地图源 SHA-256 相同，已移至 `workspace/archive/pre-full-batch/maps/HUBOLDTN/`，避免统一索引重复认领。源游戏目录未写入，游戏资源和派生物均未加入 Git。

批处理实现已提交为 `a378c51 feat(map): add recoverable full conversion`。
