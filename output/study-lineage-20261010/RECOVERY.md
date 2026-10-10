# 本轮源码恢复点

本轮之后：`source-after.tar.gz`

SHA256：`b6fc187caca5935336e32b25e8c42442519d238ce71aadefd18d4e817a1e3950`

上一轮基线：`../radar-archive-20261010/source-after.tar.gz`

SHA256：`ec9ed551b4e714ee75bb8f6732022157c4f2cf9a6b0e858ccb9e66be0fd00275`

包含源码、测试、文档及前端构建配置；不包含生产数据库、账户凭据、依赖目录或输出。恢复时先校验摘要并解压到新的隔离目录，逐文件比较，不覆盖用户后续工作。完整证据见本目录日志及 docs/study-lineage-20261010.md。

本轮临时浏览器 study-lineage 已关闭，确认后的本地 QA 进程 22134 已停止。未部署服务器。
