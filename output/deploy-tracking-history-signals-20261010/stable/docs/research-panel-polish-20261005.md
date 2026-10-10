# 研究区块第二轮精修（已部署）

基于已上线的 `easy-tdx:research-style-20261005`，进一步优化展开内容，不改分析规则和数据请求。

## 调整

- 折叠标题减轻高度，展开增加细弱的状态边线；标题、摘要、说明与结果拉开视觉层次。
- 观察周期采用等宽多选项，保留原生 checkbox 的键盘和无障碍语义；隐藏系统勾选框外观，用一致的选中背景与勾号展示。增加已选周期数。
- 参数与操作按钮分组，手机布局明确分成参数与操作两行，不挤压控件。
- 对照表以标签／数值对齐展示均线、成交量和 MACD；支持固定表头、固定周期列及独立滚动。背离类型与日期分行，信息保持完整。
- 观察与分歧按周期归组，重复周期标题只显示一次，政策说明保留为末尾注释。
- 分解审核各行的序号、角色、来源、归属状态按列对齐；价格范围、可知时间、关联中枢独立字段展示。
- 回放按钮采用紧凑成组样式，保留原有两项操作、禁用条件和事件；窄屏标签另起一行。
- 完善初始提示与等待提示，错误仍保留显式提示和重试入口（原更新按钮）。

## 验收

- `MultiPeriodResearch.vue` 和 `DecompositionInspector.vue` 的 script 内容与 HEAD 完全一致，未修改分析与请求逻辑。
- 172 项 Node 回归、TypeScript 检查及生产构建通过。
- Playwright 使用真实 Vue 组件，模拟行情和研究响应：三周期结果、八周期长表格、键盘多选、取消全部后的禁用、JSON 快照导出、分解回放事件、键盘展开／收起均通过。
- 320／390／768／1280 像素宽度，全部外层研究面板展开时无页面级横向溢出；表格横向和纵向滚动后，表头及周期列位置正确。
- 工程走势提供一条模拟已完成记录，验证展开后的数值、来源和回放布局；其他递归面板以空态检查外层布局，不重新验算金融规则。
- 减少动态效果验证按 transition-property 为 none、时长小于 1ms 判断（站点全局将时长设为 0.01ms）。模拟 503 错误显示正常且可重试；预期的 503 请求为唯一控制台错误。
- 临时验收页已删除，未进入构建。截图：`output/playwright/research-polish-desktop.png`、`research-polish-mobile.png`、`research-polish-detail.png`。

## 部署记录

2026-10-05 按用户授权发布；镜像 `easy-tdx:research-polish-20261005`，ID `sha256:3ba27d8f3e5152b704a99b7f7192e256e3f63bbb3c0bfa230d483eda8659512e`。容器运行且健康。

- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-research-polish`
- 一致性数据备份：`/home/opc/backups/tdx-20261005-research-polish/data.tar.gz`
- 上一版本：`easy-tdx:research-style-20261005`
- 本地发布包：`output/deploy-research-polish-20261005.tar.gz`
- 发布包 SHA256：`9154a7b80a2280556a8bf213d9951aa30d248a15a587c78b4ed65a7af21c1ac1`

部署前再次通过 172 项测试、类型检查、构建及差异格式检查。部署后公网首页、登录页、缠论页及入口／图表 JS、CSS 与发布包字节一致；运行配置、端口、安全限制和数据卷未变化；256 个后端模块未改变；账户及策略数据库完整性检查通过且与停服备份字节一致；登录保护正常。

回滚只切换应用，不覆盖用户新增数据：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-research-style/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-research-style/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

暂停的文档分析不受影响，未纳入本次发布。
