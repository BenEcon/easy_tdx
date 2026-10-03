# 波段核验与规则对照部署（2026-10-02）

已部署至 https://tdx.bowenv.com/chanlun 。本次部署已有的失效证据和三项研究对照，不包含讨论中的 DEA 容差，不改变默认背离规则。

## 发布与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20261002-wave-comparison`。
- 镜像：`easy-tdx:wave-comparison-20261002`。
- 镜像 ID：`sha256:c53e69c97448bd8e253365d6b4f3fda567cc4b06259b98b2d1ce3a59cd7e2a9b`。
- 前一发布：`/home/opc/apps/easy_tdx-release-20261002-wave-axis`，镜像 `easy-tdx:wave-axis-20261002`。
- 停服一致性备份：`/home/opc/backups/tdx-20261002-wave-comparison/data.tar.gz`，目录权限 700、文件 600，已验证可读取。
- 本地上传包：`output/deploy-wave-comparison-20261002.tar.gz`。
- 上传包 SHA256：`d5c9a740b0a33cf5e10ddd02588f65e1af52b2df942cfae740525311e368d608`，服务器解包前已核对。

## 验证

- 实施阶段的 1038 项后端和 154 项前端测试通过；部署前再次运行 63 项相关后端、4 项前端证据测试及生产构建，均通过。构建仅有既有大资源提示。
- 新镜像在断网、只读、无生产数据的临时容器中通过离线验收，之后才备份和切换服务。含 600/800 根窗口真实案例、顶底规则、确认时点、研究对照与严格默认隔离。
- 当前服务 `running / healthy`；三个 Python 模块与发布材料逐字节匹配。
- 除镜像外，运行配置、端口、安全限制、数据卷未变。
- 账户及策略库完整性正常，与停服备份逐字节一致；用户和会话无增删、无字段变化。
- 公网首页、登录页、缠论页 HTML 与新构建匹配；入口、缠论、指标及图表资源哈希一致。入口为 `index-BXBsRR79.js`，缠论模块为 `ChanlunView-CTkkoeFW.js`。
- 公网账户权限、多周期研究接口通过。真实回放验证 300450 两组确认日期不变；601698 的 9 月 22 日首次 DEA 失效证据正确，9 月 17 日三项研究对照分别不通过／通过／通过，默认严格规则仍拦截。
- 本机 HTTPS 验收曾遇分块传输中断、一次 SSH 连接断开；重连后由服务器通过同一公网 HTTPS 域名完成全部验证。未修改代理或应用配置规避问题。
- Linux 解包忽略 macOS 扩展属性提示，内容哈希核验正常。

## 回退

保留了旧镜像、旧发布目录和数据备份。应用回退命令：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261002-wave-axis/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261002-wave-axis/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

回退沿用当前用户数据，不自动覆盖发布后新增数据。刷新页面并重新查询可取得新核验信息。
