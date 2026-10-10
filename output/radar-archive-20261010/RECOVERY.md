# 本轮恢复点

- 完成源码：`source-after.tar.gz`
- SHA256：`ec9ed551b4e714ee75bb8f6732022157c4f2cf9a6b0e858ccb9e66be0fd00275`
- 修改前已验证源码：`../radar-original-input-20261010/source-after.tar.gz`
- 修改前 SHA256：`abdbc836052a59f52efcd1f0058163f350351fb5927fb687de7d0fe5794444fa`
- 包含全部 src／tests／docs／scripts、前端源码／测试／静态资源／构建配置、pyproject 和工作流；不含运行环境、生产数据库或凭证。
- 恢复先解包到新隔离目录并比较，不直接覆盖现有工作树或用户数据。存档仅增加可选字段，没有数据库迁移；旧代码不会展示新来源，不应因此删除存档数据。
- 验证：前端 486＋28、后端相关 221、13 份真实股票回执跨前后端检查、构建／Ruff／Mypy 302 通过。实际 WebKit 独立存档验收见 `browser-verified.log`，初次脚本问题保留在早期日志与正式文档。
- 本轮隔离浏览器已关闭；临时服务 PID 14781 经核验后 SIGTERM。没有部署服务器，原十阶段目标未完成。
