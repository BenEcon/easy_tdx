# 三笔盘整表格与补充层级样式 · 2026-10-05

## 内容与验收

- 计算口径与参数说明：正文相对标题缩进，保持参数列对齐。
- 最近的线段：正文、线段记录、确认依据逐级缩进；仍默认收起。
- 三笔盘整：正文缩进；语义化表头与行标题、两位小数价格、来源笔、确认状态统一对齐。
- 保留“非中枢”说明；进行中采用低饱和暖色背景与空心状态点，状态文字不依赖颜色。
- 表格随可用容器宽度转为分行布局，极窄容器单列，保留键盘折叠。
- 前一实施回合 189 项测试通过；部署前重新生产构建通过。
- 浏览器使用模拟行情验证 1440/390/320/768px，无页面或受测面板横向溢出；表头、行数、层级缩进、键盘展开收起通过。
- 脚本及截图：`output/playwright/consolidation-table-check.js`、`consolidation-table-*.png`。

## 发布信息

- 新版本：`easy-tdx:consolidation-table-20261005`
- 前版：`easy-tdx:research-indent-20261005`
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-consolidation-table`
- 数据备份：`/home/opc/backups/tdx-20261005-consolidation-table/data.tar.gz`
- 包 SHA256：`8f9045f37bcd88217087ae0b69239544009b92dcb959afa7f9ce8c858e3c29e6`
- 仅替换前端资源；沿用原容器配置和数据卷，不更改后端规则。
- 已部署，镜像 ID：`sha256:54102935379927a522f71c9cbcb0f896533a48c64a091accfb3c2bf89718f155`。
- 容器 healthy；三个公网 HTML 入口及七个关键资源校验通过；256 个后端模块未变。
- 账户和策略数据库完整且与停机备份字节一致，登录保护正常。

回退命令（保留当前数据）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-research-indent/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-research-indent/release-image.yaml up -d --no-build --pull never easy-tdx
```
