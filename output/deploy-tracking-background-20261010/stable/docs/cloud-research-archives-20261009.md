# 跨设备研究保存：正式应用接入与验收

## 深层图表字段校验（2026-10-09，本地，未部署）

- 新增 archive-chart-validation.ts，校验图表和审核实际消费的笔、线段、特征、中枢、盘整、背离、相关事件、失效依据和买卖点字段；返回精确错误路径，不修复或覆盖原文、不重新计算。未消费的未知结构原样保留，不宣称涵盖未来所有字段。
- 22 个冻结案例完成真实输出检查：699 笔、67 线段、10 中枢、1148 背离、7 买卖点、11517 诊断、3805 对照；原始输入不变。archive-chart-real-validation.log 保留结果，不替代原执行版本的逐根验证。
- WebKit 正式应用临时数据库核验 300750 原档及两个损坏副本。相关事件 signal_date 与未完成线段 feature.low 错类型准确显示路径，原值可读，坏图不渲染、合法原档仍能重新打开；零行情／分析请求和 pageerror。该浏览器案例没有中枢正例，中枢正例仅在上述数据校验矩阵。
- 实际弹窗验收发现 MacSelect Teleport 到 body 会落在原生 dialog 的 inert 区域。改用原控件 DOM 内的 manual popover，保持 top-layer 显示、避免动态换父节点的卸载错误。最终 archive-chart-browser-popover.log 通过；最初两次失败日志保留。
- 1440／390／320px 原档弹窗在视口内且页面不横溢；桌面和 320px 截图已查看。单元测试新增合法／旧档及 30 种损坏字段覆盖；本轮最终前端 310+28 项通过，包含后续用户活动测试。
- 旧档批量迁移、显式重算／版本对照、生产生命周期及发布门禁仍待完成，原全站十阶段范围没有缩减。

## 日期、类型与多周期原档兼容性（2026-10-09，本地完成本轮验收，未部署）

