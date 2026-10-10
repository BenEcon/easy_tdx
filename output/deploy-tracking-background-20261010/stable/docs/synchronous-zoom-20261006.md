# 缠论图表同步缩放 · 2026-10-06

## 原因与修正

普通模式此前启用了 ECharts 动画（仅 focus 核验时关闭），各系列与 marker 更新分别插值，造成 K 线、笔、线段及标记缩放先后到位。

- 全部研究图层统一禁用几何入场/更新动画，包括 markPoint、markArea、markLine、均线和技术指标，不靠统一时长仍分别插值。
- 禁止系列渐进分批绘制；当前有限行情窗口的蜡烛使用普通模式，避免与折线不同绘制批次。
- inside/slider 缩放采用一致 16ms 节流，slider 保持实时；轴指示器不额外插值。
- 去掉图表高度 CSS 过渡，避免切换指标时容器连续变高造成额外追赶。
- 不修改行情、结构坐标、成笔/线段/背离规则及信息面板触发方式。共享组件覆盖个股、行业、对照与快照图表。

## 验证

- 构建通过，207 项前端测试通过。
- Chromium 合成行情，连续十次扩大/缩小：缩放事件返回后及下一帧分别验证 K 线图元与布局一致，笔/线段/均线实际折线路径与目标布局一致，没有几何插值动画。
- 390/1440px 截图检查；脚本 `output/playwright/synchronous-zoom-check.js`。
- 原研究工作区回归通过：双图时间/范围联动、全屏、审核筛选、快照、偏好与 1600/768/390/320px 布局。
- 本地修改前归档：`output/research-workspace-20261005/before-synchronous-zoom-20261006.tar.gz`。

## 已部署

- 2026-10-06 发布为 `easy-tdx:synchronous-zoom-20261006`，容器 `running / healthy`。
- 镜像 ID：`sha256:0ad21a4d8ebf099d1d1bf9805779c527c502e213c0166d997d0ca324e4f39bc6`。
- 发布目录：`/home/opc/apps/easy_tdx-release-20261006-synchronous-zoom`。
- 停机数据备份：`/home/opc/backups/tdx-20261006-synchronous-zoom/data.tar.gz`。
- 发布包：`output/deploy-synchronous-zoom-20261006.tar.gz`，SHA-256 `6dbc72abfad003d38868dc38a3dff4cff54b5ec2e814e681ff335d2addb316a9`。
- 公网三个 HTML 入口、七项关键资源和登录保护核验通过；256 个后端模块未变；账户及策略数据库完整且与停机备份字节一致。

回退命令（保留数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-object-hover/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-object-hover/release-image.yaml up -d --no-build --pull never easy-tdx
```
