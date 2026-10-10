# 蜡烛影线居中修复 · 2026-09-30

公共 ECharts 布局扩展将蜡烛实体的左右边缘对称放置在原有影线两侧，避免各自像素取整产生半像素偏移。普通 K 线、扩展市场和缠论图共用；不修改 OHLC 数据、均线或缠论算法。大数据简化线模式保持原样。

## 验证

- TypeScript / Vite 构建成功，146 项前端测试通过。
- 本地 Playwright 模拟数据：普通 K 线与缠论图各覆盖 320、390、430、844、1440px，以及全量、缩放、平移后的 3 个区间，30 组检查的实体中心和影线偏差均为 0；无页面异常。
- 公网 `/`、`/login`、`/chanlun`、`/company` HTML 与本地构建逐字节一致。
- 入口 JS/CSS、公共 ECharts 模块、缠论、普通 K 线、扩展市场 JS/CSS 的 SHA-256 与本地构建一致。
- 正式容器 running / healthy，认证状态接口 HTTP 200，仍要求登录；未操作线上用户账户。

## 发布与恢复

- 发布目录：`/home/opc/apps/easy_tdx-release-20260930-candle-alignment`
- 镜像：`easy-tdx:candle-alignment-20260930`
- 镜像 ID：`sha256:d77df44276c0499fecbb0d9c1e8d306a2aeefbc840e2f96072d88dc050d043ec`
- 发布包 SHA-256：`12164c3644ccaefa85dc7b367119bbdbfb086c7ab25568f5cdd362a165dc7891`
- 停服数据备份：`/home/opc/backups/tdx-20260930-candle-alignment/data.tar.gz`，权限 600，归档可读取。
- 继承上一版运行镜像，只叠加前端资源，保留正式数据卷 `easy_tdx_data`、后端、端口与安全限制。
- 新入口：`index-DU7Ne78N.js`；绘图模块：`echarts-setup-DLA0bxak.js`。

回退应用，不覆盖用户现有数据：

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260930-mobile-site/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260930-mobile-site/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

与既有部署相同，重启会使旧的临时签名研究检查点失效，需重新搜索。
