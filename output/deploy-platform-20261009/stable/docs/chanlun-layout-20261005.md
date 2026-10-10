# 缠论周边区块第三轮排版优化（已部署）

## 范围

- 三笔盘整提取为独立展示组件：统一折叠标题，单列“不等同于中枢”的边界，按区间时间、重叠价格、来源笔、确认状态对齐。确认与末笔待确认不混淆，保持原有图层开关和数据顺序。
- 根据区块实际宽度切换紧凑分组布局，不仅依赖整个浏览器宽度。价格保留两位，来源笔仍使用一基编号。
- 数据口径采用同一折叠样式；窗口、参数、采集时间独立排列，复权不一致警告继续完整显示。
- 摘要去掉八个小卡片，改为轻分隔的数值网格；去掉工作区背景网格。
- 笔、基础中枢、线段提高文字可读性，取消长日期省略，线段卡片改为轻分隔列表；窄内容区域改为单列。
- 背离核验标题接入共享样式；买卖点和背离事件调整标签、日期、状态、正文及依据层次，保留所有操作。
- 展示日期不做时区转换，仅省略日线午夜后缀、替换日期与时间之间的 T；分钟数据保留秒级精度。

按照 frontend-skill 的阅读层级、减少嵌套卡片和响应式原则实施。未改变计算规则、请求流程、默认图层或历史状态。暂停的文档分析未恢复。

## 验证

- 173 项 Node 测试通过（新增日期展示回归），vue-tsc 和生产构建通过；保留既有 ECharts 大包提示。
- Playwright 实际进入 App /chanlun，加载全站及 mobile.css；拦截 API 返回明确的合成版式数据，不接触线上账户。
- 320、390、768、1280 宽度，无页面横向溢出，三笔盘整自身 scrollWidth 等于 clientWidth；另检查 1440 桌面截图。
- 验证 4 组盘整、已确认／末笔待确认、键盘展开收起、数据口径、线段依据展开、手机长文事件，无页面脚本异常。
- 此次为样式验收，不重新验证行情和金融计算。
- 可复用脚本：output/playwright/chanlun-layout-check.js；截图同目录 chanlun-layout-*.png。测试数据不进入 src/public 或生产包。

## 部署记录

2026-10-05 按用户授权发布到 https://tdx.bowenv.com/chanlun 。

- 当前镜像：`easy-tdx:chanlun-layout-20261005`
- 镜像 ID：`sha256:9d7fa5e5d9afc58395099433f7af99f14f2cee363700981195fcc35509b36ea1`
- 发布目录：`/home/opc/apps/easy_tdx-release-20261005-chanlun-layout`
- 一致性数据备份：`/home/opc/backups/tdx-20261005-chanlun-layout/data.tar.gz`
- 上一版本：`easy-tdx:research-polish-20261005`
- 本地发布包：`output/deploy-chanlun-layout-20261005.tar.gz`
- 发布包 SHA256：`123e759ee2050ef9a5c308071b89092f4a9ab3e6ac786fb3743d1afd6b87aedf`

部署前再次通过 173 项测试、类型检查、生产构建及差异检查。服务运行且健康；公网首页、登录页、缠论页及关键 JS/CSS 与本地发布包一致；登录保护正常。256 个后端模块、运行配置、端口、安全限制、数据卷均未改变。账户和策略数据库完整性及停服备份字节校验通过。

回滚应用（不覆盖部署后的用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-research-polish/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-research-polish/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
