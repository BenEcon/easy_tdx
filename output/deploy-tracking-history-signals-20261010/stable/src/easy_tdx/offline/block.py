"""板块数据读取（.dat 文件和自定义板块目录）。"""

from dataclasses import dataclass, field
from pathlib import Path

from ..codec.block import parse_block_dat
from ..exceptions import TdxFileNotFoundError, TdxOfflineError
from ..models.finance import TdxBlock


@dataclass
class CustomerBlock:
    """自定义板块。"""

    blockname: str
    block_type: str
    codes: list[str] = field(default_factory=list)


def read_block_dat(filepath: str | Path) -> list[TdxBlock]:
    """从本地 .dat 板块文件读取板块数据。

    直接复用 codec/block.py 的 parse_block_dat()。

    Args:
        filepath: .dat 文件路径（如 block_zs.dat）。

    Returns:
        TdxBlock 列表。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"板块数据文件不存在: {filepath}")
    data = filepath.read_bytes()
    return parse_block_dat(data, filename=filepath.name)


def read_customer_blocks(block_dir: str | Path) -> list[CustomerBlock]:
    """从通达信自定义板块目录读取板块数据。

    目录结构：
      blocknew.cfg  — 板块索引（120 字节/条：50B 名称 + 70B 文件名）
      *.blk         — 板块内容（每行一个代码，首位为市场标识）

    Args:
        block_dir: 自定义板块目录路径。

    Returns:
        CustomerBlock 列表。
    """
    block_dir = Path(block_dir)
    if not block_dir.is_dir():
        raise TdxOfflineError(f"自定义板块目录不存在: {block_dir}")

    cfg_path = block_dir / "blocknew.cfg"
    if not cfg_path.is_file():
        raise TdxOfflineError(f"板块配置文件不存在: {cfg_path}")

    cfg_data = cfg_path.read_bytes()
    results: list[CustomerBlock] = []
    pos = 0

    while pos + 120 <= len(cfg_data):
        name = cfg_data[pos : pos + 50].decode("gbk", errors="replace").rstrip("\x00")
        name = name.split("\x00")[0]
        blk_filename = cfg_data[pos + 50 : pos + 120].decode("gbk", errors="replace").rstrip("\x00")
        blk_filename = blk_filename.split("\x00")[0]
        pos += 120

        if not blk_filename:
            continue

        blk_path = block_dir / f"{blk_filename}.blk"
        if not blk_path.is_file():
            continue

        codes: list[str] = []
        for line in blk_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and len(line) > 1:
                codes.append(line[1:])  # 去掉首位的市场标识

        if name:
            results.append(
                CustomerBlock(
                    blockname=name,
                    block_type=blk_filename,
                    codes=codes,
                )
            )

    return results
