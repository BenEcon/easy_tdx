# DEA 容差独立对照部署（2026-10-03）

已上线 https://tdx.bowenv.com/chanlun 。严格版保持不变，仅新增第四项 5% DEA 容差研究对照，不生成正式信号。

## 发布及恢复

- 发布目录：`/home/opc/apps/easy_tdx-release-20261002-dea-tolerance`。
- 镜像：`easy-tdx:dea-tolerance-20261002`。
- 镜像 ID：`sha256:28717addde1d0dc1a4c775bef0843ee1e265df723732dc412f2b976c8858e590`。
- 前一发布：`/home/opc/apps/easy_tdx-release-20261002-wave-comparison`；镜像 `easy-tdx:wave-comparison-20261002` 保留。
- 停服一致性备份：`/home/opc/backups/tdx-20261002-dea-tolerance/data.tar.gz`，目录 700、文件 600，已检验可读。
- 本地发布包：`output/deploy-dea-tolerance-20261002.tar.gz`。
- SHA256：`cf6b13724b47661c0dd09d2aa149a6f093275b63870496d81cbc59a18f075de4`，上传后再次核对。
- 发布文件后缀沿用工作开始日，实际完成为北京时间 10 月 3 日。

## 上线验证

1. 本地 1064 项相关后端、155 项前端测试和生产构建通过。服务器新镜像在无网络、无生产数据、只读临时容器内再次通过离线案例验收，之后才停止旧服务、备份和切换。
2. 新服务 running / healthy；运行配置、安全限制、端口、数据卷除镜像外未变；三个源模块内容与发布材料一致。
3. 账户和策略库完整性正常。策略库与停服备份逐字节一致。账户库仅运行期间 preferences、updated_at 变化，用户身份、凭据、角色未变，会话无增删或修改，未覆盖用户的新偏好。
4. 公网首页、登录页、缠论页 HTML 及主要资源与新构建匹配。入口 `index-BLoA6tkq.js`、缠论模块 `ChanlunView-CrRNUr3q.js`。
5. 公网账户权限、多周期接口及真实回放通过。300450 原有确认日期未变。601698 的 9 月 22 日严格失效保留、5% 对照通过；9 月 7 日、9 月 10 日对照仍失败。全部只作研究，不生成 M1。

## 回退

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261002-wave-comparison/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261002-wave-comparison/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

回退继续使用当前用户数据，不自动覆盖发布后新增数据。
