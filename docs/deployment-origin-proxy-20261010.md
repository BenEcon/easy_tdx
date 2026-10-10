# HTTPS 同源误拦截修复 · 2026-10-10

## 已部署范围

仅修复生产 Compose 的可信代理配置，不改应用代码、前端包、缠论规则或数据库，不发布本地正在实现的因子库。

- 镜像仍为 `easy-tdx:tracking-history-signals-20261010`，ID `sha256:936c3f3a821773aba7162c02c95b6e7d223e93e2d69001d0446dda99ac29094e`。
- 原部署目录 `/home/opc/apps/easy_tdx-release-20261010-tracking-history-signals`。
- 仅新增 `FORWARDED_ALLOW_IPS: "127.0.0.1,::1,172.22.0.1"`。
- 应用端口仍只绑定主机回环 `127.0.0.1:18002`；数据卷仍为 `easy_tdx_data`。
- Nginx 配置不变，沿用覆盖设置的 Host 和 X-Forwarded-Proto，不扩大允许来源、不使用通配符。

## 原因与验证

Nginx 通过 Docker 网关 `172.22.0.1` 访问服务。应用默认仅信任回环地址，故忽略 X-Forwarded-Proto=https，将站点请求误判为 HTTP 来源。正常公网同源 POST 实测403，与用户截图及生产请求日志一致。

已发布基线的单元及真实回环代理边界测试66项通过（第三方库弃用警告6条，无测试失败）。修复后：

- 公网 `/api/v1/research/factors/compute`，Origin=`https://tdx.bowenv.com`、空请求且无cookie：401「请先登录」，证明通过来源门禁且仍要求认证。
- 同端点 Origin=`https://untrusted.invalid`：403，来源防护保留。
- 直连反代侧相同边界检查通过；容器 `running healthy`，健康探针 ExitCode=0。
- `/api/v1/auth/status` 的 `setup_required=false`，未重置账户；未创建生产测试账户或读取用户会话。
- 未代替用户进行带身份的实际因子计算；请刷新后在原登录会话验证。

## 恢复与后续发布

配置备份目录 `/home/opc/backups/tdx-20261010-origin-proxy`（700），包含原 compose.yaml 和 release-image.yaml。恢复仅还原 compose.yaml 并用原两份 Compose 文件重新 up，不覆盖用户数据。

原Compose SHA256 `6e43b3a8bcf95574e08ad16b4a11e291b79bbbb299b8ae7183c5b76c406a77d6`；新Compose SHA256 `f948b0eb33797caa5dd6de9bf419f8db47d6d0eaf2b035832808ef1efcd2cb6f`。

本地修复包及部署日志：`output/deploy-origin-proxy-20261010/`。后续发布应以现行生产Compose为基线保留此设置；Docker网络重建时核实实际代理网关，不盲目沿用或改成通配符。
