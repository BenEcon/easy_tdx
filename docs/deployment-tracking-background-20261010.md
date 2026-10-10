# 追踪标的后台分析发布 · 2026-10-10

## 发布边界

从线上 activity-access-20261009 的独立源码快照构建，只合入本次追踪后台分析、滚动布局和请求账户绑定。工作树其他因子研究、偏好隔离、查询统计等改动不混入此发布。

- 同标签页内切换站内路由继续分析；全局顶部进度入口，返回保留本批结果。
- 支持主动停止、完成项保留、分组/周期快照、权限撤销和账户切换保护。
- 修复页面纵向滚动、长文本换行和窄屏表格局部双向滚动。
- 不是服务器持久队列：刷新、关闭、注销会中断；浏览器休眠可能暂停。未启用 durable worker。
- 不改缠论计算规则、不改数据库结构，不创建生产测试账户。

## 制品与验证

- 本地目录：output/deploy-tracking-background-20261010/，stable 为独立发布源码。
- 源码 SHA-256：eacc6136e5bcef7e3910c6b30da99ea62e346ba254647ee7671e4e591dddb7b2。
- 发布包 SHA-256：4f610357344991e5e7384864d4a882ad693677ef29f5c43a00c9b2d7b4db0bae。
- 镜像：easy-tdx:tracking-background-20261010。
- 镜像 ID：sha256:f4c6410a0a1cbe490dd0f8b39c0acd0a722bae05468861a18b48b9fa552cda97。
- 服务器目录：/home/opc/apps/easy_tdx-release-20261010-tracking-background。
- 独立快照前端 318 + 28 项通过，TypeScript/Vite 构建通过；后端 35 项相关回归通过。原有图表 chunk 体积提示保留。
- 实际候选 Linux 镜像在无外网、临时数据环境中验证：真实 HTTP 的账户归属、权限授权/撤销、旧账户表迁移、周/日/30/15/5 分钟 replay/observations、11 MiB 存档、账户隔离、重启保留和注销全部通过。
- 开发态桌面/手机交互验收见 tracking-background-analysis-20261010.md，不冒充生产账户登录后实测。

## 恢复

部署前验证生产镜像与隔离验收镜像 ID；停止服务后备份整个数据卷再切换。异常自动恢复旧镜像，保留当时数据，不自动用备份覆盖数据库。

- 旧镜像：easy-tdx:activity-access-20261009，ID sha256:9877d278e47e125d34a9d9c88213fab0d01bd9ac228f37330ef863a265ca2c7a。
- 旧目录：/home/opc/apps/easy_tdx-release-20261009-activity-access。
- 备份目录：/home/opc/backups/tdx-20261010-tracking-background（目录 700，数据归档 600）。
- 沿用原生产 compose、数据卷、端口、Nginx，不改其他站点。

## 上线结果

- 部署脚本退出 0；生产镜像 ID 与候选一致，容器 running healthy。
- 数据备份 SHA-256：0c803357a526483d03e5e9dc1733636bf113309b55f29e1f8e29ed415e1c7f3d。
- 认证状态 setup_required=false，匿名行情 401，错误 Origin 登录写请求 403；原账户与持久数据卷沿用。
- 公网 /tracking 已引用 index-NmOl9M3m.js；TrackingView-9u39e6bW.js 和 TrackingView-C3RNZxoY.css 哈希与制品分别一致：
  - JS：f36f65d3b8aee4520061080edd5e7c66d0999d176ca551fb850a711a2053c96a。
  - CSS：76b8a9a4d14657d647c9875b31741e745376e622d22b3c7c14046ec5523190dc。
- 未使用生产账户登录或创建测试账户；登录后流程依据同镜像隔离测试及本地交互验证。
