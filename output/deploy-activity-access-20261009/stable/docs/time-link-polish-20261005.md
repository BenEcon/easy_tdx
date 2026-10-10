# 时间联动高亮修正 · 2026-10-05

## 修正范围

- 单根对应使用 1px 淡蓝定位线，不再绘制窄长矩形。
- 多根对应使用无边框低透明度区间，按半个柱宽覆盖两端。
- 每个价格/指标绘图区独立绘制，采用 ECharts 解析后的实际 grid 边界，避开标题、图例及绘图区间隙。
- 完全不在可视范围内时不显示，部分重叠时裁剪，不把不可见日期挤到边缘。
- 显式管理每个图形的 ID 和删除，修复空 group 更新可能保留旧图形的问题。
- 保持时间映射、点击信息卡及缠论判定不变；图形 silent，不抢占命中。

## 验证

- vue-tsc / Vite 构建通过；206 项前端单元测试通过。
- Chromium 模拟行情验证双向联动：单根为三段独立细线、多根为三个无边框区间；边界与实际 grid 一致，移出后全部删除。
- 原研究工作区浏览器回归通过：联动/缩放、审核、快照、账户偏好、多尺寸布局。
- 脚本 `output/playwright/time-link-polish-check.js`；截图 `time-link-single.png`、`time-link-multi.png`。
- 恢复点：`output/research-workspace-20261005/before-time-link-polish.tar.gz`。

## 发布

- 发布包：`output/deploy-time-link-20261005.tar.gz`。
- SHA-256：`f2f7bc715102a41263a4b7aeddbf90ed166f1a390d2f9dd6d18422e06fc5575f`。
- 基于 `easy-tdx:research-workspace-20261005`，仅替换前端资源。
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-time-link`。
- 停机数据备份：`/home/opc/backups/tdx-20261005-time-link/data.tar.gz`。
- 已部署，容器 `running / healthy`，镜像 ID：`sha256:d461e751386c2c647cb156f941f8ae4cb664fbf565a27fad1ebad8ea3af9e3a1`。
- 公网三个 HTML 入口、七项关键资源与登录保护通过；256 个后端模块不变，账户/策略数据库完整且与备份字节一致。

回退（不覆盖数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-research-workspace/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-research-workspace/release-image.yaml up -d --no-build --pull never easy-tdx
```
