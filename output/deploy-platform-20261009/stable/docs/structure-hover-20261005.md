# 缠论对象悬停预览（已部署）

## 交互

- 日期信息面板未激活：鼠标命中背离／背驰标记（包括开启历史后的失效点）或盘整矩形，复用同一结构详情面板临时预览，不抢焦点。
- 移出对象与面板后延迟 180ms 收起，允许从对象移动到详情面板阅读。右键对象或操作面板后固定查看，外部点击、Esc 或关闭按钮收起。
- 普通蜡烛悬停不自动激活日期面板；点击激活后继续随鼠标更新日期信息，此时不打开结构预览。点图外后恢复未激活状态。
- 使用同一套渲染坐标与标记堆叠偏移命中；缓存本次渲染的标记，避免在每次 pointermove 深拷贝完整图表配置。
- 图层、数据、回放、缩放、尺寸变更关闭旧面板；卸载清理延迟任务。Esc 关闭后在同一命中对象上轻微移动不会立即重开。
- 按 sidebar-dialog-ux 技能复用非模态详情，区分临时预览与固定查看，不新增永久信息面板。
- 本版合并此前未部署的工具栏对齐、对称进行中图标、股票名称补全、背离右键详情、灰色连续空心历史标记。判定规则未改。

## 验收

- 189 项 Node 测试、类型检查、生产构建、git diff --check 通过。
- 浏览器使用实际 App 路由与合成数据，验证未激活蜡烛不显示、三种生命周期悬停、无焦点抢占、移开关闭、移入面板保持、操作／右键固定、激活日期优先、外部重置、盘整预览及 Esc 抑制重开。
- 七类 × 三状态右键、历史开关、缩放、全屏、股票名称以及 320/390/768/1280 宽度回归通过。
- 脚本：output/playwright/structure-hover-check.js、structure-details-check.js；预览截图 divergence-hover-preview.png、consolidation-hover-preview.png。

## 发布记录

- 发布镜像：easy-tdx:structure-hover-20261005。
- 发布目录：/home/opc/apps/easy_tdx-release-20261005-structure-hover。
- 数据备份：/home/opc/backups/tdx-20261005-structure-hover/data.tar.gz。
- 包 SHA256：8a961af04732594ee03754d8c47c7c6473f0137a0028a6221124ad1572abfc19。
- 上一版本：easy-tdx:consolidation-popup-20261005。
- 镜像 ID：sha256:6596c28473bc150838a4d1947005f471239f6871e851b68cb77ed891d7c1b09e。
- 容器 running / healthy，三个公开 HTML 入口与七项资源哈希核对通过，登录保护正常。
- 配置、端口、安全设置、数据卷及 256 个后端模块保持不变；账户／策略数据库完整性通过，且与部署前备份字节一致。

回滚（保留用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-consolidation-popup/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-consolidation-popup/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
