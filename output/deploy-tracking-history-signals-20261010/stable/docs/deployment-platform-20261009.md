# 已完成优化的阶段部署 · 2026-10-09

用户明确要求“把目前完成的部署到服务器”，因此先发布已验证稳定快照，不等待完整十阶段目标，不包含正在提取的对比周期证据组件。

## 发布身份

- 地址：https://tdx.bowenv.com
- 镜像：`easy-tdx:platform-20261009`
- 镜像 ID：`sha256:1c3afdeee600f50c019a3f1352e506476c3ca16e5d78a2ecd567de6f4b8a9f60`
- 服务器目录：`/home/opc/apps/easy_tdx-release-20261009-platform`
- 已验证源码：`output/platform-optimization-20261009/source-after-evidence-date.tar.gz`
- 源码 SHA-256：`826161d861fc38ca2ad76b91a3ac4032c273b86685d569469b64c0fe52c526f7`
- 之前版本：`easy-tdx:research-20261009`，ID `sha256:83fde4353a5c84db8ddf9902f9bbc48289afdfc91ac1918bb9bbda6d891d5461`。

从稳定归档独立构建，没有使用当前工作树尚未验收的 SignalEvidenceWorkspace／PeriodEvidencePanel 提取。归档缺少的未修改构建配置及 public 资源从原工作树复制；依赖复用原锁定安装，生产依赖没有升级。

## 本次上线与保留边界

- 已完成的行情口径、来源状态、权限与资源准入、账户审计、结果证据及既有研究功能改进。
- 周／日／30／15／5 分钟信息表、统一结构买卖点／M1／背离／规则核验检索，以及主图日期直达证据。
- 后台仍显式使用 `EASY_TDX_TASK_BACKEND=memory`，没有启用未完成最终生产验收的独立 durable worker。
- 新增明确同源白名单 `https://tdx.bowenv.com`；Secure Cookie 保留；代理信任仅回环和已核对 Docker 网关 `172.22.0.1`。未改 Nginx、端口、数据卷或交易规则。
- 完整逐根矩阵仍在运行；十阶段目标、因子异常吞零修复和其他未完成项目没有被标记完成。不能把阶段上线描述为全部优化完成。

## 验证

- 稳定快照前端 262 项逻辑＋28 项评级通过；类型检查及生产构建通过；既有 ECharts 大分块警告仍存在。
- 稳定快照账户／安全／代理配置／资源准入／前端规则契约 133 项通过。日志在 `output/deploy-platform-20261009/stable/`。
- 新镜像、Python 3.12、隔离账户、断外网容器：实际 HTTP 登录初始化、Secure／HttpOnly Cookie、错误来源 403、匿名业务 401、注销失效通过；真实冻结 300750 周线 150 根及日／30／15／5 分钟各 240 根 replay 和 observations 全部通过。没有为测试创建生产账户。
- 首次 smoke 被 macOS 隐藏 `._*.json` 元数据干扰，读取失败；验收脚本改为只读取非隐藏 JSON，重新执行完整测试通过。应用源码未改变。
- 生产数据库只读挂载，通过 SQLite backup 创建隔离一致副本；新版迁移后逐表比较所有原字段／原记录摘要不变；旧镜像也实际读取并复核通过。不输出账户或策略内容。
- 部署脚本退出 0；容器 `running healthy`；认证状态接口 200、初始化标志 false；匿名行情 401、跨来源写入 403。公网 `/login` 200，未登录访问缠论跳转普通登录页面。
- 公网缠论 JS `ChanlunView-Cj9Fgu16.js` SHA-256 与本地一致：`9497213fa29c8203e66952b886f7f56c52adb391332a98e9d4a9d793d86f724b`。
- Playwright WebKit 公网 390px 登录页面无横向溢出，截图 `output/playwright/platform-live-login-390.png` 已查看。控制台唯一错误为 Cloudflare Insights 统计脚本网络连接失败，无应用资源错误；不宣称浏览器零错误或已完成生产账户登录后全部功能验收。

## 备份与回退

- 停止旧容器后完整备份同一数据卷，未覆盖或重建账户／策略库。
- 备份：`/home/opc/backups/tdx-20261009-platform/data.tar.gz`，权限 600。
- 备份 SHA-256：`3180a48c8eeea12435bf8be868dfcd806cd6b4072cd83f6df566d92141aedb09`。
- 旧 compose、镜像覆盖配置和 Nginx 配置保存在同一 700 权限目录。迁移验收副本移入其 `migration-validation` 子目录，权限 700。
- 回退应用可用旧目录的 compose＋release-image 配置启动旧镜像。数据库兼容已在副本验证；不要直接覆盖当前数据库，以免丢失上线后新写入的数据。恢复备份需要另外核对并明确授权。

此次没有修改生产用户设置、策略或密码；既有数据只做兼容性建表／增加字段迁移。浏览器临时会话在验收后关闭。