- 新增共用 `archive-data-validation.ts`：校验真实日历日期、时间/时区范围、严格递增的实际时刻、OHLC 与可选成交量/金额/收盘标记类型。无时区按交易所北京时间解释；显式时区保留原文但按实际时刻比较，不误拒合法混合表示，也不允许同一时刻因字符串不同重复。后端 `research_archive.py` 采用相同边界；无效新上传拒绝写入，不清理或覆写既有存档。
- `archive-study-preview.ts` 校验概览表实际消费的字段，坏周期保留为明确错误行，而非静默筛掉；未知/非对象记录仍保留原始展开入口，重复周期全部标为歧义、不挑选其中一条充当有效结果。原有 error 记录只投影安全表格字段，原文不变；不补造数值、修复价格类型或重新运行研究。此项是概览渲染契约，不冒充所有深层缠论结构均已验证。
- 导入确认前提示字段不完整的记录数，表格显示具体字段原因；旧档显示错误不再配上“本周期未得出结论”的误导性文案。frontend-skill 继续采用单张轻量表格与原文按需展开，无新增卡片矩阵；有效周期与坏周期共存，数值显示两位但原档保存完整精度。
- 云目录/详情响应同样拒绝无效日历时间和数组冒充 kind/state；笔/背离方向拒绝数组隐式转换。新增纯测试覆盖类型混淆、原始失败行、重复/未知周期、空值/零值、未知字段及不变性；行情校验直接读取既有冻结夹具，未改夹具或数值规则。
- `archive-study-real-output.json` 来自 22 个经过原清单文件哈希/行情哈希核验的案例，通过正式 `observations(StudyRequest)` 实际计算生成，无网络取数。`verify_archive_study_matrix.mjs` 逐一检查概览字段、行完整保留、六列可读、不改变原始对象；`archive-study-real-validation.log` 为 22 成功、0 来源错误。这不是新的逐根/全部市场验收，原 10034 前缀报告及原执行哈希保持不变。
- `frontend-archive-validation-verified.log`：**304 逻辑 + 28 评级通过**；`build-archive-validation-verified.log` 类型检查/构建通过，既有 ECharts 大块警告仍在。`archive-validation-regression.log`：**192 后端相关测试通过**，1 条既有 Starlette 警告；CI Ruff 检查/486 文件格式通过，严格 Mypy **292 源文件通过**（`mypy-archive-validation-verified.log`）。不是全库最终回归或生产验收。
- 正式应用、临时 SQLite、实际 Cookie WebKit 使用明确合成的三周期备份：日线 price 错类型保留原文，周线原取数失败不改写，30 分钟有效数据独立显示。确认前无写入、确认后恰一份；未知字段/精度原样保存；恶意形状的 HTML 字符串按文本显示，没有生成 img 或触发弹窗。`archive-study-browser-validation-results.log` 返回 3 行/2 条明确错误、零 pageerror/行情或分析请求/脚本弹窗。
- 1440/390/320px 文档宽度各等于视口，弹窗在视口内，表格通过键盘左右键内部横滚。截图 `output/playwright/archive-study-validation-{1440,390,320}.png` 已检查桌面及 320px。不是实体 iPhone/Safari 或线上验收。
- 初次本机浏览器加载期间重构建使旧 CSS 哈希失效，重载稳定构建后复验；此为 QA 构建/加载并发，不把历史控制台错误说成未发生。第一版测试脚本收起动态详情后旧 nth 定位超时，第二版因旧“查看原档”按钮已存在而提前读取上传计数；均修正测试等待/定位，保留失败日志，未为迎合测试改变存储逻辑。最终按正式 PUT 完成及目录同步等待后通过。
- 待继续：复杂图表嵌套结构的全消费校验、IndexedDB 批量迁移、显式重算/版本对照、账户与备份生命周期、生产反代/大载荷和新版 Linux 发布门禁。原十阶段完整范围保留；严格笔、背离、MACD、M1 与高层递归算法未修改，本轮未部署。
- 本轮恢复包 `output/platform-optimization-20261009/source-after-archive-validation.tar.gz`，SHA-256 `8e6dc8fc7f50bf6946036e26ab923764e011581e26cab05117b423888aa2d6b2`。包含源码/测试/文档/构建配置、完成前缀报告及本轮合成 QA 脚本，不含生产数据库/凭证/依赖目录；归档后仅追加本条。已关闭 WebKit tdx-archive-validation，并核对 PID 73828 后 SIGTERM 本机服务，session 41012 正常 shutdown/退出 143；仅临时 QA 账户及合成档案随隔离环境清理，用户数据未操作。

## 备份导入验收与解除源码冻结（2026-10-09）

- 新增本地图表 schema 1、多周期研究 v2 及完整云原档导入。确认前只读校验/预览，取消不写入；确认后生成新云 ID。剥离旧浏览器 owner 绑定，保留原版本、备注、原始精度及未知规则字段，不重算旧档或伪造缺失的冻结指标。
- 断线重试沿用同一个 ID；切换账户拒绝旧页面导入。读取成功而目录刷新失败明确区分，不诱使重复创建。单文件 25 MiB 在读取前拦截；复杂结构的完整渲染校验及直接批量迁移 IndexedDB 仍待实现。
- `frontend-archive-import.log`：297 逻辑 + 28 评级通过；`build-archive-import.log` 类型检查/构建通过，保留既有 ECharts 大块警告。浏览器最终日志 `import-ui-{confirm-final,retry-final,export-account,layout}.log` 覆盖确认/取消无写入、原档精度、同 ID 断线重试、云导出往返、账户切换 409、1440/390/320px 无溢出与零 pageerror。使用隔离 QA 身份及合成备份，不是生产账户验收；早期脚本等待和文件选择器队列失败日志保留，未当作成功。
- 原 verifier 句柄 25859/PID 29389 消失后，核验无进程且哈希未变，使用同一报告 `--resume` 续跑 session 39041。最终该进程已退出，报告于 **2026-10-09 22:09:16 +08:00** 完成；本轮独立检查清单、全部源文件哈希、22 案例逐个状态、每案连续前缀序号，共 **10034/10034**，无 failure。
- 完成报告 `real-prefix-matrix.json` SHA-256：`f5a8b974c628f879d02b307dc2d2e8ea1f416d4901d6573c56465833a31f4224`。对应 execution `research-execution-v1:9fb5d4f8a983ca93862a7850f1492072804b2e7102043dcbf79a17c9bac0333a`；manifest `29bb2e705a8a4d25844eceb5e54b9cd5cc13dbefdd24e098a2a1f113be82671c`；verifier `57974aca9546e9087ce129a98c04885f276129f97154f2c5fbaa61c8eb4e82dd`；loader `7036be78faf4e1e8c8839314019198f01f290cab9c4c58b903279cdb706ea965`。
- 验证范围是这些冻结行情每个前缀的完整回放与污染未来后缀的结果相等、事件索引不越界；不是所有标的/历史数据修订/原著解释/递归合法分支的穷举证明。现在解除正式 Python 源码冻结；后续新增 Web 后端会改变执行哈希，不将旧报告冒充新版本全量验收。

