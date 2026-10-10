# 研究说明文字排版优化（已部署）

## 调整范围

- 按 frontend-skill 的文字层级和克制布局原则，将说明拆成语义化定义列表，正文使用统一行距、段距、色阶、有限阅读宽度和中文两端对齐。
- “计算口径与参数说明”分为数据范围、快照与预热、指标参数、对照窗口；MA、MAVOL、MACD、BOLL 参数独立对齐，不改变值和计算窗口。
- “延伸升级核验”区分核验输入、层级含义、排除项；具体升级证明中的时间、来源、子区间和外围独立排列。
- “工程走势递归”保留“旧解释”标识，历史用途单独展示；完成条件、递归层级、实际确认与使用边界分层阅读。
- 高层中枢进程使用相同的文字布局，空状态与边界限制保留。
- 细小箭头和悬停反馈辅助展开，支持键盘焦点及减少动态效果。
- 按实际内容宽度切换上下布局；窄栏标题与回放按钮同步适配，避免只按浏览器宽度判断。

没有改变识别、确认、交易规则、默认图层或请求逻辑，不删除限制条件，不将历史解释改称当前规则。未恢复暂停的文档分析。

## 验证

- 五个组件（MultiPeriodResearch、ExtensionHierarchyInspector、EngineeringTrendInspector、ExtensionProofNode、RecursiveCentreInspector）的 script 与 HEAD 完全一致。
- 173 项 Node 回归通过；vue-tsc、生产构建及差异格式检查通过。保留既有 ECharts 大包提示。
- Playwright 在实际 App /chanlun 中拦截 API 使用合成版式数据；验证参数、升级证明、旧解释、展开依据与键盘操作，不访问线上账户。
- 320、390、768、1280 像素均无页面或本次目标面板的横向溢出；1440 像素桌面截图另存。
- 验收脚本：output/playwright/chanlun-copy-check.js。截图：同目录 chanlun-copy-parameters.png、chanlun-copy-extension.png、chanlun-copy-engineering.png、chanlun-copy-mobile.png。
- 合成数据仅用于界面验收，不是金融计算验证，也不包含在生产源码或 public 目录。

## 部署记录

2026-10-05 按用户授权发布到 https://tdx.bowenv.com/chanlun 。

- 当前镜像：`easy-tdx:research-typography-20261005`
- 镜像 ID：`sha256:6bb7959a40c421cbb8ec8f7fbd7ad0e93a242d3e513d1cd05df12a19270c7019`
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-research-typography`
- 一致性备份：`/home/opc/backups/tdx-20261005-research-typography/data.tar.gz`
- 上一版本：`easy-tdx:chanlun-layout-20261005`
- 本地发布包：`output/deploy-research-typography-20261005.tar.gz`
- 发布包 SHA256：`304594d2dc9b8e44669497d50563e4505c12b6bbdc487caa8e4f3e8a5853b11f`

发布前再次通过 173 项测试、类型检查、构建和差异检查。发布后容器运行且健康；公网首页、登录页、缠论页和关键 JS/CSS 与发布包一致；登录保护正常。256 个后端模块、运行配置、端口、安全限制和数据卷未改变。账户、策略数据库完整性检查通过，且与本次停服备份字节一致。

回滚应用（不覆盖部署后的用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-chanlun-layout/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-chanlun-layout/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
