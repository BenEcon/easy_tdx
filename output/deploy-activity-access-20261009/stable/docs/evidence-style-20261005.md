# 确认依据阅读布局优化（已部署）

## 范围

- 移除“历史对照”前的装饰竖线，保留标题、旧解释提示和全部使用边界。
- 线段、基础中枢、结构信号依据共用 EvidenceReading；短字段标签与内容对齐，长叙述单独显示。仅按首个全角冒号切分短标签，所有字符可原样还原，不改变时间、数字或判断。
- 最近线段采用纵向列表，避免两列展开造成大块空白；桌面价格靠右，窄屏自然换行。
- 统一依据展开箭头、焦点、减少动画设置及回放操作区；候选线段提示、连接状态改为低饱和色与轻量布局。
- 保留确认所需最后一笔、特征来源、反向特征以及原有确认回放事件。未改计算、确认或递归规则。
- 前端设计技能用于减少装饰、统一阅读层次；Playwright 技能用于实际浏览器交互验收。

## 验收

- 180 项 Node 测试通过，新增两项字段完整性测试，覆盖次级冒号、时间、缺失依据提示、长标题和空内容。
- 类型检查、生产构建、git diff --check 通过；既有 ECharts 体积提示不变。
- 真实 App 路由使用合成数据验证无缺口、缺口、特殊包含及缺少依据四类显示；历史对照左边框为 0px。
- 320、390、768、1280 宽度下，页面及依据区无横向溢出，无页面脚本错误；1440 桌面和手机截图人工检查通过。
- 键盘展开／收起正常；线段 3 确认回放发送 visible_count=51，与合成 confirmed_index=50 一致。
- 测试脚本 output/playwright/evidence-style-check.js；截图同目录 evidence-style-proof.png、evidence-style-mobile.png、evidence-style-history.png。
- 初次合成归属数据缺字段导致测试失败，补齐 fixture 后复测通过；未以生产代码绕过核验。

## 发布

- 镜像 easy-tdx:evidence-style-20261005。
- 镜像 ID：sha256:89ed045abd7120d74dab52e6ea9daaf9abfb19398a77a798e787f94b9fb2a0cf。
- https://tdx.bowenv.com/chanlun 已上线，容器 running / healthy；三处公网页面及七项前端资源校验通过，登录保护正常。
- 配置、端口、安全设置、数据卷及 256 个后端模块未改变；账户和策略数据库完整性、备份字节一致性检查通过。
- 发布目录 /home/opc/apps/easy_tdx-release-20261005-evidence-style。
- 备份 /home/opc/backups/tdx-20261005-evidence-style/data.tar.gz。
- 发布包 SHA256：68e6df3dc5562549d6b67a905c14cae6aba36efcbf681b46665ae4c02d2d1862。
- 上一版本 easy-tdx:coverage-style-20261005；暂停的文档分析未恢复。

回滚命令（不覆盖用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261005-coverage-style/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261005-coverage-style/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