## 当前状态

最新恢复点：`output/platform-optimization-20261009/source-after-archive-integration.tar.gz`，SHA-256 `569018f0cccce8b275f7d57a01de625294bebb9150c4970f1940cfa16f3049c3`。包含源码/测试/配置/文档、合成 QA 和完成的前缀报告，不含生产数据库或生产凭证；归档后仅追加此记录。WebKit `tdx-formal-archive` 已关闭，QA PID 61229 核验命令后 SIGTERM，session 32608 正常 shutdown/退出 143；没有遗留本轮测试服务或修改生产数据。

第八阶段进行中，**网页和正式应用后端均已本地接入，未部署生产服务器**。此前为保持长时回归源码冻结，将实现暂存在下列目录；10034 前缀验收完成后，已复制到 `src/easy_tdx/web/research_archive.py` 与 `routers/research_archive.py`，原暂存文件保留作历史恢复材料，不是运行时导入来源：

`output/platform-optimization-20261009/cloud-snapshot-stage/`

其中 `research_archive.py` 为存储层，`research_archive_router.py` 为依赖注入式 HTTP 适配器，另有存储及 HTTP 测试。运行中的 Python 源、冻结行情、清单和验证器没有改动。不可将本阶段测试通过描述为云同步已经上线。

## 已实现契约

- 独立 SQLite 数据库，不占用账户偏好的 64KB 配额。每次写入、配额预占、版本递增及审计使用同一 `BEGIN IMMEDIATE` 事务，跨进程有效。
- 不可变 JSON 原始结果存档，支持图表快照 schema 1 及多周期研究 `chanlun-research-snapshot-v2`。保留价格精度、原始行情、元信息、结果及未知版本字段，不重新计算或拼接最新行情。
- 存档明确标记 `client_archive_not_server_verified`；存储完整性哈希不等于行情真实性或算法结果已被服务端验证。客户端字段不决定访问权限。
- 使用账户与 UUID 联合身份；同 UUID 在不同账户下独立。管理角色不取得别人存档读取/修改权，已撤销的真实会话不能再调用接口。
- 创建可幂等重试；相同 ID 的不同原始内容返回 409。编辑只更新名称/备注，必须提交当前整数 revision；旧设备版本冲突 409，不覆盖他人修改。
- 删除先进入回收站，可以查看、恢复；回收站仍占容量。永久删除只允许作用于回收站，删除内容但保留幂等墓碑，防止迟到的创建请求把旧资料复活。
- 单份 25MiB，每账户 128MiB/100 份；实例总内容 1GiB。墓碑记录另受每账户 1000、实例 10000 条限制，拒绝静默淘汰；账户列表返回内容与记录配额，实例其他账户用量不泄漏。
- 列表返回同一读事务下的目录、集合 revision 和配额，不读取全部 JSON 正文。详情验证 SHA-256 后才返回，损坏报 503。
- 数据库版本不认识时拒绝打开，不擅自降级。事务连接关闭；审计仅记账户/存档 ID、操作、版本、时刻，最多 5000 条，不记录名称、备注、行情或凭证。
- HTTP：GET `/research/archives` 目录、GET `/{id}` 详情、PUT `/{id}` 创建、POST `/{id}/actions` 编辑/回收/恢复/永久删除。owner 不可从请求顶层注入，写操作仍经过同源限制，成功响应 no-store，单记录响应带 revision ETag。

