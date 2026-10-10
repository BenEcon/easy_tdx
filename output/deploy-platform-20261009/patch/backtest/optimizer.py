"""参数网格寻优器。

对单个策略的 1-2 个参数做网格搜索：遍历用户指定的取值列表的笛卡尔积，
每个组合跑一次回测，按 total_return 排序，返回排名 + 热力图矩阵。

设计镜像 :class:`~easy_tdx.backtest.combo.CombinationRunner` 的枚举/排序模式，
但遍历的是参数组合而非策略组合。网格大小硬上限 ``MAX_GRID_POINTS`` 防组合爆炸。

用法::

    from easy_tdx.backtest.optimizer import ParamGridOptimizer

    opt = ParamGridOptimizer(
        strategy_name="ma_cross",
        param_grid={"fast": [5, 10, 20], "slow": [10, 20, 30]},
        df=df,
        cash=100000,
    )
    result = opt.run()
    print(result.best.params, result.best.total_return)
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import asdict, dataclass, field
from numbers import Real
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.metric_state import metric_states, ranking_key
from easy_tdx.backtest.performance_sampling import CONTRACT, input_sampling_basis
from easy_tdx.backtest.types import BacktestResult
from easy_tdx.checkpoints import calculation_journal
from easy_tdx.computation import computation_checkpoint

logger = logging.getLogger(__name__)

# 网格点上限：防止组合爆炸。3 参数各 6 值 = 216 已接近上限。
MAX_GRID_POINTS = 200


@dataclass
class GridPointResult:
    """单个网格点的回测结果摘要。

    Attributes:
        params: 该点的参数取值（如 {"fast": 10, "slow": 20}）
        total_return: 总收益率
        sharpe: 夏普比率
        max_drawdown: 最大回撤
        total_trades: 总交易笔数
        win_rate: 胜率（0-1）
        profit_factor: 盈亏比
    """

    params: dict[str, Any]
    total_return: float = float("nan")
    sharpe: float = float("nan")
    max_drawdown: float = float("nan")
    total_trades: int = 0
    win_rate: float = float("nan")
    profit_factor: float = float("nan")
    metric_status: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metric_status = metric_states(
            {
                key: getattr(self, key)
                for key in ("total_return", "sharpe", "max_drawdown", "win_rate", "profit_factor")
            },
            {key: value["reason"] for key, value in self.metric_status.items()},
        )


@dataclass
class OptimizeResult:
    """网格寻优完整结果。

    Attributes:
        strategy: 策略名
        param_names: 寻优的参数名列表（1-2 个，决定热力图维度）
        results: 所有网格点结果，按 total_return 降序排列
        best: 最优点（results[0] 的引用）
        heatmap: 2 参数时的热力图矩阵（x/y 轴取值 + cell 收益率）；1 参数或空时为 None
    """

    strategy: str
    param_names: list[str]
    results: list[GridPointResult]
    best: GridPointResult | None = None
    heatmap: dict[str, Any] | None = None
    performance_basis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典。"""
        import math

        def clean(v: Any) -> Any:
            if isinstance(v, Real) and not isinstance(v, bool):
                return float(v) if math.isfinite(v) else None
            return v

        return {
            "strategy": self.strategy,
            "param_names": self.param_names,
            "results": [
                {
                    "params": r.params,
                    "total_return": clean(r.total_return),
                    "sharpe": clean(r.sharpe),
                    "max_drawdown": clean(r.max_drawdown),
                    "total_trades": r.total_trades,
                    "win_rate": clean(r.win_rate),
                    "profit_factor": clean(r.profit_factor),
                    "metric_status": r.metric_status,
                }
                for r in self.results
            ],
            "best": (
                {
                    "params": self.best.params,
                    "total_return": clean(self.best.total_return),
                    "sharpe": clean(self.best.sharpe),
                    "max_drawdown": clean(self.best.max_drawdown),
                    "total_trades": self.best.total_trades,
                    "win_rate": clean(self.best.win_rate),
                    "profit_factor": clean(self.best.profit_factor),
                    "metric_status": self.best.metric_status,
                }
                if self.best
                else None
            ),
            "heatmap": self.heatmap,
            "performance_basis": self.performance_basis,
        }


