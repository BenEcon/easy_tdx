# 2026-10-01 缠论优化部署

已部署至 MathBlog：`https://tdx.bowenv.com/chanlun`。

## 发布版本与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20261001-chanlun-october`。
- 镜像：`easy-tdx:chanlun-october-20261001`。
- 镜像 ID：`sha256:26690b334aceb8781e2d44aecd881fd11fe330ef721d3e49bdc04be72d0d9365`。
- 发布包 SHA256：`ff705d6d81b112016e4e44c262809cbc70ce5f9740c9856cc33218649a184521`。
- 停服一致性备份：`/home/opc/backups/tdx-20261001-chanlun-october/data.tar.gz`，目录权限 700，数据包权限 600，已检查可读取。
- 上一版本：`easy-tdx:candle-alignment-20260930`，镜像 ID `sha256:d77df44276c0499fecbb0d9c1e8d306a2aeefbc840e2f96072d88dc050d043ec`。

继承上一版运行环境，仅叠加本次 9 个后端模块及前端构建。保留 `easy_tdx_data` 数据卷、端口、环境变量、安全限制与资源上限。未修改账户、密码、Nginx、Cloudflare 配置或其他站点。切换涉及短暂重启，不是零停机发布。

## 验证

1. 本地 42 项新功能与真实行情验收通过，TypeScript 和生产构建通过。
2. 新镜像先在断网、只读、无生产数据卷的临时容器中执行验证：最近局部极值、顶底镜像、波段零轴限制及结构范围隔离、800 根冻结日线、三笔盘整、MACD 精度、共同截止、复权元数据、120 分钟协议参数均通过。
3. 正式容器 `running / healthy`；9 个运行中的 Python 模块与发布源文件哈希一致。
4. `accounts.db`、`strategies.db` 完整性检查正常，且检查时与停服备份逐字节一致；未读取或输出账户内容。
5. 公网 `/`、`/login`、`/chanlun` 返回新版 HTML。部分响应由既有 Cloudflare 规则追加统计脚本，验证只移除此已知追加项与标签间空白，再严格比较应用 HTML。
6. 入口 JS/CSS、缠论 JS/CSS、技术指标选择器 JS/CSS及公共绘图模块均与本地构建 SHA256 一致。入口 `index-BtaPEJWX.js`，缠论模块 `ChanlunView-CQLlEoAL.js`。
7. 认证状态保留既有账户设置；匿名 `/auth/me` 返回 401，登录保护正常。
8. 公网多周期研究接口使用合成数据通过 HTTP 验收，共同截止、样本数和非交易标记正确。一次默认 Python User-Agent 的请求返回 403，采用与其他验收请求一致的部署工具 User-Agent 后通过；未更改访问控制。
9. 其他原有容器仍运行。真实分钟案例逐点复核、上游 120 分钟行情与浏览器下载落盘仍属于另行业务验收，不因本次部署而宣称已完成。

## 回退应用（保留当前用户数据）

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20260930-candle-alignment/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20260930-candle-alignment/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

回退后重新核验健康与公网资源。不要自动恢复数据备份覆盖用户发布后的新数据。与既有版本一致，重启后旧的临时签名研究检查点会失效，需重新运行对应研究。
