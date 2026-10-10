# 2026-10-04 MACD 规则部署记录

已部署到 https://tdx.bowenv.com/chanlun 。

## 发布与备份

- 发布目录：`/home/opc/apps/easy_tdx-release-20261004-indicator-rules`
- 镜像：`easy-tdx:indicator-rules-20261004`
- 镜像 ID：`sha256:32033a91d9031c889308947d3fb55b0053fb6822287e56066fc0fc4f4cc263dc`
- 前一版本：`/home/opc/apps/easy_tdx-release-20261003-special-a-extrema`
- 停服后一致性数据备份：`/home/opc/backups/tdx-20261004-indicator-rules/data.tar.gz`（目录 700，归档 600）
- 本地部署包：`output/deploy-indicator-rules-20261004.tar.gz`
- 包 SHA256：`d31e29c31d3512d5900ac1331bbd809bac6d23cf5225f482a4f8480b58d7ca9f`

沿用前一镜像依赖，仅覆盖应用源码与构建后的前端。端口、认证、安全限制和数据卷配置均未改变，其他容器未重启。

## 验收

- 部署前复测 97 项规则及真实案例测试通过；此前完整相关验收结果见规则文档。
- 新镜像先在无网络、只读、无生产数据挂载的容器中验证 603936、603259、399006 冻结案例，全部通过。
- 服务上线后为 `running healthy`，256 个 Python 模块逐文件哈希与发布包一致。
- accounts.db、strategies.db 完整性检查通过，均与停服时的备份字节一致。
- 公网首页、登录页、缠论页及新版入口、缠论 JS/CSS 哈希核验通过；账户接口仍要求登录。
- 公网回放接口通过：603936 60 分钟，23.76 特殊顶背离确认标签为 2026-09-28 15:00；603259 30 分钟非标准底背离确认标签为 2026-09-30 10:00，完整 A 面积 24.922384899472686。
- 本机再次访问公网缠论页成功，入口为 `index-C0WPOMQN.js`，缠论资源为 `ChanlunView-Bv8CwueM.js`。
- 日期为 K 线标签；行情时间戳起止标签的保守边界限制保持不变。

解包时 Linux tar 忽略了 macOS provenance 扩展属性；内容哈希及后续验收均通过，不影响发布。

## 回滚

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261003-special-a-extrema/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261003-special-a-extrema/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

代码回滚继续使用现有数据卷，不自动用旧数据库覆盖用户后续数据。重启可能令进程内研究检查点失效，需要重新查询。
