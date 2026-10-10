# 背离列表与研究层级统一 · 2026-10-05（已部署）

- 背离事件记录采用独立可折叠区块，默认展开；保留所有候选、确认和失效记录。
- 条目按类型、状态、极值/对照/确认日期、说明、判定依据、定位与回放排列。
- 复用 EvidenceReading 展示短字段与长段落，不删除、截断或修改原判定依据。
- 核验列表分离类型、时段、状态和失败摘要；完整失败追踪及旧规则对照仍可展开。
- 去掉旧规则对照左竖线，回放按钮成组对齐，窄屏自动换行。
- 将层级步长集中于 research-panel：桌面 20px、手机 10px、小屏 8px；补齐快照说明与多周期研究。
- 不修改分析规则、信号状态、查询接口或数据。

验证：189 项测试、vue-tsc 和 Vite 构建通过；Playwright 模拟行情覆盖 7 种事件×3 种状态、4 类核验、11 个研究区块缩进。1440/390/320/768px 无受测面板或页面横向溢出；键盘折叠、定位比较区间、首次提示时刻回放成功。

验收脚本：`output/playwright/divergence-layout-check.js`；截图：同目录 `divergence-record-*.png` 与 `divergence-audit-*.png`。

## 部署与恢复

- 生产版本：`easy-tdx:divergence-layout-20261005`，容器 healthy。
- 镜像 ID：`sha256:3f77d82b4e5aa9be3591bce32e6b1459dec5bba4b6ac8603ff21325a614e4f98`。
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-divergence-layout`。
- 数据备份：`/home/opc/backups/tdx-20261005-divergence-layout/data.tar.gz`。
- 部署包 SHA256：`fc6b5d952ddb2f24adf3c1d4da9bbb367f5b8e85a54d33334d2e7084826f7a62`。
- 三个公网 HTML 入口、七个关键资源一致性及登录保护检查通过。
- 256 个后端模块未变；账户和策略数据库完整且与停机备份字节一致。

回退前版（不回写数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-consolidation-table/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-consolidation-table/release-image.yaml up -d --no-build --pull never easy-tdx
```
