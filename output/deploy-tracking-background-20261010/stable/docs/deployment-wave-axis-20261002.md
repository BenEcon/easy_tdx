# MACD 独立波段及轴侧尾段部署（2026-10-02）

已部署至 `https://tdx.bowenv.com/chanlun`。

## 发布与恢复点

- 新发布目录：`/home/opc/apps/easy_tdx-release-20261002-wave-axis`。
- 新镜像：`easy-tdx:wave-axis-20261002`。
- 镜像 ID：`sha256:631d3ac3e1bebbcb180c3d7be4c5fc903ebd2df5dae0f7870d2e40183abf281b`。
- 前一镜像：`easy-tdx:chanlun-october-20261002`，ID `sha256:b9b4f414e41bdce42d2b8e0daab19e870d586fa91fe57535853847157bcba72e`。
- 停服一致性备份：`/home/opc/backups/tdx-20261002-wave-axis/data.tar.gz`，目录 700，归档 600，已验证可读取。
- 本地上传包：`output/deploy-wave-axis-20261002.tar.gz`，SHA256 `a2a7c072ff70dcee61560bd23d7a6164250508d638b675ed7b8bffed8f740fad`；上传后再次核对一致。

旧版本目录、镜像、备份均保留。仅覆盖缠论三个源模块和前端构建，运行配置、端口、安全限制、数据卷、认证、代理设置未变。归档中 macOS 扩展属性被 Linux tar 忽略，不影响源文件内容。

## 验证

1. 实施阶段已有 1021 项相关后端测试、152 项前端测试及生产构建通过。
2. 本次部署前在本地及服务器新镜像内分别运行离线验收，通过后才停止旧服务备份及切换。验证包含有效 A 全部统计同步重算、B/C 跨轴拒绝、反向笔确认、C 结束确认、结构基线、两组 600/800 根真实快照案例及未生成候选原因。
3. 新服务 `running / healthy`。运行中的源文件哈希与上传发布材料匹配（核验包含归档携带的 macOS 元数据伴随文件）。
4. 前后运行配置除镜像外一致。账户和策略数据库完整性检查通过；策略库与停服备份逐字节一致。账户库经只读字段哈希比对：用户数及身份、凭据、角色不变，会话无增删或变化，仅 `preferences` 和 `updated_at` 在运行期间发生变化，未覆盖这些用户偏好更新。最初临时只读容器无法访问宿主备份，后改用宿主读取、内存流比对，全程未修改数据权限或生产安全配置。
5. 公网 `/`、`/login`、`/chanlun` 与新构建 HTML 匹配；仅归一化既有 Cloudflare 统计注入和标签空白。入口、缠论、图表及指标选择器资源哈希均一致。
6. 新前端入口 `index-k07Regek.js`，缠论模块 `ChanlunView-DUMVj4LK.js`。
7. 既有账户设置保留，匿名账户接口仍为 401；公网多周期研究接口验证通过。
8. 公网真实回放接口使用冻结的 300450 前复权日线快照，确认 2025-12-16 极值于 12-22 最终确认，2026-09-11 极值于 9-16 最终确认，且返回具体未通过核验记录。以上日期受已确认的 C 结束规则约束，不回填实际确认日。

## 回退

```sh
sudo docker compose -p easy_tdx \
  -f /home/opc/apps/easy_tdx-release-20261002-chanlun-october/compose.yaml \
  -f /home/opc/apps/easy_tdx-release-20261002-chanlun-october/release-image.yaml \
  up -d --no-build --pull never easy-tdx
```

应用回退仍沿用现有用户数据，不自动覆盖发布后新增数据。旧的临时研究检查点可能因重启失效，应重新运行。刷新网页并重新查询可取得本次规则的计算结果。
