# MAP/PRO/LST 结构化阶段结果

关联：[[资源提取设计方案]] · [[工作计划 Checklist]] · [[INT 反汇编阶段结果]]

## 已实现能力

`fallout1resource` 已增加 `convert-map` 命令。它以只读方式解析版本 19 MAP 的 236 字节文件头、全局与局部变量、最多三层的 100×100 地砖、五类脚本、顶层对象和递归背包对象，并要求解析位置准确到达文件末尾。

对象 PID 的最高字节确定原型类别，低 24 位作为一基行号连接对应 LST；工具随后加载该行指向的 PRO，并验证 PRO 内部 PID 完全一致。物品和场景对象的可变更新数据由 PRO 子类型决定，不通过猜测跳过字节。地图脚本的 `script_index` 则按零基位置连接 `SCRIPTS.LST`。

输出 JSON 保留六类 LST 的每一条原始行及顺序、全部打包地砖值和拆分后的地面/屋顶编号、脚本记录、对象层级及地图实际引用的 PRO 全字段；CSV 提供便于筛选的扁平对象清单。

## 全量 PRO 格式验证

本地提取的 4,306 个 PRO 全部严格解析成功，格式错误为 0：

| 类别 | 数量 |
|---|---:|
| 生物 | 312 |
| 物品 | 242 |
| 场景 | 908 |
| 墙体 | 1,176 |
| 地砖 | 1,622 |
| 杂项 | 46 |

## HUBOLDTN.MAP 验证

地图源 SHA-256 为 `7E17DAB65F728AA5979BE34767001EACFCD634A962293BAA317D220632334810`。解析结果如下：

- 存在楼层：0、1；全局变量 10 项，局部变量 0 项。
- 地图脚本 66 个；顶层对象 2,406 个，背包对象 115 个。
- 2,521 个对象全部成功连接原型，引用 301 个唯一 PRO。
- 对象类别：物品 133、杂项 739、墙体 1,241、场景 374、生物 34。
- JSON 为 5,085,636 字节，CSV 为 206,977 字节；JSON 侧车哈希验证一致。

## 哈罗德链路

哈罗德对象位于地图楼层 0、格位 `22942`，按 200×200 网格拆分为坐标 `(142, 114)`，朝向值为 2。完整编号关系为：

`HUBOLDTN.MAP 对象 1633` → `PID 0x0100009D` → `CRITTERS.LST 第 157 行` → `00000157.pro` → `SCRIPTS.LST 第 45 行` → `Harold.int`

哈罗德 PRO 的 SHA-256 为 `78DE41F6D107821261BCFC1037B5C0FA0C1B74119B995EE43E9DDDF919F99EF5`；`SCRIPTS.LST` 的 SHA-256 为 `CA1E7D9E0D8B26F0031F6322687CDD73D7100B879564DAB6ECC0226C9247CAB3`。

## 输出与安全

- `workspace/output/maps/master/MAPS/HUBOLDTN/HUBOLDTN.json`
- `workspace/output/maps/master/MAPS/HUBOLDTN/HUBOLDTN.objects.csv`
- `workspace/output/maps/master/MAPS/HUBOLDTN/HUBOLDTN.json.sha256`

早期样本目录已在全量结果验证同源哈希后移到 `workspace/archive/pre-full-batch/maps/HUBOLDTN/`；未删除且可恢复。

79 项自动测试通过；另有 5 项符号链接逃逸测试因当前 Windows 账户没有创建符号链接权限而跳过。测试覆盖六类 PRO、LST 顺序、MAP 版本与截断、脚本类型、对象与背包、PID/LST/PRO 不一致、绝对路径、父目录穿越、符号链接逃逸、覆盖拒绝及原子覆盖。

本阶段代码已提交为 `d21dce6 feat(map): link maps to prototypes and lists`。提交仅保存在本地，尚未推送；4,306 个 PRO、地图和派生数据均位于 Git 忽略的工作区，没有进入提交。
