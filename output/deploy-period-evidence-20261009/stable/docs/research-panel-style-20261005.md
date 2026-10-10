# 缠论研究区块展示优化

范围：多周期研究、走势分解审核、延伸升级核验、工程走势递归、全域走势递归、归属时间轴与分解研究、完整分解搜索与失败追踪、分层归属与内部递归、跨中枢候选核验。

- 统一标题与摘要对齐、展开箭头、内容边距、分隔线、文字层次和焦点状态。采用共享 `research-panels.css`，不叠加装饰卡片。
- 周期选项增加选中状态；参数和操作分组；保留完整计算口径，改为可展开说明。
- 研究表格优化行距、数字和次级信息，周期列固定；窄屏表格独立横向滚动并显示提示。
- 回放操作桌面靠右，手机分为说明与操作两行。
- 保留所有数据、分析函数、请求、事件和确认规则；不更改默认展开状态或触发自动研究请求。

验证：172 项 Node 回归通过；类型检查及生产构建通过。Playwright 使用真实 Vue 组件、模拟研究响应和三条分解记录验收 320、390、768、1280 像素宽度，全部展开时无页面级横向溢出；验证研究按钮、表格滚动、回放事件、Enter 收起和 Space 展开。递归深层结果未重新计算，使用空态验证其外层布局。浏览器唯一控制台错误是临时验收页缺少 favicon，不涉及业务代码。

截图保留在 `output/playwright/research-desktop-data.png`、`research-mobile.png`、`research-all-mobile.png`。临时验收入口已移除，不进入构建。

## 部署记录

2026-10-05 按用户授权部署完成。镜像 `easy-tdx:research-style-20261005`，ID `sha256:58a2c887abc6a650f8376287bbeb9d4530e6218d314f9b5b1ca09aa19b41fc97`，容器运行且健康。

- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-research-style`
- 一致性备份：`/home/opc/backups/tdx-20261005-research-style/data.tar.gz`
- 上一版：`easy-tdx:tooltip-activation-20261005`
- 本地包：`output/deploy-research-style-20261005.tar.gz`
- 发布包 SHA256：`a6c7cf740ff72d5fc79c987e533d6c62ece5802a61f1b99652b59d372431a2ce`

上线前重新通过 172 项测试、类型检查、生产构建和差异格式检查。上线后验证首页、登录页、缠论页以及入口／缠论／K线／共享图表的 JS、CSS 公网字节与本地构建一致。256 个后端模块未改变；配置、端口、安全限制及数据卷不变；账户和策略数据库完整性正常且与停服备份字节一致；登录保护正常。

应用回滚（不覆盖部署后新增数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-tooltip/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-tooltip/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

已暂停的《2026.10.4.docx》分析继续保持暂停，未纳入本次发布。
