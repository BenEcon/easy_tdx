# 三类波段与特殊 A 段指标极值部署（2026-10-03）

已上线 https://tdx.bowenv.com/chanlun 。包含标准、非标准及特殊波段独立标记；特殊波段以 B 新价格极值当根 DIF/DEA 比较前一完整 A 段各自指标极值，保留轴侧检查和反向成笔确认。原最近局部极值双线记录独立保留。

## 发布与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20261003-special-a-extrema`。
- 镜像：`easy-tdx:special-a-extrema-20261003`。
- 镜像 ID：`sha256:767f59113bd20cbf9d10ebab535b21a132a82c6a169296582b718c18753a51b7`。
- 前版目录：`/home/opc/apps/easy_tdx-release-20261002-dea-tolerance`，前版镜像仍保留。
- 停服一致性备份：`/home/opc/backups/tdx-20261003-special-a-extrema/data.tar.gz`；目录 700、文件 600，压缩包可读。
- 发布包：`output/deploy-special-a-extrema-20261003.tar.gz`。
- 上传校验 SHA256：`0a9a7719f951f56deeacad26b4952591bb4d0e37c668c23311c905d50b071fda`。

## 验收

1. 使用上一版固定镜像为基础，只更新应用源码和生产前端资源；未安装依赖、改端口、改认证配置或改数据卷。
2. 本地以及服务器新镜像隔离容器均通过离线案例验收：A 价格、DIF、DEA 极值在不同日期的顶底镜像；零轴检查；反向笔前不确认；原双线不被放宽；603936 和 603259 固定行情案例。
3. 正式服务 running / healthy，256 个 Python 模块与发布源文件逐字一致；除镜像外运行配置、安全限制及数据卷不变。其他既有容器保持运行。
4. 账户库与策略库完整性正常，检查时二者与停服备份逐字节一致。
5. 经正式 HTTPS 域名验证首页、登录页、缠论页及新入口/缠论资源内容匹配：`index-nEkfMe3e.js`、`ChanlunView-DZEr-2AM.js`。现有账号设置保留，账户接口仍要求登录。
6. 经正式 HTTPS 回放：603936 60 分钟 23.76 特殊顶背离为候选；A DIF 峰值日期 9 月 15 日 11:30，DEA 峰值日期 9 月 16 日 11:30。603259 30 分钟 159.47 非标准底背离于 9 月 30 日 10:00 确认，标准版仍未确认，非标准保留 DEA 完整 ABC 零轴检查。
7. 本机 Python HTTPS 验证曾遇连接中断；服务器经正式域名完整复验通过，本机改用 curl 再验证缠论页取得新入口。未修改访问控制。没有登录用户浏览器或修改个人偏好。

## 回退

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261002-dea-tolerance/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261002-dea-tolerance/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

回退继续使用现有用户数据，不自动覆盖发布后的新增记录。重启可能使旧临时研究检查点失效，必要时重新运行研究。
