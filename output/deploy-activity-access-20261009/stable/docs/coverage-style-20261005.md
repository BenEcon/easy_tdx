# 全来源覆盖样式优化（已部署）

## 展示调整

- 标题、基础线段数量与展开箭头分区对齐；保留键盘展开和焦点提示。
- 覆盖明细按基础来源、结构层级、当前状态展示，来源编号、线段数及状态说明独立排版；采用轻分隔线而非嵌套卡片。
- 外部可用、区内保留、待解决保留文字及不同状态点，采用低饱和色，避免只靠颜色区分。
- 基于内容宽度响应，窄屏分层排列，无内容裁切；遵循前端设计技能的克制阅读布局。
- 未修改 script、来源核验或后端分析规则；同包包括上一轮盘整状态配色及默认关闭的“下一笔参考”。

## 本地验收

- 178 项 Node 回归通过；类型检查、生产构建和 git diff --check 通过。仍有既有 ECharts 包大小提示。
- Playwright 在真实 App 路由以合成数据验证 4 条基础来源（完成结构 3 条＋待解决 1 条）、覆盖表语义、键盘展开／收起及 4 条子来源查看。
- 320、390、768、1280 像素下页面、覆盖明细和相邻面板无横向溢出，无脚本错误；桌面／手机截图人工检查通过。
- 脚本：output/playwright/coverage-style-check.js；截图同目录 coverage-style-detail.png、coverage-style-mobile.png。

## 发布信息

- 镜像：easy-tdx:coverage-style-20261005。
- 镜像 ID：sha256:85021039bf8d6b4a50b102aacc1b02f32d5b3f72002fd2faab583f5b7aabe572。
- 线上 https://tdx.bowenv.com/chanlun 验收通过：容器 running / healthy，三处 HTML 与七项资源一致，登录保护正常。
- 配置、端口、安全设置、数据卷及 256 个后端模块未改变；账户／策略数据库完整性及与备份逐字节核对通过。
- 发布目录：/home/opc/apps/easy_tdx-release-20261005-coverage-style。
- 数据备份：/home/opc/backups/tdx-20261005-coverage-style/data.tar.gz。
- 发布包 SHA256：e2a8cabd7b58433397dbaae720bf61185c0477b1c4cf06aa06db20dc85ac96fd。
- 上一版本：easy-tdx:recursion-style-20261005。
- 暂停的文档分析未恢复。

回滚命令（不覆盖用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-recursion-style/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-recursion-style/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
