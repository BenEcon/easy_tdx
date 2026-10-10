# 对象详情悬停开关 · 2026-10-05

## 交互

- 左侧图层下新增“悬停显示对象信息”，复用现有侧栏开关与紧凑说明。
- 默认关闭（旧账户无此偏好也为关闭）；按账户保存 `chanlun_workspace.objectHover`，主图、行业、对照图共享。
- 开启：保留原悬停预览、点击/右键固定，日期卡激活时仍优先跟随日期。
- 关闭：普通悬停和左键不打开对象详情；右键固定，Command + 鼠标移动临时预览。松开 Command/窗口失焦隐藏未固定预览，右键固定面板不受松键影响。
- 关闭时左键仍可激活普通蜡烛日期信息卡，不改其点击后跟随、点击外部关闭的机制。
- 开关切换时关闭已有对象面板，清除悬停状态；按钮明确查看入口仍保留，支持手机和键盘。
- 适用于买卖点、背离/背驰（含失效记录）和盘整矩形，不改识别规则。

## 验证及恢复

- vue-tsc/Vite 构建与 206 项前端测试通过。
- `output/playwright/object-hover-check.js`：默认、四类对象、左键/右键、Command 按下移动/松开、固定保留、切换关闭、偏好刷新恢复、手机明确入口通过。
- `output/playwright/signal-popover-check.js`：开启后原有六类买卖点、M1、悬停/固定、日期卡优先、键盘/手机/文本转义回归通过。
- 截图：`output/playwright/object-hover-control.png`、`object-hover-mobile.png`。
- 本地恢复归档：`output/research-workspace-20261005/before-object-hover-option.tar.gz`。

## 发布

- 发布包 `output/deploy-object-hover-20261005.tar.gz`，SHA-256 `a4e5ae00b1238832f0a0078c1e6346627809466cde7425917648c87d60370c8d`。
- 发布目录 `/home/opc/apps/easy_tdx-release-20261005-object-hover`。
- 数据备份 `/home/opc/backups/tdx-20261005-object-hover/data.tar.gz`。
- 仅替换前端，上一版 `easy-tdx:time-link-20261005` 保留。
- 已部署，容器 `running / healthy`；镜像 ID `sha256:61175b37b3898ef62467a5c2667807c71adec9faf73eb835a59d5a30b189766d`。
- 公网三个 HTML 入口、七项关键资源、登录保护通过；256 个后端模块未变，账户与策略数据库完整并与停机备份字节一致。

回退（保留当前数据卷）：

```sh
sudo docker compose -p easy_tdx -f /home/opc/apps/easy_tdx-release-20261005-time-link/compose.yaml -f /home/opc/apps/easy_tdx-release-20261005-time-link/release-image.yaml up -d --no-build --pull never easy-tdx
```
