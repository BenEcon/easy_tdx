# 缠论结构线宽 · 2026-09-29

在左侧图层下增加“线条粗细”，笔和线段分别设置 0.5–6 px，步进 0.05 px，支持手动输入、键盘上下箭头、恢复默认。默认仍为笔 1.35 px、线段 1.8 px。个股与行业共享本页设置，调整不重新请求分析或指标、不重置当前图表缩放。候选线段仍用虚线；悬停线宽随设置增加。设置为本页会话状态，刷新页面恢复默认。本次未改算法及信号判定。

遵循 frontend-skill，复用现有紧凑数值控件和暗色侧栏，并配蓝色/紫色线样预览，不另加浮窗。

## 验证

- 前端构建成功，135 项 Node 测试通过；原有图表大包警告保留。
- 浏览器使用模拟行情、真实图表组件与实际侧栏：两张图同步更新，默认值、恢复默认、范围限制、键盘微调、悬停宽度、候选虚线和缩放保留均验证通过。模拟行情只用于本机验收，未写入服务器。
- 公网 HTTPS 页面及新入口 `index-BNQdunTU.js`、缠论模块 `ChanlunView-DjOl4WEJ.js` 验证通过。

## 发布和回退

- 发布目录：`/home/opc/apps/easy_tdx-release-20260929-line-width`
- 镜像：`easy-tdx:line-width-20260929`
- 镜像 ID：`sha256:2354f17d4ac95e07cc886ab218c5549c6147da782271b53965ba086d85c876f9`
- 基于已上线 phase62 镜像，只叠加两个静态文件目录；保留后端及旧哈希资源供已打开页面使用。
- 发布包 SHA-256：`a99863d4d9f0cd329d3e2e7ec4230bfa27c607984304c2ffa8e60d5aafceaa23`
- 数据恢复点：`/home/opc/backups/tdx-20260929-line-width/data.tar.gz`（停服后备份，权限 600）。
- 正式容器发布后 `running / healthy`；复用原数据卷、端口及所有安全配置。
- 两数据库完整性均为 `ok`；用户数量、除 `preferences` / `updated_at` 外的用户字段、会话和个人策略与备份一致。运行中发现偏好及更新时间变化，未将其误判为数据丢失，也未用备份覆盖在线数据。
- 本地发布文件：`/Users/bowen/Documents/Python/Google/TDX-deployments/20260929-line-width`。本次未提交 Git，未覆盖其他已有开发改动。

回退应用，保留最新用户数据：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260929-220317/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260929-220317/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

单进程重启会使旧研究检查点失效，需重新搜索；该既有边界未变。
