"""扩展行情握手命令。"""

from typing import Final

EX_SETUP_CMD: Final[bytes] = bytes.fromhex(
    "01 01 48 65 00 01 52 00 52 00 54 24"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "1f 32 c6 e5 d5 3d fb 41"
    "cc e1 6d ff d5 ba 3f b8"
    "cb c5 7a 05 4f 77 48 ea"
)