## 验收

- `cloud-archive-final.log`：44 项通过（1 条既有 Starlette 弃用警告）。
- 真实 spawn 进程测试：重复创建只占一份；同版本编辑恰好一方成功；最后一个配额并发提交恰好一方成功。
- Cookie 会话/撤销采用实际 AccountStore；全部数据库在 pytest 临时目录。跨账户/管理员访问与不存在 ID 返回相同 404；拒绝跨域写入、owner 注入、布尔或字符串 revision。
- 内容保真、非有限价格、无效类型/Unicode、OHLC/日期/重复周期、容量与 UTF-8 计费、回收站/永久删除/迟到重试、未知数据库版本、哈希损坏及 SQLite backup 恢复均有测试。
- `cloud-archive-ruff.log`：CI 固定 Ruff 0.11.11 通过；`cloud-archive-mypy.log`：Mypy 2.1.0 严格检查两个源码文件通过。未放宽项目配置。
- 初次 HTTP 回归错误调用不存在的会话撤销方法，导致 1 项失败；修正为实际 `invalidate_user_sessions` 后复验通过，保留 `cloud-archive-api.log`。初版格式失败也保留，已整理后复验。

## 必须继续完成的集成与验收

1. 逐根验证结束后，将暂存实现及测试移入正式源码/测试目录；替换临时模块导入，挂入现有受保护路由与资源准入，不绕过认证。
2. 正式 HTTP 中间件当前总体 8MiB，本阶段测试应用显式使用 26MiB。正式接入须只对云存档上传端点设置明确的 26MiB 传输限制，保留其他端点原上限；补无 Content-Length、分块、并发、大载荷实际 HTTP 验证。
3. 完善与渲染器一致的完整结构验证。暂存存储已做基础格式/行情检查，但不能声称任意上传文件都可以安全完整渲染。图表验证现已扩至 12 周期/每周期 8000 根、支持 120 分钟并拒绝重复周期；当前失败回退原文，不静默截断。复杂递归字段、各版本格式仍待完整验证。
4. 图表与多周期研究已接入可选云保存、目录/回收站/导出/备注冲突及账户页独立目录；本地副本独立保留。原行情、分析结果、参数和来源随完整原档保存；新图表快照已冻结 MA/技术指标逐根数值（见下节），旧档缺少这些字段时明确披露当前版本计算，不为旧档补造原版结果。继续补全版本比较/显式重算入口及研究表格与图表之间的完整源数据衔接。
5. 已有隔离 WebKit 的双设备冲突、账户变化拒写、删除恢复、断线同 ID 重试及窄屏验收（详见下方）。仍需大载荷与容量 UI、实际 Cookie 浏览器双会话、旧本地档案迁移、版本差异及实体手机；不以隔离 QA 替代生产验收。
6. 数据生命周期（账户删除/孤立档案、容量管理）、生产数据库备份/迁移/回滚门禁及版本发布。原有十项总目标和其他未完成项保持不变。

本轮最新读取逐根验收报告为 19 个案例已通过、8334 个前缀已完成，整体 running；不是最终结果。

暂存恢复包 `output/platform-optimization-20261009/cloud-archive-stage.tar.gz`，SHA-256 `0ed614bb41d2bfe8c3cc29ca02d1329cf22639c02f21d734d9bf5e9df8f510fd`。归档后仅追加本记录。`cloud-archive-frozen-identity.log` 已核对实际当前 Python 执行哈希仍与运行中验收报告一致。

## 网页接入与异常响应复验（2026-10-09）

