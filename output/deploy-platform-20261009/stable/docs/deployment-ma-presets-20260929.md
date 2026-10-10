# 可选 MA 均线 · 2026-09-29

缠论侧栏补齐 MA5、MA10、MA20、MA30、MA60、MA120、MA250（此前缺 MA250）。默认只启用 MA5 和 MA10，其余关闭；“均线系统”继续默认折叠。选项显示实际 MA 周期而非序号，可继续手动修改周期。沿用既有黄、白、紫、绿、青、橙、红配色，个股和行业图共享启用设置。保留上一版笔/线段线宽功能，未修改算法或账户接口。

前端构建及 138 项测试通过，新增测试覆盖全部周期、默认可见性、独立设置对象及颜色映射。保留已有大包警告。

发布后容器 `running / healthy`；公网 HTTPS 页面返回新入口，入口和缠论模块与本地已测试构建逐字节一致。

发布记录：

- 目录：`/home/opc/apps/easy_tdx-release-20260929-ma-presets`
- 镜像：`easy-tdx:ma-presets-20260929`
- 镜像 ID：`sha256:4985124b6b182846765a1186dbb5a5ead43be8a5bbdd4c4d5d09c645d40993a9`
- 发布包 SHA-256：`c49312fc5e2ec948ad9e28c82831ce9e3db06f0f1fa1579c6c395174e26b6ca6`
- 数据恢复点：`/home/opc/backups/tdx-20260929-ma-presets/data.tar.gz`，停服后备份，权限 600。
- 本地发布文件：`/Users/bowen/Documents/Python/Google/TDX-deployments/20260929-ma-presets`
- 入口：`index-HN2NTLhq.js`，缠论模块：`ChanlunView-DbTsMhtC.js`。

使用上一版镜像叠加静态资源，沿用正式数据卷及其他配置，保留旧哈希资源。健康检查失败自动回退。重启后既有临时研究检查点需要重新搜索。

手动回退应用（不覆盖在线用户数据）：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260929-line-width/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260929-line-width/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```
