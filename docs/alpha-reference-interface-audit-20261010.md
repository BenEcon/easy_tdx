# Alpha101 / GTJA191 官方模块接口与差异复核

本记录是来源与依赖盘点，不是将参考实现认证为原公式，更不是宣布本 App 已实现这些因子。

**阶段说明：** 下文及生成 JSON 的 `not_implemented`／0 计数是第十九批接口核查时的冻结快照，不是实时目录。第二十批已独立实现 43 个 GTJA 内核；当前编号、口径和证据见 `gtja191-foundation-20261010.md` 与 `gtja-factor-evidence.json`。其余接口仍不可据此直接计为实现。

## 固定来源与许可

- DolphinDB 官方 `DolphinDBModules` 固定提交 `43ace2cc4b81d048864ec2e40c25728d5d464e05`（2025-12-30）。
- [仓库 LICENSE](https://github.com/dolphindb/DolphinDBModules/blob/43ace2cc4b81d048864ec2e40c25728d5d464e05/LICENSE) 是 Apache-2.0；SHA-256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`。本次列举未发现另附 NOTICE 文件；两个模块头署名 DolphinDB。
- [Alpha101 模块](https://github.com/dolphindb/DolphinDBModules/blob/43ace2cc4b81d048864ec2e40c25728d5d464e05/wq101alpha/src/wq101alpha.dos) SHA-256 `ae7a52198542aa879d00d7f97a6281e036af116fcbb6c82fa95308021235f64a`。
- [GTJA191 模块](https://github.com/dolphindb/DolphinDBModules/blob/43ace2cc4b81d048864ec2e40c25728d5d464e05/gtja191Alpha/src/gtja191Alpha.dos) SHA-256 `e3d93adcdacff263795b8f0b97de1b806ce3666b118f7819af59d9ef5ff98543`。

这是较原专有参考仓库更明确的代码许可来源，但不能将其解释为原始论文／第三方所有内容的统一再许可。本批没有移植 DolphinDB 因子代码、公式表或打包其源码；本地只读参考 checkout 用于接口事实核查。后续若适配其代码，须随包保留许可、归属与修改声明，并逐项核对原始公式差异。原 Alpha101 权利声明记录保留，不自行覆盖。

## 可重建清单

`scripts/audit_alpha_reference.py` 不导入或执行第三方代码，只读取已校验 SHA 的源文件，抽取接口编号、输入、行号、截面算子和依赖警告。缺编号、重号、超出编号、源文件或许可变化时停止。

生成文件：`output/factor-system-20261010/alpha-reference-interface-audit.json`，SHA-256 `499735db5fb1b773ebad2e9f006e87b94e956bd8ef99780185cd17c154f2a6aa`。每项保留 `formula_verified=false`、`app_status=not_implemented`、`count_as_available=false`。

| 参考库 | 接口数 | 含截面算子 | 声明行业字段 | 声明 VWAP | 声明市值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Alpha101 | 101 | 81 | 18 | 43 | 1 |
| GTJA191 | 191 | 63 | 0 | 40 | 0 |

这些是固定参考模块的签名／代码事实，不等于标准因子最终依赖，不计入 App 登记或实现数。单纯时间序列的因子也可能使用面板载体，不能据输入形状误判其必须截面排名。

## 已发现不能直接照搬的差异

1. **Alpha101 窗口取整**：原始来源记录的向下取整与参考模块不一致。例如 96 号相关窗口约 3.84，模块用 4；99 号约 19.90，模块用 20。逐项实现时必须选择并披露原始定义，不能直接继承这些整数。
2. **Alpha101 adv**：原始论文定义平均美元成交额；参考模块多处对 `vol` 求均值。需要进一步核实其实际输入语义；本 App 不把已确认股数的 volume 冒充金额。
3. **历史行业**：模块说明忽略行业分类层级；部分函数直接取 `indclass.row(0)`。这不能用作本 App 的历史 PIT 行业中性化，sector／industry／subindustry 也不能混为同一分类。
4. **GTJA191 第 30 项**：简版字段表不充分。实际签名需要 `MKT`、`SMB`、`HML` 等输入，并涉及回归和加权；只有指数收盘价不能实现此因子。本 App 不以指数或当前市值分组代替风险因子历史序列。
5. **GTJA 平滑、排名、累计**：官方 README 明确作了部分解释性调整，其 SMA 文本中写的 n/m 也需与原始递归定义和实现核查。RANK 百分数、并列值、TSRANK、SUMAC 和滚动初值不能因“官方模块”字样而免除独立验证。

## 后续实施顺序

1. 已先补统一引擎的真正整池执行，不另建因子平台。
2. 依这份逐项索引回到原始论文／报告，冻结可独立核验的价量公式、窗口／排名／平滑约定及授权来源。
3. 按数据就绪分批实现全部可支持公式并接入目录、任务与原档；需要 VWAP／行业／市值／基准／风险因子的项分别保留门槛，不整库假报可用。
4. Alpha101、GTJA191 本轮 App 登记、实现、验收、部署仍为 0；测试合成因子仅用于引擎，不发布到目录。
