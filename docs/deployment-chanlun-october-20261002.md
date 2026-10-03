# 2026-10-02 缠论确认规则部署

已部署至 `https://tdx.bowenv.com/chanlun`。

## 发布与恢复点

- 发布目录：`/home/opc/apps/easy_tdx-release-20261002-chanlun-october`。
- 镜像：`easy-tdx:chanlun-october-20261002`。
- 镜像 ID：`sha256:b9b4f414e41bdce42d2b8e0daab19e870d586fa91fe57535853847157bcba72e`。
- 前一版本：`easy-tdx:chanlun-october-20261001`，镜像 ID `sha256:26690b334aceb8781e2d44aecd881fd11fe330ef721d3e49bdc04be72d0d9365`。
- 停服一致性备份：`/home/opc/backups/tdx-20261002-chanlun-october/data.tar.gz`；目录 700，归档 600，已检查可读取。
- 本地发布材料：`output/deploy-october-20261002/`。

在前一镜像上仅覆盖三个缠论 Python 模块和前端生产构建。未改变账号、密码、个人数据、数据卷、运行限制、端口、Nginx 或 Cloudflare 配置。服务切换涉及短暂重启。

## 本次上线

- 波段最终确认等待 C 段结束并复核，双线最终确认等待从极值出发的已确认反向笔。
- 极值日、初步条件日、最终确认日及失效日分别记录；候选不得提前显示为最终确认。
- DIF/DEA 零轴同侧检查覆盖完整 ABC；高层级结构维持独立校验。
- 顶底颜色、圆形／菱形和空心／实心分别表达方向、类型及状态。
- M1 仅为已确认 MACD 波段提示，不混入结构买卖点或策略。

## 验证

1. 实施阶段已有 1005 项相关后端测试、150 项前端测试和生产构建通过。本次部署前再次运行 30 项新规则测试及全部 150 项前端测试，均通过。
2. 先在断网、只读、无生产数据挂载的新镜像内验证逐根前缀确认、顶底镜像、初步条件后失效、C 结束确认、完整 ABC 零轴检查、独立结构校验及 800 根冻结行情；均通过。
3. 正式容器 `running / healthy`。三个运行中的 Python 模块与发布源文件哈希一致。
4. 前后运行配置除镜像外一致；`accounts.db`、`strategies.db` 完整性检查通过，且检查时与发布前备份逐字节一致。未输出账户内容。
5. 公网 `/`、`/login`、`/chanlun` HTML 与构建匹配；仅归一化既有 Cloudflare 统计脚本和标签间空白。入口、缠论、图表和指标选择器资源哈希一致。
6. 入口为 `index-_NrtQ3Mf.js`，缠论模块为 `ChanlunView-DreNLF-I.js`。
7. 既有账户设置保留，匿名 `/api/v1/auth/me` 仍返回 401。公网多周期研究接口使用合成数据验证通过。
8. 首次离线验证因新发布目录 750 阻止容器非特权用户读取验证脚本而停止，生产服务尚未切换；仅将无秘密发布目录的遍历权限调整为 755 后重新验证成功。数据备份仍为 700/600。

具体文档市场案例仍受行情快照、复权和暖机窗口约束，本次部署不代表额外完成这些真实案例的逐点复现。

## 应用回退

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261001-chanlun-october/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261001-chanlun-october/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

回退应用仍保留当前用户数据；不要自动用备份覆盖发布后新增数据。重启后旧的临时签名研究检查点可能失效，需重新运行。用户刷新页面并重新查询后获得新规则计算结果。