- `CloudResearchArchives` 在展开时加载目录，不增加首屏行情请求；图表和多周期研究分别保存完整捕获内容，个人账户可直接查看，换设备不必先重新分析股票。采用 frontend-skill 的轻量列表、统一展开标题和按需原档对话框；没有新建装饰性卡片网格。
- 保存捕获一次不可变请求体和 UUID；服务器已保存但响应断线时，同 ID 重试不重复占配额。不自动重试覆盖编辑冲突，保留本机草稿；刷新目录不悄悄合并或覆盖它。
- `X-Research-Owner` 只约束预期账户，不授予权限；请求 Cookie 身份不同返回 409。前端拒绝账户切换后的迟到成功/错误，清理旧目录和对话框。新增后端测试后 `cloud-ui-api-final.log` 45 项通过，Ruff/Mypy 通过。
- 目录及详情增加运行时契约检查：缺数组、非法字段、重复身份、配额数量不符、详情缺正文均明确报错，保留已读取记录；未知正文版本字段原样保留。任务列表也校验实际响应，避免异常 QA 数据让账户页渲染失败。
- `frontend-cloud-responses.log`：288 项逻辑 + 28 项评级通过。`build-cloud-final.log`：类型检查及构建通过；保留 ECharts 679KB 既有分块警告。未改算法规则及 Python 源码。
- WebKit 的 `cloud-ui-save-chart.log` / `cloud-ui-save-study.log`：保存并重新查看双图与五周期真实冻结行情的研究结果；`cloud-ui-two-devices.log`：两个浏览器上下文竞争编辑，后提交旧 revision 得到 409，旧草稿仍保留。
- `cloud-ui-trash-retry.log` / `cloud-ui-purge-layout.log`：移回收站、恢复、显式二次确认永久删除；一次保存成功后人为断开响应，重试后数量只增加一份。永久删除仅操作该实验临时多建的 QA 档案，原两份测试档案保留；未触及用户数据。
- `cloud-ui-account-switch.log`：模拟登录账户变化，旧页面写入 409，新账户空目录，恢复原账户可查看。此处浏览器使用明确 QA 身份切换，不是真实 Cookie 登录；真实 Cookie 所有权和撤销由 HTTP 测试覆盖。
- `cloud-ui-account-final.log`：账户页查看已存多周期原档，行情/replay/observations 请求数为零。原档没有重新拉行情或重新调用缠论分析，但前端技术指标重算边界如上。
- 初次账户页出现 `tasks.value.length` 渲染异常：QA 回退路由返回 `{data:[],count:0}`，不符合任务接口契约。未将此错误掩盖为生产故障；修复前端校验后，`cloud-ui-response-validation.log` 明确错误响应有提示、云目录坏响应保留两份旧档，随后显式模拟正确空任务响应可恢复。最终测试监听 `pageerror` 为零；历史控制台错误及故障注入日志不删除，不称全部历史运行零错误。
- `cloud-ui-final-layout.log`：1440/390/320px 文档宽度等于视口、无未捕获异常，截图 `output/playwright/cloud-account-final-320.png`。此前图表/研究预览截图亦已检查，手机对话框居中并在内部滚动。
- 最新实查长验证为 running、20 案例通过、9134/10034 个前缀。当前 Python 执行哈希仍为 `research-execution-v1:9fb5d4f8a983ca93862a7850f1492072804b2e7102043dcbf79a17c9bac0333a`，没有移动暂存后端或重启验证器。本阶段和完整十项范围均未宣称完成。
- 恢复包 `output/platform-optimization-20261009/source-after-cloud-ui.tar.gz`，SHA-256 `f1109c1c198104dc313327ff36cb1ae2e2fa3f36a90a6625f15599640622970c`。含源码/测试/文档/配置和独立暂存模块，不含账户数据库或凭证；归档后仅追加本记录。验收浏览器 tdx-cloud 已关闭，QA PID 28438 经命令核对后 SIGTERM 正常停止；原长时验收继续运行。

## 图表指标冻结（2026-10-09，本地实现，未部署）

