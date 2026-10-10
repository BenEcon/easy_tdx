# 研究审核层级缩进 · 2026-10-05

## 范围

- 走势分解审核及下方七个研究区块统一父级标题、子级记录、展开依据的层级缩进。
- 桌面每级 20px；760px 以下 10px，380px 以下 8px。深层 disclosure 限制累计缩进。
- 沿用现有字体、配色、展开箭头和轻分隔；无需新增厚边框或嵌套卡片。
- 包含此前已完成的“最近的线段”可折叠、默认收起。
- 未更改后端、缠论计算、确认规则或账户数据。

## 验证

- 前端 189 项测试通过；vue-tsc 与 Vite 生产构建通过（保留既有 bundle size 警告）。
- Playwright 真实应用、模拟行情：七个区块缩进、展开依据、键盘 Enter 折叠、最近线段默认收起通过。
- 320、390、768、1280px 页面和受测面板无横向溢出；页面无 JS 异常。
- 脚本：`output/playwright/research-indent-check.js`；截图同目录 `research-indent-*`。

## 部署

- 版本：`easy-tdx:research-indent-20261005`
- 镜像：`sha256:d829ec5a909637eeadce2c957301f2cbc17b663b5aa263f5ab005c33d6199323`
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-research-indent`
- 前版：`/home/opc/apps/easy_tdx-release-20261005-structure-hover`
- 数据备份：`/home/opc/backups/tdx-20261005-research-indent/data.tar.gz`
- 包 SHA256：`f3520f12cde727cdd5b44418c6ce9a190152b80ac124f90768d377ca9fd70c75`
- 容器健康、三个公网 HTML 入口、七个前端资源校验通过；256 个后端模块未变，账户与策略数据库完整且与停机备份字节一致；登录保护正常。

回退仅切换前版镜像，保留当前数据卷：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-structure-hover/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-structure-hover/release-image.yaml up -d --no-build --pull never easy-tdx
```
