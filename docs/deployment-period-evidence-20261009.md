# 对比周期证据阶段发布 · 2026-10-09

用户要求将目前完成的优化部署到服务器。本次从已验收恢复包独立构建，不发布工作树中尚未接完、未验收的雷达复核改动。

## 发布范围

- 对比图按来源周期进入统一信号证据，支持日期检索、比较区间及局部反向笔定位、确认时刻审核回放。
- 主图与对比周期共用证据组件，但保持来源、日期精度和审核状态独立；迟到响应与错误处理不覆盖新的来源。
- 修复图表重建时旧联动 graphic ID 引起的异常，以及手机诊断行布局。
- 不修改缠论判定规则。Python 源码及 pyproject.toml 与上一线上快照相同；仅前端静态资源更新。
- durable worker 仍未启用；未完成的十阶段工作与全前缀验收不视为已完成。

## 身份与验证

- 源码：`output/platform-optimization-20261009/source-after-period-evidence.tar.gz`
- 源码 SHA-256：`e9fe0601cacd7dc7f4eec61b038e04693a42005e381a1050cc66dabcff86608a`
- 发布包 SHA-256：`dfe7f016748388affe3534f0f780136c9c1890caed36ad698367c6b713d5ec9b`
- 新镜像：`easy-tdx:period-evidence-20261009`
- 镜像 ID：`sha256:2532172e84c5b6be17cc713eeb6f077ec378eda3c6de447288a2ed868c5c73c0`
- 服务器目录：`/home/opc/apps/easy_tdx-release-20261009-period-evidence`
- 原版本：`easy-tdx:platform-20261009`，镜像 ID `sha256:1c3afdeee600f50c019a3f1352e506476c3ca16e5d78a2ecd567de6f4b8a9f60`。
- 独立发布快照重新运行前端测试：265 项逻辑、28 项评级全部通过；类型检查及生产构建通过。既有 ECharts 大分块警告仍在。
- 新镜像隔离、断外网、临时账户实测：周／日／30／15／5 分钟实际 HTTP replay 与 observations 通过；认证、Secure Cookie、来源校验、匿名拒绝及注销通过。无生产账户创建或修改。
- 构建、测试及部署日志：`output/deploy-period-evidence-20261009/`。

## 回退约束

部署脚本先核验旧镜像、数据卷和网关，停止服务后备份原数据，再切换新镜像。失败自动用旧目录 compose 与 release-image 配置恢复原镜像，保留当前数据，不自动覆盖数据库。旧镜像与旧部署目录均保留。

备份预定目录：`/home/opc/backups/tdx-20261009-period-evidence`，目录权限 700、数据归档权限 600。最终上线及公网核验结果追加如下。

## 上线结果

- 部署脚本退出 0；新容器 `running healthy`，镜像 ID 与隔离测试版本一致。
- 数据备份已完成：`/home/opc/backups/tdx-20261009-period-evidence/data.tar.gz`，SHA-256 `fc5b03eb4f5ab9bac4f7619f4c25bfded112233369794b2d5996a9925cb80c3c`。
- 认证状态正常（无需初始化），匿名行情接口 401、错误 Origin 写请求 403；未重置生产账户、策略或用户偏好，Nginx、端口与数据卷保持原样。
- 公网 `ChanlunView-Bpaul9dY.js` 的 SHA-256 `5cd9b1d377c0022cbedb7c106bf6b661fef52a85e34f0ac89dcffbfd33015340` 与独立构建完全一致。
- 按 Playwright skill 完成独立 WebKit 公网检查：未登录访问缠论正常跳到网页登录，390px 文档宽度为 390px，无横向溢出，截图已查看。唯一控制台错误来自 Cloudflare 统计 beacon 网络连接，不是应用资源；不声称零控制台错误或生产账户登录后全功能验收。
- 本次浏览器会话已关闭。最新雷达上下文开发代码仍只在工作树，未发布；本次上线不代表全部优化目标完成。