class ParamGridOptimizer:
    """参数网格寻优器。

    遍历 ``param_grid`` 的笛卡尔积，每个组合实例化策略 + 跑回测，
    收集指标后排序。复用同一份 DataFrame（引擎无跨 run 缓存，安全）。

    Args:
        strategy_name: 策略名（从注册表解析）
        param_grid: 参数取值网格，如 {"fast": [5,10,20], "slow": [10,20,30]}
        df: OHLCV DataFrame（所有网格点共用）
        cash: 初始资金
        commission: 佣金率
        min_commission: 最低佣金
        stamp_tax: 印花税
        slippage: 滑点
        execution: 成交模式
    """

    def __init__(
        self,
        strategy_name: str,
        param_grid: dict[str, list[Any]],
        df: pd.DataFrame,
        cash: float = 1_000_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
    ) -> None:
        size = 1
        for vals in param_grid.values():
            size *= len(vals)
        if size > MAX_GRID_POINTS:
            raise ValueError(f"网格大小 {size} 超过上限 {MAX_GRID_POINTS}，请减少参数取值数量")
        if size == 0:
            raise ValueError("param_grid 不能有空取值列表")

        self._strategy_name = strategy_name
        self._param_grid = param_grid
        self._df = df
        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution

    def run(self) -> OptimizeResult:
        """执行网格寻优，返回排序后的结果。"""
        # 延迟导入避免循环依赖
        from easy_tdx.backtest.strategies import get_registry

        entry = get_registry().get(self._strategy_name)
        param_names = list(self._param_grid.keys())
        value_lists = [self._param_grid[name] for name in param_names]
        combinations = [
            dict(zip(param_names, combo, strict=True)) for combo in itertools.product(*value_lists)
        ]
        configuration = {
            "cash": self._cash,
            "commission": self._commission,
            "min_commission": self._min_commission,
            "stamp_tax": self._stamp_tax,
            "slippage": self._slippage,
            "execution": self._execution,
        }
        journal = calculation_journal()
        key = "optimizer-grid/" + self._strategy_name
        header = {
            "schema": "optimizer-grid-v1",
            "performance_contract": CONTRACT,
            "strategy": self._strategy_name,
            "configuration": configuration,
            "param_names": param_names,
            "total": len(combinations),
        }
        saved = journal.restore(key) if journal is not None else None
        points = self._restore_points(saved, header, combinations)
        restored_count = len(points)
        results: list[GridPointResult] = []
        for index, params in enumerate(combinations):
            computation_checkpoint()
            if index < len(points):
                point = points[index]
            else:
                point = {"params": params, "status": "invalid", "result": None}
                try:
                    # Preserve semantic constraints, while exploring out-of-range parameters.
                    strategy = entry.build(params, skip_bounds=True)
                except ValueError:
                    logger.info("网格点 %s 语义无效，跳过", params)
                else:
                    try:
                        engine = BacktestEngine(
                            strategy=strategy,
                            cash=self._cash,
                            commission=self._commission,
                            min_commission=self._min_commission,
                            stamp_tax=self._stamp_tax,
                            slippage=self._slippage,
                            execution=self._execution,
                        )
                        bt_result: BacktestResult = engine.run(self._df)
                        perf = bt_result.performance
                        result = GridPointResult(
                            params=params,
                            total_return=perf.get("total_return", float("nan")),
                            sharpe=perf.get("sharpe", float("nan")),
                            max_drawdown=perf.get("max_drawdown", float("nan")),
                            total_trades=int(perf.get("total_trades", 0)),
                            win_rate=perf.get("win_rate", float("nan")),
                            profit_factor=perf.get("profit_factor", float("nan")),
                            metric_status={
                                name: state
                                for name, state in bt_result.config.get("performance_basis", {})
                                .get("metric_status", {})
                                .items()
                                if name
                                in {
                                    "total_return",
                                    "sharpe",
                                    "max_drawdown",
                                    "win_rate",
                                    "profit_factor",
                                }
                            },
                        )
                        point = {"params": params, "status": "ok", "result": asdict(result)}
                    except Exception:  # noqa: BLE001 — existing per-point failure policy
                        logger.warning("网格点 %s 回测失败，跳过", params, exc_info=True)
                        point = {"params": params, "status": "failed", "result": None}
                points.append(point)
                if journal is not None:
                    # Never turn a checkpoint failure into a successful partial ranking.
                    journal.save(key, {**header, "points": points})
            if point["result"] is not None:
                results.append(GridPointResult(**point["result"]))
            if journal is not None and index + 1 == restored_count:
                journal.used(key, restored_count)

        # 按 total_return 降序
        results.sort(key=lambda r: ranking_key(r.total_return), reverse=True)

        best = next((r for r in results if math.isfinite(r.total_return)), None)
        heatmap = self._build_heatmap(results, param_names) if len(param_names) == 2 else None

        return OptimizeResult(
            strategy=self._strategy_name,
            param_names=param_names,
            results=results,
            best=best,
            heatmap=heatmap,
            performance_basis=input_sampling_basis(self._df),
        )

    @staticmethod
    def _restore_points(
        saved: dict[str, Any] | None, header: dict[str, Any], combinations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if saved is None:
            return []
        if (
            set(saved) != {*header, "points"}
            or any(saved[key] != value for key, value in header.items())
            or type(saved["total"]) is not int
            or not isinstance(saved["points"], list)
            or len(saved["points"]) > len(combinations)
        ):
            raise ValueError("寻优检查点配置、版本或游标不匹配")
        points: list[dict[str, Any]] = saved["points"]
        metrics = {"total_return", "sharpe", "max_drawdown", "win_rate", "profit_factor"}
        for point, params in zip(points, combinations, strict=False):
            if (
                not isinstance(point, dict)
                or set(point) != {"params", "status", "result"}
                or point["params"] != params
                or point["status"] not in {"ok", "invalid", "failed"}
            ):
                raise ValueError("寻优检查点参数顺序或状态无效")
            result = point["result"]
            if point["status"] != "ok":
                if result is not None:
                    raise ValueError("无效/失败网格点不能带成功结果")
            elif (
                not isinstance(result, dict)
                or set(result) != metrics | {"params", "total_trades", "metric_status"}
                or result["params"] != params
                or type(result["total_trades"]) is not int
                or result["total_trades"] < 0
                or not isinstance(result["metric_status"], dict)
                or set(result["metric_status"]) != metrics
                or any(
                    name not in metrics
                    or not isinstance(state, dict)
                    or set(state) != {"state", "reason"}
                    or state["state"]
                    not in {"finite", "unavailable", "positive_infinity", "negative_infinity"}
                    or not isinstance(state["reason"], str)
                    for name, state in result["metric_status"].items()
                )
                or any(
                    not isinstance(result[name], Real) or isinstance(result[name], bool)
                    for name in metrics
                )
            ):
                raise ValueError("寻优检查点完整结果无效")
            elif any(
                state["state"] != result["metric_status"][name]["state"]
                for name, state in metric_states({name: result[name] for name in metrics}).items()
            ):
                raise ValueError("寻优检查点指标状态与数值不一致")
        return points

    def _build_heatmap(
        self,
        results: list[GridPointResult],
        param_names: list[str],
    ) -> dict[str, Any]:
        """2 参数时构建热力图矩阵：x=参数1取值，y=参数2取值，cell=total_return。

        Returns:
            {"x": [...], "y": [...], "data": [[x_idx, y_idx, value], ...]}
        """
        x_name, y_name = param_names
        x_vals = sorted(set(self._param_grid[x_name]))
        y_vals = sorted(set(self._param_grid[y_name]))
        x_idx = {v: i for i, v in enumerate(x_vals)}
        y_idx = {v: i for i, v in enumerate(y_vals)}

        data: list[list[Any]] = []
        for r in results:
            x = r.params.get(x_name)
            y = r.params.get(y_name)
            if x not in x_idx or y not in y_idx:
                continue
            data.append(
                [x_idx[x], y_idx[y], r.total_return if math.isfinite(r.total_return) else None]
            )

        return {"x_name": x_name, "y_name": y_name, "x": x_vals, "y": y_vals, "data": data}
