"""历史财务数据读取（gpcw*.dat / gpcw*.zip 文件）。"""

import zipfile
from pathlib import Path

from ..codec.financial import parse_financial_dat
from ..exceptions import TdxFileNotFoundError, TdxOfflineError
from ..models.enums import Market
from ..models.finance import FinancialRecord


def read_history_financial(filepath: str | Path) -> list[FinancialRecord]:
    """从本地 gpcw*.dat 或 gpcw*.zip 文件读取历史财务数据。

    复用 codec/financial.py 的 parse_financial_dat() 解析二进制格式。

    Args:
        filepath: .dat 或 .zip 文件路径。

    Returns:
        FinancialRecord 列表。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"历史财务数据文件不存在: {filepath}")

    if filepath.suffix.lower() == ".zip":
        data = _read_from_zip(filepath)
    else:
        data = filepath.read_bytes()

    raw_records = parse_financial_dat(data)
    results: list[FinancialRecord] = []
    for code, market_byte, report_date, fields in raw_records:
        try:
            market = Market(market_byte)
        except ValueError:
            market = Market.SZ  # 默认深圳
        results.append(
            FinancialRecord(
                code=code,
                market=market,
                report_date=report_date,
                fields=fields,
            )
        )
    return results


def _read_from_zip(zip_path: Path) -> bytes:
    """从 zip 中提取 .dat 文件内容。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".dat"):
                    return zf.read(name)
            raise TdxOfflineError(f"zip 中未找到 .dat 文件: {zip_path}")
    except zipfile.BadZipFile as e:
        raise TdxOfflineError(f"无效的 zip 文件: {zip_path}") from e
