# Fallout 1 MAP/PRO/LST 格式说明

## 编号关系

对象 PID 的最高字节表示原型类型：物品、生物、场景、墙体、地砖或杂项；低 24 位是一基索引，对应各类型 `.LST` 的物理行号。解析器不跳过空行，也不重排列表，并验证该行指向的 PRO 内部 PID 与对象 PID 完全一致。地图脚本的 `script_index` 则是 `SCRIPTS.LST` 的零基索引。

## PRO

PRO 使用大端整数，以 PID、消息编号和 FID 开头。其余字段由 PID 类型决定；物品和场景还包含子类型，并据此读取武器、弹药、容器、门、楼梯、电梯等不同数据。生物原型保存 35 项基础属性、35 项加成、18 项技能及阵营相关字段。解析必须恰好到达文件末尾。

## MAP

版本 19 MAP 的 236 字节头部保存名称、入口位置、变量数量、脚本编号、楼层标志和 44 个保留整数。随后依次是全局变量、局部变量、每个存在楼层的 10,000 个打包地砖、五类脚本和对象树。

地砖低 16 位表示地面，顶部 16 位表示屋顶；各自低 12 位是地砖原型编号，高 4 位是标志。对象先保存 18 个基础整数，再保存背包信息和按 PRO 类型决定的更新数据；背包对象以数量加嵌套对象的形式递归出现。

## 交叉核验

- [Community Edition `map.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/map.cc)：地图头、变量、楼层和地砖读取。
- [Community Edition `scripts.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/scripts.cc)：五类脚本及 16 项 extent 结构。
- [Community Edition `object.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/object.cc)：对象与递归背包读取。
- [Community Edition `proto.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/proto.cc)：LST/PID 解析、PRO 字段和对象更新数据。

本项目仅重新实现只读解析和结构化输出，不加载脚本、不执行地图逻辑，也不调用游戏引擎。
