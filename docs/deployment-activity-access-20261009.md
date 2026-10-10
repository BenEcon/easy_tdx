# 追踪授权与用户活动发布 · 2026-10-09

用户要求完成后部署。候选来源为已完成本地验证的独立快照；本次不改变缠论数值规则，不自动授予任何普通用户权限，不创建生产测试账户。

## 发布范围

- 管理员及指定用户的追踪标的权限，撤权保留分组；管理员用户活动、登录 IP、按需外部归属地与受支持查询记录。
- 自上一线上版本之后已验收的雷达复核上下文、追踪分组、五周期信息表、云存档／只读原档／冻结指标与深层渲染校验一并发布。原完整十阶段任务未全部完成，不把本次发布称为全站优化终结。
- 部署检查补上 Web 运行依赖 httpx；实际镜像安装 httpx 0.28.1、httpcore 1.0.9、certifi 2026.7.22，pip check 通过。后台任务仍使用 memory，不启用尚未发布的持久 worker。
- Nginx 上传限制由 10m 调整到 26m，匹配存档 JSON 包装上限；应用层仍要求身份和上传容量槽，普通接口保留更小上限。

## 独立制品

- 源码：output/deploy-activity-access-20261009/source.tar.gz。
- 源码 SHA-256：24e11c566a8905a0c7923f9e8ef3faefd12ba71d0dc82ac2433b79ae4b6881a6。
- 最终发布包 SHA-256：4185ceb29acb8237d3c6bcc5a2f854cf05083dd74a4bfd01b10274c1bb7bdd14。
- 候选镜像：easy-tdx:activity-access-20261009；ID sha256:9877d278e47e125d34a9d9c88213fab0d01bd9ac228f37330ef863a265ca2c7a。
- 服务器候选目录：/home/opc/apps/easy_tdx-release-20261009-activity-access。
- 旧镜像：easy-tdx:period-evidence-20261009；ID sha256:2532172e84c5b6be17cc713eeb6f077ec378eda3c6de447288a2ed868c5c73c0。

## 验证与回退

- 独立快照后端 167 项相关测试通过；前端 310 逻辑＋28 评级通过，类型检查和构建通过，既有 ECharts 大块提示保留。Ruff 全源／测试检查通过。
- Linux 实际候选容器断外网、临时数据库、真实 Cookie 和 HTTP 验证。第一轮大文件测试漏填图表设置，正确返回 422；仅修正测试夹具，未放宽业务校验。全部最终结果以 server-smoke-final.log 为准。
- 部署脚本校验当前镜像、持久数据卷、网关和隔离 smoke 标记，停止服务后备份整个 /data，再切换。任一步失败恢复旧镜像和 Nginx 配置，不自动覆盖当前数据库。旧目录及镜像保留。
- 备份目录：/home/opc/backups/tdx-20261009-activity-access（目录 700，数据归档 600）。数据库变化是新增字段／独立存档及活动表，旧账户、密码、角色、偏好及策略不重置。

## 上线结果

- 隔离 Linux 容器最终 smoke 退出 0：旧表迁移、授权／撤权／分组保留、五周期实际 replay/observations、查询元数据、11 MiB 原档读写、账户隔离、重启后的存档／偏好／活动保留及注销全部通过。没有向生产创建测试账户。
- 部署脚本退出 0，容器 running healthy，镜像与已验收候选一致。认证状态 setup_required=false；匿名行情、活动、存档接口 401，错误 Origin 写请求 403。
- 数据备份 SHA-256：ae3c333a53324e25fac58c780540322edf642495acdb81e360ba4f1710e9ce14。旧部署目录／镜像及原 Nginx 配置均保留。
- 公网 AdminAccountsView-CTvrwhtf.js 哈希与发布包一致：b22ace2b879360022c8fcd7bcb2539f2b0e6015ee387370a0f273d624bbfb4cb。服务器实际查询公共测试 IP 8.8.4.4 成功，没有外发用户 IP。
- 独立 WebKit 未登录打开追踪地址，正确跳至 /login?redirect=/tracking；390px 文档宽度 390px，截图已查看。没有使用生产账户登录，因此登录后的授权流程以同镜像隔离验收为证，不冒充线上用户实测。
- 浏览器唯一资源错误为 Cloudflare Insights beacon 连接中断；Nginx 既有其他域名重复 server_name 警告仍在，配置语法与 reload 均通过。本次没有修改其他站点。
- 日志／制品保存在 output/deploy-activity-access-20261009/。完整十阶段优化目标仍未全部完成。
