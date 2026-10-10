# 局部确认与非标准价格规则部署记录

日期：2026-10-04。用户授权：部署到服务器。

## 版本与恢复点

- 地址：https://tdx.bowenv.com/chanlun
- 规则版本：`2026100414`
- 新发布目录：`/home/opc/apps/easy_tdx-release-20261004-local-confirmation-14`
- 镜像：`easy-tdx:local-confirmation-20261004-14`
- 镜像 ID：`sha256:c82840ec7bfbbc87cce82825feaebdca1d7fbac28f228848bd58da4973bff23a`
- 上一版目录：`/home/opc/apps/easy_tdx-release-20261004-indicator-rules`
- 一致性数据备份：`/home/opc/backups/tdx-20261004-local-confirmation-14/data.tar.gz`，停服务后创建，目录权限 700、文件权限 600。
- 本地发布包：`output/deploy-local-confirmation-20261004-14.tar.gz`
- 发布包 SHA256：`4cb18c43320eb98d7720f1f399dffc5767b6d73d9fc3b9e61fb89e4e69115c0c`

## 验证

新镜像先在禁用网络、只读文件系统、未挂载生产数据的隔离容器中测试，通过后才备份并切换。

- 服务 `running healthy`。
- 运行配置、安全限制、端口、数据卷与上一版一致，仅更换镜像。
- 部署的源码哈希与发布包逐一匹配。
- `accounts.db` 与 `strategies.db` 完整性正常，字节哈希与停机时备份一致。
- 隔离镜像通过三组 15 分钟局部反向笔正例、两个间距不足失效反例、非标准 C 未达到 A 价格极值的确认例。
- 公网首页、登录页、缠论页面以及入口和缠论 JS/CSS 与本地构建一致；账户接口保持登录保护。
- 公网回放验收脚本：`output/deploy-local-confirmation-20261004-14/verify_public.py`。
- 公网回放全部通过：603936 60 分钟、603259 30 分钟旧例，以及 603936 15 分钟 9/15 13:45、002821 15 分钟 9/14 13:15 和 9/18 11:00 的新局部确认日期；特殊与原双线依据分别验证，规则版本与局部确认证据正确。

## 回滚

仅回滚应用镜像，保留当前数据卷；不要用旧备份覆盖部署后产生的用户数据。

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261004-indicator-rules/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261004-indicator-rules/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

没有修改 nginx、登录配置或其他服务；没有进行新的公网浏览器视觉验收，本次视觉验收沿用部署前的本地真实组件测试。
