# 买卖点信息面板 · 2026-10-05

## 原因与修复

- 原图的命中检测只登记背离标记和盘整矩形，未登记结构性买卖点与 M1；现在记录实际渲染的坐标、尺寸和偏移，复用原有命中检测。
- 信息卡未激活时，悬停买卖点预览；点击或右键固定，移入面板可继续查看依据，Esc／外部点击关闭。
- 普通蜡烛图仍是点击激活、鼠标移动更新、外部点击关闭。买卖点点击优先打开对象详情，不同时显示日期卡。
- 同位置聚合 B/S 标签保留全部来源，可以逐条切换；M1 使用原 macdPrompts 筛选，不新增信号，也不将非标准或特殊背离提升为 M1。
- 复用紧凑浮层：类型、极值日期、价格（两位小数）、实际确认时间、来源、原始说明及可展开依据。未知确认与结构来源明确标为缺失，不伪造规则。
- 新增“查看买卖点详情”入口，方便手机和键盘用户；只在图层启用且有可定位记录时显示。
- 共享 ChanlunChart，因此主图、行业图、多周期对比图均使用同一逻辑。

## 验证

- 198 项前端单元测试通过，vue-tsc／Vite 构建通过（保留既有大资源警告）。
- 真实浏览器模拟接口：六类结构买卖点、同位置多个来源、M1 独立依据、未知确认、文本转义。
- 检查悬停、点击、右键、键盘、外部关闭、日期卡优先级、缩放后命中、图层隐藏／恢复和新查询清理。
- 390／320px 面板不越界；脚本 output/playwright/signal-popover-check.js，截图同目录 signal-popover-*.png。

## 已部署与恢复

- 基于 easy-tdx:period-compare-20261005，只替换前端静态资源，不修改分析算法。
- 发布包 output/deploy-signal-popover-20261005.tar.gz。
- SHA256：e5fb56a4d90ef5e92aa830f01088caf51ac404e95ef3ffef647e2e8fb01eac18。
- 多周期对比浏览器回归通过，包括桌面与手机布局、原生／降级全屏、历史截止和过时请求隔离。
- 生产版本：easy-tdx:signal-popover-20261005，running / healthy。
- 镜像 ID：sha256:b05c9d14cdab550e9a92ceb8d42bc6acdc1e431b35bd7f2f4572270e5d60b542。
- 发布目录：/home/opc/apps/easy_tdx-release-20261005-signal-popover。
- 数据备份：/home/opc/backups/tdx-20261005-signal-popover/data.tar.gz。
- 公网三个 HTML 入口、七项关键资源与登录保护验证通过；256 个后端模块未变，账户与策略数据库完整且与停机备份字节一致。

回退（不覆盖数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-period-compare/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-period-compare/release-image.yaml up -d --no-build --pull never easy-tdx
```
