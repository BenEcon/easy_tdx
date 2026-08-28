"""缠论分析器主入口。

ChanlunAnalyser 接收 easy_tdx 的 K 线 DataFrame，
内部执行完整的缠论计算管道：
K线合并 → 分型识别 → 笔计算 → 中枢计算 → 线段 → 买卖点 → 背驰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from easy_tdx.chanlun.beichi import check_bi_beichi  # noqa: F401
from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.macd import calc_macd  # noqa: F401
from easy_tdx.chanlun.mmd import find_mmds  # noqa: F401
from easy_tdx.chanlun.types import BC, BI, FX, MMD, XD, ZS, CLKline, FXType, Kline
from easy_tdx.chanlun.xd import find_xds  # noqa: F401
from easy_tdx.chanlun.zs import find_zss


def _df_to_klines(df: pd.DataFrame) -> list[Kline]:
    """将 easy_tdx K 线 DataFrame 转为缠论 Kline 列表。

    期望 DataFrame 包含列：datetime, open, close, high, low, vol
    """
    klines: list[Kline] = []
    for i, row in enumerate(df.itertuples()):
        dt = getattr(row, "datetime", None) or getattr(row, "date", None)
        if dt is None:
            continue
        row_any: Any = row  # avoid pandas-stubs vs bare pandas type mismatch
        vol = getattr(row, "vol", 0.0) or 0.0
        klines.append(
            Kline(
                index=i,
                date=dt,
                open=float(row_any.open),
                close=float(row_any.close),
                high=float(row_any.high),
                low=float(row_any.low),
                amount=float(vol),
            )
        )
    return klines


@dataclass
class ChanlunResult:
    """缠论分析结果。"""

    code: str = ""
    frequency: str = ""
    klines: list[Kline] = field(default_factory=list)
    cklines: list[CLKline] = field(default_factory=list)
    fractals: list[FX] = field(default_factory=list)
    bis: list[BI] = field(default_factory=list)
    zss: list[ZS] = field(default_factory=list)
    xds: list[XD] = field(default_factory=list)
    mmds: list[MMD] = field(default_factory=list)
    bcs: list[BC] = field(default_factory=list)
    macd: dict[str, list[float]] = field(default_factory=dict)

    def _fmt_dt(self, dt: datetime) -> str:
        """按 frequency 自适应格式化日期。

        分钟级别（1/5/15/30/60min）输出完整时分 YYYY-MM-DD HH:MM，
        日/周/月/年级别只输出日期 YYYY-MM-DD（无多余 00:00）。
        frequency 来自 CLI 原始值（如 5MIN/30MIN）或 Web 映射值（5min/30min），
        统一转小写后判断是否含 'min'。
        """
        fmt = "%Y-%m-%d %H:%M" if "min" in self.frequency.lower() else "%Y-%m-%d"
        return dt.strftime(fmt)

    @staticmethod
    def _fx_dt(fx: FX) -> datetime:
        """返回分型极值真正所在的原始 K 线时间。

        包含处理后的 CLKline.date 是合并区间最后一根 K 线时间，但分型高低值
        可能来自区间内更早的一根。图表若直接使用 CLKline.date，会让端点价格
        落在错误蜡烛上。这里按分型类型回溯原始 K 线并吸附到真实极值位置。
        """
        price_field = "high" if fx.fx_type == FXType.DING else "low"
        tolerance = max(1e-8, abs(fx.val) * 1e-9)
        matches = [
            kline for kline in fx.k.klines
            if abs(float(getattr(kline, price_field)) - fx.val) <= tolerance
        ]
        return matches[-1].date if matches else fx.k.date

    def to_dict(self) -> dict[str, Any]:
        """将结果转为可序列化的字典（用于 JSON 输出）。"""
        return {
            "code": self.code,
            "frequency": self.frequency,
            "kline_count": len(self.klines),
            "ckline_count": len(self.cklines),
            "fractal_count": len(self.fractals),
            "bi_count": len(self.bis),
            "zs_count": len(self.zss),
            "xd_count": len(self.xds),
            "mmd_count": len(self.mmds),
            "bc_count": len(self.bcs),
            "bis": [
                {
                    "index": bi.index,
                    "direction": bi.direction.value,
                    "start_date": self._fmt_dt(self._fx_dt(bi.start)),
                    "end_date": self._fmt_dt(self._fx_dt(bi.end)),
                    "start_value": round(bi.start.val, 2),
                    "end_value": round(bi.end.val, 2),
                    "high": round(bi.high, 2),
                    "low": round(bi.low, 2),
                    "done": bi.is_done(),
                }
                for bi in self.bis
            ],
            "zss": [
                {
                    "index": zs.index,
                    "zg": round(zs.zg, 2),
                    "zd": round(zs.zd, 2),
                    "gg": round(zs.gg, 2),
                    "dd": round(zs.dd, 2),
                    "line_count": zs.line_count,
                    "start_date": self._fmt_dt(self._fx_dt(zs.start)) if zs.start else None,
                    "end_date": self._fmt_dt(self._fx_dt(zs.end)) if zs.end else None,
                    "done": zs.done,
                }
                for zs in self.zss
            ],
            "xds": [
                {
                    "index": xd.index,
                    "direction": xd.direction.value,
                    "start_date": self._fmt_dt(self._fx_dt(xd.start)),
                    "end_date": self._fmt_dt(self._fx_dt(xd.end)),
                    "start_value": round(xd.start.val, 2),
                    "end_value": round(xd.end.val, 2),
                    "high": round(xd.high, 2),
                    "low": round(xd.low, 2),
                }
                for xd in self.xds
            ],
            "mmds": [
                {
                    "type": mmd.mmd_type.value,
                    "date": self._fmt_dt(self._fx_dt(mmd.bi.end)) if mmd.bi else None,
                    "msg": mmd.msg,
                }
                for mmd in self.mmds
            ],
            "bcs": [
                {
                    "type": bc.bc_type.value,
                    "bc": bc.bc,
                    "curr_date": self._fmt_dt(self._fx_dt(bc.curr.end)) if bc.curr else None,
                    "prev_date": self._fmt_dt(self._fx_dt(bc.prev.end)) if bc.prev else None,
                    "msg": bc.msg,
                }
                for bc in self.bcs
            ],
        }


class ChanlunAnalyser:
    """缠论分析器。

    接收 easy_tdx K 线 DataFrame，执行缠论计算管道。

    用法：
        analyser = ChanlunAnalyser("SZ000001", "DAILY")
        analyser.process_klines(df)
        result = analyser.result
    """

    def __init__(
        self,
        code: str = "",
        frequency: str = "",
        config: ChanlunConfig | None = None,
    ) -> None:
        self._code = code
        self._frequency = frequency
        self._config = config or ChanlunConfig()
        self._result = ChanlunResult(
            code=code,
            frequency=frequency,
        )
        self._prev_df: pd.DataFrame | None = None

    @property
    def config(self) -> ChanlunConfig:
        return self._config

    @property
    def result(self) -> ChanlunResult:
        return self._result

    def process_klines(self, df: pd.DataFrame) -> ChanlunResult:
        """处理 K 线 DataFrame，执行缠论计算管道。

        Args:
            df: easy_tdx 返回的 K 线 DataFrame

        Returns:
            ChanlunResult 包含所有缠论计算结果
        """
        self._prev_df = df.copy()
        # Step 1: DataFrame → Kline 列表
        klines = _df_to_klines(df)
        self._result.klines = klines

        if not klines:
            return self._result

        # Step 2: K线包含处理
        cklines = merge_klines(klines)
        self._result.cklines = cklines

        # Step 3: 分型识别
        fractals = find_fractals(cklines, self._config)
        self._result.fractals = fractals

        # Step 4: 笔计算
        bis = find_bis(fractals, self._config)
        self._result.bis = bis

        # Step 5: 中枢计算
        zss = find_zss(bis, self._config)
        self._result.zss = zss

        # Step 6: MACD 计算
        closes = [k.close for k in klines]
        self._result.macd = calc_macd(
            closes, self._config.macd_fast, self._config.macd_slow, self._config.macd_signal
        )

        # Step 7: 线段计算
        xds = find_xds(bis, self._config)
        self._result.xds = xds

        # Step 8: 买卖点识别
        mmds = find_mmds(bis, zss, self._config)
        self._result.mmds = mmds

        # Step 9: 背驰判断
        bcs = check_bi_beichi(bis, zss, self._config)
        self._result.bcs = bcs

        return self._result

    def append_klines(self, df_new: pd.DataFrame) -> ChanlunResult:
        """增量追加 K 线数据并重新计算。

        将新数据追加到之前处理过的 DataFrame 后面，
        然后在完整数据上重新执行缠论计算管道。

        相比手动拼接 + process_klines 的优势：
        - API 更简洁，无需用户管理 DataFrame 拼接
        - 未来可优化为只重新计算受影响的部分

        Args:
            df_new: 新增的 K 线 DataFrame

        Returns:
            更新后的 ChanlunResult

        Raises:
            RuntimeError: 如果之前没有调用过 process_klines
        """
        if self._prev_df is None:
            msg = "请先调用 process_klines() 初始化，再使用 append_klines()"
            raise RuntimeError(msg)

        # 拼接旧数据 + 新数据
        combined = pd.concat([self._prev_df, df_new], ignore_index=True)

        # 去重（防止重复追加）
        if "datetime" in combined.columns:
            combined = combined.drop_duplicates(subset=["datetime"], keep="last")
            combined = combined.reset_index(drop=True)

        return self.process_klines(combined)

    def get_bis(self) -> list[BI]:
        return self._result.bis

    def get_zss(self) -> list[ZS]:
        return self._result.zss

    def get_fxs(self) -> list[FX]:
        return self._result.fractals

    def get_klines(self) -> list[Kline]:
        return self._result.klines

    def get_cklines(self) -> list[CLKline]:
        return self._result.cklines
