# 手机显示兼容优化 · 2026-09-30

## 范围

遵循 frontend-skill 和 sidebar-dialog-ux，保留现有暗色视觉，手机导航改为原生模态抽屉，支持关闭按钮、背景点击、Escape 和切页自动关闭。移除外框最小宽度限制，兼容安全区和短横屏；桌面侧栏保持原样。

缠论设置可折叠，首次查询成功后自动收起。手机 MA 使用可触控按钮，保持七个周期和默认只启用 MA5、MA10，沿用既有同步及颜色。全屏内可以滚动查看全部指标，保留不支持原生全屏时的替代模式。

查询、账户、行情服务器等页面使用紧凑堆叠布局，表格局部横向滚动；F10 分类成为横向标签。输入字体至少 16px，增加按钮及数值步进触控面积。下拉菜单按可见视口定位，处理软键盘和边缘空间；弹窗限制高度并允许内部滚动。

仅修改前端显示和交互，未修改缠论算法、后台接口和账户数据。

## 验证

- TypeScript / Vite 构建成功，141 项前端测试通过；既有 ECharts 大包警告保留。
- Playwright 检查 390px 下 17 个页面，320px、430px 下九个主要页面，以及 844×390 横屏、1440px 桌面。
- 验证导航开关、Escape、切页关闭、桌面恢复、设置折叠、MA 点按以及强制原生全屏失败后的替代模式。
- 测试使用本地模拟接口和浏览器内存行情，未写入线上用户数据；测试夹具形状错误已修正后重测。
- 已检查截图；这些是浏览器尺寸模拟，尚未在实体手机 Safari / Chrome 上验收。
- 正式容器 running / healthy；公网 HTML、入口 JS/CSS 和缠论模块与本地构建逐字节一致。

## 发布与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20260930-mobile`
- 镜像：`easy-tdx:mobile-20260930`
- 镜像 ID：`sha256:7ca1beec28fb8611357f52a4f74bee4a567bef7058ee8ff8e7e141b22181dc02`
- 发布包 SHA-256：`9a9bfede9ae18087120fa552d6dcd5d4941d3bdd99d157423fd60abcd3d30b98`
- 停服数据备份：`/home/opc/backups/tdx-20260930-mobile/data.tar.gz`，权限 600。
- 保留前版后端、正式数据卷、端口、资源限制及安全配置；只叠加前端资源。
- 新入口：`index-oKN6gO_y.js`；样式：`index-C9KypvtL.css`；缠论模块：`ChanlunView-Ck0BJ9Nc.js`。

回退应用（不覆盖当前用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260929-ma-toolbar/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260929-ma-toolbar/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

重启使旧的临时签名研究检查点失效，需要重新搜索；该既有边界未变。
