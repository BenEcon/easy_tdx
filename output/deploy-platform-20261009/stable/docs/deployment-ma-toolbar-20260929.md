# MA 图例与回放布局修复 · 2026-09-29

## 问题与修复

前一版仅在折叠侧栏补齐七个 MA 周期，但图表仅为已启用周期创建序列和图例，因此用户在右上角仍只能看到 MA5、MA10。

本版分离“可选周期”和“已启用周期”：图表始终创建全部可选 MA 序列与图例，默认 MA5、MA10 启用，其他以灰色显示但不画线。图例点击向父页面同步，左侧开关、个股及行业两张图使用同一状态。重新绘图时显式覆盖旧 MA 选择，避免旧图例状态覆盖侧栏变更；保持指标图例及缩放状态。全屏同样可直接点击 MA。

“快照末尾”行按 frontend-skill 的紧凑布局分成左右两组：状态、前后步进、伸展滑块靠左，日期、根数、返回末尾靠右；窄窗口自动换行，右组仍贴右对齐。未修改分析、回放算法及数据接口。

## 验证

- 构建与 139 项前端测试通过；原有图表大包警告保留。
- 本机浏览器使用模拟行情和真实页面组件验证：七个 MA 图例、默认隐藏、图例至侧栏同步、侧栏至图表同步、缩放保留、全屏开关、行业至个股同步均通过。
- 1440 px 桌面与 1000 px 窄窗口截图检查；窄窗口回放条没有横向溢出，右组边界与容器一致。
- 模拟数据只存在本机浏览器内存，未写入线上。
- 正式容器 `running / healthy`；公网 HTML 指向新入口，入口脚本、缠论脚本和样式与已测试构建逐字节一致。
- 本机全屏退出/对比布局调整后出现一次 ResizeObserver 通知延迟警告，未影响上述同步断言；本次未改动既有 ResizeObserver 实现。

## 发布与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20260929-ma-toolbar`
- 镜像：`easy-tdx:ma-toolbar-20260929`
- 镜像 ID：`sha256:4ca95eb21a34a40c39f588f45b77a76da6a0dfbc8766b15c68639b239ed93ea3`
- 发布包 SHA-256：`2c6d62bdcfb0af95a3f6a1bda5c243232f497fb0a3ec255f25adddfd50414301`
- 数据备份：`/home/opc/backups/tdx-20260929-ma-toolbar/data.tar.gz`，停服后备份，权限 600。
- 仅叠加前端资源，保留上一版后端、账户、正式数据卷、端口及安全配置。
- 新入口：`index-DQiLZ5T4.js`；缠论模块：`ChanlunView-N7DolmD5.js`；样式：`ChanlunView-BXOx5r-J.css`。

回退应用（不覆盖当前用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260929-ma-presets/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260929-ma-presets/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

重启使旧的临时签名研究检查点失效，需要重新搜索；该既有边界未变。
