# 多周期图表对比 · 2026-10-05

## 功能与口径

- 在主图上方增加对照周期选择与“生成对比”；支持月、周、日、60/30/15/5/1 分钟，不改变左侧主周期。
- 生成后可切换主周期、仅看对照周期、上下对比；支持个股、指数及板块，沿用当前实际复权方式。
- 两图独立结构计算，沿用均线、图层、线宽和透明度；技术指标、缩放和全屏可各自操作。
- 主周期复用当前可见快照，仅当需排除未收盘柱时重新计算；副周期使用同一截止时刻，保留各自预热起点。共同截止不等于起始日期相同，各图显示实际覆盖区间与排除数量。
- 截止为主图 as-of 与两个快照 observed_at 的最早值；严格要求 is_closed=true 且 period_end <= cutoff。缺失时间、收盘标识、复权不一致或乱序时明确报错。
- 变更标的、周期、复权、窗口、回放时刻或对照选择后清除旧结果；过时请求返回不会覆盖新选择。失败时保留原主图，无历史数据时不补造行情。
- 下方结构明细仍属于左侧主周期；点击明细定位时返回主图，不将不同周期的证据混用。
- 本次同时发布此前本地完成的背离／买卖点事件版式深化，见 event-ledger-20261005.md。
- 修正全屏降级被外层窗口裁切：降级时将框架传送到 body，退出时还原，显式保留组件 class 等属性；修正 ChanlunChart scoped global 选择器错误匹配框架的问题。

## 验证

- 195 项前端单元测试通过；23 项后端回放／对比回放测试通过；vue-tsc 与 Vite 构建通过。保留原有大型图表资源警告。
- Playwright 使用真实应用、模拟 API，覆盖个股／指数／板块、不同周期独立回放请求、排除未收盘及截止后柱、旧响应隔离、失败恢复、空历史、主图恢复、键盘切换、原生与降级全屏。
- 1440、768、390、320px 对比区域无横向溢出；截图 output/playwright/period-compare-*.png。
- 事件版式脚本再次回归通过，包含 21 条背离事件、结构／MACD 提示、回放定位、11 个区块缩进和手机布局。
- 脚本：output/playwright/period-compare-check.js、event-ledger-check.js。

## 已部署与恢复

- 发布包：output/deploy-period-compare-20261005.tar.gz
- SHA256：459346e0233a5e84918180dd3bf6d392b31277ac67a60ad8e8a58bfaa7184fd4
- 基于生产 easy-tdx:divergence-layout-20261005，仅替换两处静态资源目录；不修改后端算法、服务配置和数据卷。
- 生产版本：easy-tdx:period-compare-20261005，容器 running / healthy。
- 镜像 ID：sha256:81433ab3cd47326880a93cbc0c8477b79858cfaa323a578a76ca1133d0e1fe23。
- 发布目录：/home/opc/apps/easy_tdx-release-20261005-period-compare。
- 一致性数据备份：/home/opc/backups/tdx-20261005-period-compare/data.tar.gz。
- 公网三个 HTML 入口、七项关键资源一致性及登录保护通过；256 个后端模块未变，账户与策略数据库完整且与停机备份字节一致。
- 补充核验 ChartFrame-DMYzUDFs.js 与 ChartFrame-BqFOyl-x.css 公网 SHA256，均与构建文件一致。

回退上一版（不覆盖数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-divergence-layout/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-divergence-layout/release-image.yaml up -d --no-build --pull never easy-tdx
```