- `frozen-chart-indicators.ts` 保存对应 K 线日期、全部可选 MA 的原始数值与初始开关、每项技术指标的实际参数、逐列未舍入数值、面板归属/范围/参考线。成交量与 MAVOL5/10 同样冻结；MACD 直接保存结构分析实际使用的 DIF/DEA/HIST，不以另一组默认参数补算。
- 从当前图表的完整指标状态捕获，不另发计算请求。指标仍在加载、出错、行情/配置发生变化而旧计算尚未失效完成时拒绝保存；主图及对照图逐一校验，不让一图覆盖另一图。
- 新本地/云图表原档直接绘制保存的序列，不调用 `researchIndicatorRows` 或 `buildIndicatorSeries` 重算数值；图例/手机 MA 显隐仅改变当前阅读，不修改原档。参数编辑隐藏，不混入当前账户后来新增的指标。
- 严格验证逐根日期对应、序列长度、数值、MA 周期唯一、面板/列类型及边界；无效冻结数据不静默降级为重算。只接受声明式数据，不接收任意 ECharts 配置或函数；导入文本进入 HTML 提示框前统一转义。复杂结构数据的其他渲染验证仍待继续，不能据此声称任意外部档案完全可信。
- 此阶段旧图表未含冻结字段仍可读取，曾明确提示部分指标使用当前算法；后续正式接入验收发现仍会联网补算，现已修正，以下节的“旧档只读”行为为准。多周期研究表格保留保存时结果，不属于本节图表序列捕获；直接批量迁移及统一重算比较仍未完成。

## 正式路由、上传保护与旧档只读（2026-10-09，本地验收）

- 正式 `_create_app` 在原身份/资源保护下挂载云存档 API，存储位于实际账户库旁的 `research_archives.db`。临时/打包/部署目录均从实际账户库解析；没有修改生产账户数据库或启动行情网络。
- 仅规范 UUID 的 `PUT /api/v1/research/archives/{id}` 放行 26 MiB 请求信封，存档正文仍限制 25 MiB。其他接口不扩大原 8 MiB 上限；身份、预期账户、来源及并发容量在读取上传正文前检查。上传途中撤销登录，在正式路由写入前重新鉴权。
- 上传共享租约独立限额为账户 1、实例 4，SQLite 原子预留，正文总接收时间 30 秒。分块超限、断开、超时、取消、异常均释放；预留尚未完成时取消，迟到的租约亦会释放。已开始的同步 SQLite 操作持有额外引用，HTTP 等待者离开不会提前释放上传/数据名额；响应遗失可同 ID 重试，不把取消承诺为数据库回滚。
- `archive-formal-regression.log`：**190 项通过**，涵盖正式应用路由、真实 Cookie、存储/并发、来源与资源门禁、账户、安全审计、来源/时间口径、回放和任务控制；既有 Starlette 警告 1 条。专项 `archive-formal-final.log` 91 项通过。最初两次失败来自测试误认创建响应含正文及误放置测试尾行，已修正并保留日志，没有据此更改 API 语义。
- CI 固定 Ruff 0.11.11 检查/486 文件格式通过；严格无增量 Mypy 2.1.0 **292 源文件通过**（`mypy-archive-formal-final.log`）。初次 Scope Any 返回 bool 类型问题已显式检查字符串修正。当前 execution 为 `research-execution-v1:88d44e51863dc8ba95844d50943bfd1748205e90ae48bc8501c5c9478741235d`；与前缀恢复包逐文件比对，修改仅为 3 个 Web 边界文件及新增 3 个存档模块，数值计算源码未改；不把旧执行哈希的 10034 前缀报告改写成新哈希。
- 实际 WebKit 使用正式登录表单/Cookie、完整正式应用路由，只关闭外部行情启动并放入临时数据库。`archive-formal-browser-save3.log` 确认前未写、成功仅一份、精度保留；`archive-formal-browser-isolation.log` 两个独立 Cookie 上下文冲突 409、本地备注保留，另一账户目录为空且不能读取原 ID。早期 CLI 函数语法解析失败日志保留。
- `archive-formal-browser-preview.log` 首次发现**无冻结指标的旧档仍调用指标计算接口**，不是仅脚本等待问题。新增 `readonlyArchive`，云端与本地快照共用只读模式：旧档只画原行情/原结构，不画未保存的 MA/指标，不开放参数编辑，也不能再次捕获为伪冻结指标；有冻结数据的新档仍按保存序列显示。
- 修复后的 `archive-formal-browser-legacy-final.log` 与 `archive-formal-browser-frozen-final.log` 均零行情/指标/缠论请求、零 pageerror；前者验证 1440/390/320px 无页面横向溢出。旧档快速连续 resize 的首次截图尚未布局稳定，已等待两次 animation frame 补拍 `archive-formal-legacy-stable-320.png`，实际画布和父容器均 278px、蜡烛完整显示；新档截图 `archive-formal-frozen-final-320.png`。两张均已查看。这里是合成备份验收，不冒充真实市场数值验证；真实冻结序列验证见前节。
- 最终 `frontend-archive-readonly.log` **297 逻辑 + 28 评级通过**；`build-archive-readonly.log` 类型检查/构建通过，既有 ECharts 679KB 分块警告保留。frontend-skill 采用原图下的一行缺失说明，不增卡片/弹窗；Playwright 实际发现并验证了旧档补算缺口。
- 仍待：复杂嵌套结构/多周期结果完整渲染契约、直接批量旧档迁移、显式重算/版本对照、账户停用/存储保留与备份生产生命周期、正式反向代理大文件限制与新版 Linux/生产发布门禁。全站十阶段目标未完成，未部署。
- 正式接入前恢复包 `source-before-archive-integration.tar.gz` SHA-256 `26c98ec0923164332f977dbfade66bb9d05ffe84434fba9dbf6f07a7b486dd0c`，包含已完成前缀报告及当时完整源码，不含生产数据/凭证。
### 上一阶段指标冻结验收历史（以下运行状态仅指当时）

