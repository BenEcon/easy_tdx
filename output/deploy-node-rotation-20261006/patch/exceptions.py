"""easy-tdx 异常层次"""


class TdxError(Exception):
    """所有 easy-tdx 异常的基类"""


class TdxConnectionError(TdxError):
    """TCP 连接失败或超时"""


class TdxDecodeError(TdxError):
    """响应报文解析失败"""


class TdxNodesExhaustedError(TdxConnectionError):
    """全部兼容行情节点均失败；保留逐节点诊断，不伪装成无行情。"""

    def __init__(self, attempts: list[tuple[str, str]]) -> None:
        self.attempts = tuple(attempts)
        super().__init__(f"行情服务暂不可用，已轮换全部 {len(attempts)} 个兼容节点，请稍后重试。")


class TdxCommandError(TdxError):
    """命令执行失败（服务器返回错误）"""


class TdxFileNotFoundError(TdxError):
    """本地数据文件不存在"""


class TdxOfflineError(TdxError):
    """离线数据读取失败（路径未配置、文件格式错误等）"""
