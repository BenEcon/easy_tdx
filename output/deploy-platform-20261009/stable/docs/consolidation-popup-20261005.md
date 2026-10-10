# 盘整矩形右键详情

- 右键命中三笔盘整矩形后显示紧凑浮动详情：盘整序号、确认／进行中状态、重叠价格、起止时间及来源笔。
- 多矩形重叠时默认选择后绘制的区间，面板内可切换命中的盘整。
- 矩形外不拦截浏览器右键菜单；点外部、关闭按钮或 Esc 收起面板。图层、分析结果、缩放或图表尺寸变化会关闭旧面板。
- 图表下提供“查看盘整详情”按钮，供触屏及键盘使用。采用顶层 popover，支持图表全屏；尺寸和位置限制在视口内。
- 按 sidebar-dialog-ux 技能采用非模态短详情面板，不添加常驻侧栏，不阻断图表研究。继续明确“三笔价格重叠不等同于中枢”。不修改计算规则。

## 本地验收

- 185 项 Node 测试、vue-tsc 类型检查、生产构建、git diff --check 通过。
- 浏览器通过实际 App 路由及合成数据验证右键命中、重叠切换、外部右键菜单、Esc、外部点击、图层变更、键盘入口与全屏。
- 320、390、768、1280 宽度的面板均位于视口内，页面无横向溢出。
- 脚本：output/playwright/consolidation-popup-check.js；桌面与手机截图同目录 consolidation-popup-desktop.png、consolidation-popup-mobile.png。
- 弹窗采用显式关闭逻辑，不监听页面滚动关闭，避免浏览器滚动定位与右键打开的时序冲突。

## 发布记录

- 镜像：easy-tdx:consolidation-popup-20261005。
- 镜像 ID：sha256:e63b2fed42d10b8d4501231300a356ed2444c4abf16f41c7616cd46758fe3f36。
- 发布目录：/home/opc/apps/easy_tdx-release-20261005-consolidation-popup。
- 数据备份：/home/opc/backups/tdx-20261005-consolidation-popup/data.tar.gz。
- 包 SHA256：9dc95c87ed0371998c51cd890d275b5384daf90d6046003b47d996ee0d62952c。
- 上线验收通过：容器 running / healthy；三个公开 HTML 入口及七项静态资源与发布包一致，登录保护正常。
- 配置、端口、安全设置、数据卷和 256 个后端模块不变；账户与策略数据库完整性校验通过，且与部署前备份字节一致。

回滚（保留现有用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-candle-fill/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-candle-fill/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
