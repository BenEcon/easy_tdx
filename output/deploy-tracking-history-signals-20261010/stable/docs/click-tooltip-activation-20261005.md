# 点击激活信息面板（已部署）

按用户澄清，普通 K 线和缠论图共用以下行为，不改信息面板样式、内容和任何分析规则：

- 初始未激活，鼠标移入及移动不出现信息面板。
- 图表内点击激活并显示该位置的信息；之后移动鼠标跟随日期更新。
- 仅移动到图外再回来，不解除激活状态；图外点击才隐藏并解除激活。
- 关闭后再次移入、移动仍不显示，必须再次点击激活。
- Escape、新数据及组件重置解除激活。缩放仅清除原坐标下的旧面板，下一次移动仍可更新，不额外要求点击。
- 两种图表共享一个状态控制器，卸载移除全部监听。

验证：172 项 Node 测试、类型检查及生产构建通过。Playwright 在实际 ChanlunChart 和 KlineChart 组件验证默认隐藏、点击激活、移动改变日期、移出再入保持激活、图外点击关闭、关闭后移动不显示、再次点击激活及 Escape 关闭，全部通过。模拟行情仅用于 UI 验收。

2026-10-05 按用户“部署到服务器”授权发布。线上镜像为 `easy-tdx:tooltip-activation-20261005`，镜像 ID `sha256:7c8831584d54efaad407cba033d4576b19c0246c6e06239b3e5c8684eef94252`。

本次只覆盖前端构建。256 个后端模块与上一版完全一致，运行配置、端口、安全限制、数据卷不变；账户和策略数据库完整性检查通过，与停服备份字节一致。公网首页、登录页、缠论页及入口、两类图表、共享图表 JS/CSS 均与本地构建哈希一致，容器健康和登录保护检查通过。

- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-tooltip`
- 备份：`/home/opc/backups/tdx-20261005-tooltip/data.tar.gz`
- 发布包：`output/deploy-tooltip-20261005.tar.gz`
- 发布包 SHA256：`8b0510943fe4cead92541bd2644561ae265e2f15d53ccf6eaeb3d1843c738c48`
- 上一版：`easy-tdx:instruments-20261005-v2`

回滚只切换应用镜像，保留当前数据卷：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-instruments-v2/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-instruments-v2/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

《2026.10.4.docx》任务继续暂停，未纳入发布。
