# 缠论蜡烛填充透明度（已部署）

- 默认透明度 80%，即填充 alpha=0.2；面板明确显示透明与填充比例，0% 实心、100% 空心。
- 左侧“蜡烛填充”提供 0–100% 滑块、整数输入及恢复默认；采用现有紧凑步进器和轻量布局，符合前端设计技能的克制界面原则。
- 缠论个股、指数、板块及行业对比图均通过同一属性生效。边框／影线色不变，未收盘 K 线继续空心虚线。
- 只调整 ChanlunChart 的填充色 alpha，不影响其他页面 K 线，不改行情、指标、笔、线段或确认规则。
- 调整在当前页面生效，重新进入页面默认 80%；未新增账户持久化字段。

## 验收

- 182 项 Node 测试、类型检查、生产构建、git diff --check 通过；既有 ECharts 体积提示不变。
- 浏览器实际 App 路由＋合成数据：个股及行业两图默认均 alpha=.2，键盘 Home/End 调至实心／空心，数字输入 35 得到 .65，恢复默认 .2。
- 两图边框、最后一根未收盘空心虚线保持不变。320、390、768、1280 宽度页面无横向溢出，无页面脚本错误。
- 验收脚本 output/playwright/candle-fill-check.js，截图同目录 candle-fill-controls.png、candle-fill-desktop.png。

## 发布

- 镜像 easy-tdx:candle-fill-20261005。
- 镜像 ID：sha256:2f74edfdbf256d953f8eb0226508b96126b30670fdc3b53f9c31dfbf80eb1946。
- https://tdx.bowenv.com/chanlun 上线验收通过：容器 running / healthy，三处 HTML 和七项前端资源一致，登录保护正常。
- 配置、端口、安全设置、数据卷及 256 个后端模块保持不变；账户及策略数据库完整性与备份字节一致性校验通过。
- 发布目录 /home/opc/apps/easy_tdx-release-20261005-candle-fill。
- 数据备份 /home/opc/backups/tdx-20261005-candle-fill/data.tar.gz。
- 发布包 SHA256：9ed27d177f55cd5a1390596e36b02b5ee5f6f87d7e83186095ddee40b436cbd6。
- 上一版本 easy-tdx:evidence-style-20261005；暂停的文档分析未恢复。

回滚命令（不覆盖用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-evidence-style/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-evidence-style/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
