# 指数／板块缠论与图表交互发布

日期：2026-10-05（北京时间）。用户授权：暂停《2026.10.4.docx》，完成其余任务并部署。

## 本次范围

- 指数／板块独立缠论入口、市场身份、目录搜索、不复权行情；接入现有分析、指标、回放和多周期研究。
- 普通 K 线与缠论图的信息卡默认隐藏，点击才显示；点击图外、按 Escape 或更换数据后隐藏。
- 中枢和线段默认关闭；显示失效历史默认开启。
- 多周期研究仅使用共同截止前的完整行情前缀，未收盘柱及后续数据不参与。
- 文档衍生的 MA 排列历史、发展笔、跨周期修复事件等扩展已移出工作副本及发布。保留生产原有多周期观察，不改正式结构及 M1 门槛。

文档工作保存在 `output/backups/paused-document-20261004-work.tar.gz`，SHA256 `362026f8a392b1b6403757c9ec875e4e5bc66bee3a13403a88bf59da171db397`。恢复时解压到独立目录并比较合并，不直接覆盖当前代码。

## 版本和恢复点

- 网站：https://tdx.bowenv.com/chanlun
- 最终发布目录：`/home/opc/apps/easy_tdx-release-20261005-instruments-v2`
- 镜像：`easy-tdx:instruments-20261005-v2`
- 镜像 ID：`sha256:f370ac5e49ec0f45fdc9bbed4914b80b132fce902504283c5409ba49957e0b8c`
- 前一发布目录：`/home/opc/apps/easy_tdx-release-20261004-local-confirmation-14`
- 规则版本仍为 `2026100414`。
- 停服一致性数据备份：`/home/opc/backups/tdx-20261005-instruments-v2/data.tar.gz`，目录700、文件600；首版备份目录 `tdx-20261005-instruments` 也保留。
- 本地最终发布包：`output/deploy-instruments-20261005-v2.tar.gz`
- 发布包 SHA256：`6c5e3242feccd0868264125e8dc1dce03b146a6f0f17c2d2cf3d1e98df03326b`，上传后与服务器一致。

## 已完成验证

- 前端类型检查及生产构建通过；Node 测试170项全部通过，仅既有大chunk警告。
- 后端相关回归160项全部通过（204.34秒），仅 Starlette/AnyIO 弃用提示。
- 生产首次真实验收发现标准指数接口返回空行情，MAC 显式 SH000001 实测可返回上证指数；V2 改为 MAC 优先、标准指数命令备用，保留 NONE 和显式市场身份。新增3项路由回归，最终行情／行业／观察相关33项通过。日线快照经前端统一 date→datetime 后送回放，测试亦按此契约处理。
- 三组冻结快照的标准事件、结构笔及源哈希不变。
- 与前一已发布后端源码相比，仅 `routers/bars.py` 和 `routers/chanlun_observations.py` 变化，核心判定代码一致。
- 新镜像在无网络、只读、未挂载生产数据的隔离容器中通过指数／板块路由和既有冻结确认案例。
- 容器 `running healthy`；运行配置、安全限制、端口与数据卷不变。
- 256个部署 Python 模块哈希匹配发布源码。
- 账户和策略数据库完整性正常，并与停服备份字节哈希完全一致。
- 公网首页、登录页、缠论HTML及入口／缠论JS、CSS均与本地发布构建一致。

公网行情和回放验收使用 `output/deploy-instruments-20261005-v2/verify_public.py`；本机公网连接偶发断开，最终从服务器请求公网域名验收。脚本对临时连接错误最多重试3次，不改变运行应用。

最终公网全部通过：SH000001、SZ399001、SZ399006 日线各200根，SH000001 30分钟200根，行业881106及概念880710日线各200根，均完成真实行情→缠论回放；不支持的指数120分钟正确返回422。603936/603259旧回放及603936、002821三组局部确认时间均保持正确。V2账户和策略数据库仍与本次停服备份字节一致。

## 回滚

只回滚应用镜像，保留当前数据卷，避免覆盖部署后用户新增的数据：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261004-local-confirmation-14/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261004-local-confirmation-14/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

未修改 nginx、登录方式、用户角色或其他服务。暂不支持的指数120分钟明确报错，不伪装为其他周期。