- `frontend-frozen-final2.log`：293 逻辑 + 28 评级通过；新增全部指标定义输出、暖机空值、完整精度、快照独立性、禁联网、格式错位/损坏、导入集成及 HTML 转义测试。`build-frozen-final2.log` 类型检查/构建通过，保留既有 ECharts 大块警告。
- 隔离 WebKit：300750 日线 240 根真实冻结行情保存后，账户页原档 **13 条实际 ECharts 序列逐值相同**（7 MA、成交量/MAVOL5/MAVOL10、DIF/DEA/HIST），`frozen-ui-series.log`。账户页查看无行情/指标/分析请求、零 pageerror，`frozen-ui-account.log`。
- `frozen-ui-comparison.log`：日线与 30 分钟各 240 根，两个独立冻结指标对象正确保存。`frozen-ui-pending-error.log`：延迟/故障指标请求期间拒绝不完整保存，存档数仍为 2。故障注入 503 不属于生产故障。
- `frozen-ui-mobile-corrupt.log`：320px MA20 可临时开关、无页面溢出；注入冻结日期损坏后不绘图、不重算，仍可查看完整原始内容，零 pageerror。截图 `frozen-account-chart-390.png`、`frozen-comparison-320.png` 已查看。
- 首次 `frozen-ui-main.log` 监听所有请求，捕获到研究工作区后台自动五周期请求，故断言失败；不能据此说原档重取行情。已改在没有自动研究的账户目录单独验证，零请求结论仅对应后两次隔离复验，保留首次失败日志。
- 实查 session 25859 仍 live；报告 running、21 案例、9684 前缀。Python 执行哈希仍为 `research-execution-v1:9fb5d4f8a983ca93862a7850f1492072804b2e7102043dcbf79a17c9bac0333a`，未动正式后端、冻结清单或验证器，未部署。全站十项目标继续保留。
- 最终本地快照 `frozen-ui-local.log` 保存/打开成功，显示冻结指标且不提供参数重算编辑。补充本地旧档告知后最终构建 `build-frozen-release.log` 通过；末次报告 running、21 案例、9784 前缀，进程 PID 29389 仍在运行。
- 恢复包 `output/platform-optimization-20261009/source-after-frozen-indicators.tar.gz`，SHA-256 `9546927850b7b9dc70a997a4875ea08dd896303f09e816daa6a3a6c7bf4c9c32`；排除依赖、账户数据库、凭证及缓存。归档后仅补本记录。WebKit tdx-frozen 已关闭，QA PID 41779 经核对后 SIGTERM 并确认正常 shutdown；未停止原逐根验证器。
