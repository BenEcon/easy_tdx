# 全域递归及相邻研究区块样式优化（已部署）

## 范围

- 全域走势递归：准入、来源与层级、核验截止改为标签／说明布局；使用边界完整保留。
- 全来源覆盖：来源、层级与状态对齐，外部可用使用弱色实心点，区内保留和待解决使用空心点且保留文字，不只靠颜色区分。
- 完成走势：标题、来源、状态分层；价格、局部可知、结构可用、当前准入、归属和 MACD 依据统一定义列表。
- 子走势查看：简化阅读面板；范围、状态、覆盖缺口与依赖路径独立展示，原下钻、定位和回放操作不变。
- 归属时间轴、完整分解搜索：整理重建方式、数据版本、搜索边界、完成与续接口径；失败原因汇总改为原因／计数对齐。
- 分层归属与跨中枢核验：统一说明、事实、限制与空态；旧解释使用和其他区块一致的标识。
- 按 frontend-skill 的克制布局与阅读层级原则，延续现有低饱和配色、正文行距、两端对齐、轻量展开反馈和基于内容宽度的手机布局。

## 验收

- ReleasedRecursionInspector、ReleasedMovementExplorer、ReleaseResearchDesk、ExhaustiveResearch、LayeredOwnershipInspector、ExpansionInspector 六个组件 script 与 HEAD 完全一致；未改变计算、校验或请求逻辑。
- 173 项 Node 回归、类型检查、生产构建和差异检查通过；保留既有 ECharts 大包提示。
- Playwright 使用真实 App 路由与合成结构数据，验证一条通过来源校验的 M1 外部走势、待解决来源、三个基础子来源及一个反向确认来源；键盘展开／收起正常。
- 320、390、768、1280 像素无页面或目标面板横向溢出，无页面脚本错误；1440 像素桌面额外检查。
- 相邻研究区块检查初始态及缺少数据提示。此次不重新验证金融算法，不将合成验收数据打包到线上。
- 模拟 503 后错误说明和重试按钮正常，预期的 503 为唯一控制台资源错误；减少动态效果设置生效。
- 脚本：output/playwright/recursion-style-check.js。截图：同目录 recursion-style-desktop.png、recursion-style-research.png、recursion-style-mobile.png。

## 部署记录

- 已部署至 https://tdx.bowenv.com/chanlun，镜像为 `easy-tdx:recursion-style-20261005`。
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-recursion-style`。
- 数据备份：`/home/opc/backups/tdx-20261005-recursion-style/data.tar.gz`。
- 发布包 SHA256：`0327351840266c3fcf1488dcca2ab3f817347c0e077aef9dc2ece0e3092682c2`。
- 容器 running / healthy；公网页面及七个前端资源与发布文件核对通过，登录保护正常。
- 配置、端口、安全设置和数据卷保持不变；256 个后端模块未改变，账户与策略数据库完整性检查通过且与切换前备份逐字节一致。
- 上一版本：`easy-tdx:research-typography-20261005`。可通过以下命令回滚前端，不覆盖用户数据：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-research-typography/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-research-typography/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

暂停的文档分析未恢复。
