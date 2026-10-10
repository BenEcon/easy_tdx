# 追踪历史、买卖点及筛选发布 · 2026-10-10

## 制品

- 基线：`easy-tdx:tracking-background-20261010`，ID `sha256:f4c6410a0a1cbe490dd0f8b39c0acd0a722bae05468861a18b48b9fa552cda97`。
- 新镜像：`easy-tdx:tracking-history-signals-20261010`，ID `sha256:936c3f3a821773aba7162c02c95b6e7d223e93e2d69001d0446dda99ac29094e`。
- 服务器目录：`/home/opc/apps/easy_tdx-release-20261010-tracking-history-signals`。
- 独立源码 SHA-256：`81b902bdae20e0b9d88da9c5becdb984fd2fd2647d5fe2c8ecb8eeba821ebace`。
- 最终发布包 SHA-256：`0872ab5c98b40a63e0e14b0dd04d21e7f4f3b0a61dcfd972c3afdccecd23fbbf`。
- 仅合入追踪自动保存、买卖点展示、汇总数字筛选。未合入工作区其他因子、回测、存档迁移和查询分类修改。

## 测试

- 独立发布源码：332 + 28 项前端测试、104 项后端测试通过，TypeScript/Vite 构建成功。
- WebKit 开发态验证：数字选择、0 项空结果、M1 筛选、原档重开及筛选、390 px 手机和 1440 px 桌面；无控制台错误。
- 实际 Linux 候选镜像禁外网、临时数据验收：真实 HTTP 的周/日/30/15/5 分钟 replay 和 observations、买卖点日期、追踪权限与账户隔离、防重复保存、原始行情与规则版本保留、重启读取、11 MiB 既有图表存档均通过。
- 未创建或使用生产测试账户。

## 镜像层数处理

原镜像 124 层，叠加后无法创建容器。用原镜像创建未启动临时容器，导出程序文件并扁平化导入；没有挂载生产数据。保留原运行环境、命令、用户、工作目录、端口和卷配置，Dockerfile 恢复健康检查。只清理该临时容器及其空匿名卷，原镜像保留。

第一次隔离脚本遇到 macOS `._*.json` 元数据并误作为行情读取，已在验收脚本排除，最终验收成功；最终发布包也排除该元数据。

## 备份与恢复

- 发布前停服务备份整个数据卷，备份路径 `/home/opc/backups/tdx-20261010-tracking-history-signals/data.tar.gz`，权限 600。
- 数据备份 SHA-256：`50fc19b0a31d76bb96e6fbe9eb998c5efa6ae7d1cd637d23977b7d74c7c5fb63`。
- 原目录 `/home/opc/apps/easy_tdx-release-20261010-tracking-background` 保留，失败自动切回旧镜像，不自动覆盖当前用户数据。
- 不修改其他站点或 Nginx 配置，沿用原数据卷与端口。

过程日志：`output/deploy-tracking-history-signals-20261010/`。

## 上线确认

- 部署退出 0，新镜像 ID 与隔离验收候选一致，容器 `running healthy`。
- 原账户状态 `setup_required=false`；匿名行情 401、错误 Origin 写请求 403 检查通过。
- 公网 `/tracking` 已引用 `index-QWNnRtrK.js`。
- 公网 `TrackingView-nIZW0BMd.js` SHA-256 为 `1af6743bd395789aa4ba8ce9f7459e3650c67940680581431876643e870c7d1d`；CSS `TrackingView-BZ-V44Ss.css` 为 `e311c5017482d0d310cc9990297734a28c496155f354fd212a8ad2500cff362c`，均与制品一致。
- 新字段需重新分析生成；旧存档显示「未记录」，不会自动补算历史结果。
