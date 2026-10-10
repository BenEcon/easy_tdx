"""Explicit recomputation from supplied archived inputs; never fetch or overwrite archives."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, model_validator

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.archive_indicators import SavedChartIndicators, recompute_chart_indicators
from easy_tdx.web.research_cursor import fingerprint
from easy_tdx.web.resource_admission import BoundedComputeRoute
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations
from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot
from easy_tdx.web.task_version import execution_version


def require_recompute_owner(
    user: UserRecord = Depends(get_current_user),
    expected: str | None = Header(default=None, alias="X-Research-Owner"),
) -> None:
    if expected != user.id:
        raise HTTPException(409, "登录账户与原档页面不一致，请重新登录并打开本账户存档")


router = APIRouter(
    tags=["chanlun"],
    route_class=BoundedComputeRoute,
    dependencies=[Depends(require_recompute_owner)],
)


class ArchiveReplayRequest(ReplayRequest):
    category: Literal[
        "DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120"
    ]


class ArchiveRecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    kind: Literal["chart", "study"]
    chart: ArchiveReplayRequest | None = None
    study: StudyRequest | None = None
    chart_indicators: SavedChartIndicators | None = None

    @model_validator(mode="after")
    def complete_input(self) -> ArchiveRecomputeRequest:
        if self.chart_indicators is not None and self.kind != "chart":
            raise ValueError("只有图表重算可以提交冻结指标参数")
        if (self.kind == "chart") != (self.chart is not None) or (self.kind == "study") != (
            self.study is not None
        ):
            raise ValueError("必须且只能提交与存档类型对应的重算输入")
        if self.chart and self.chart.visible_count != len(self.chart.bars):
            raise ValueError("存档重算必须使用完整保存窗口，不得静默截短")
        sources = [self.chart] if self.chart else self.study.series if self.study else []
        if any(
            not {"vol", "amount"} <= bar.model_fields_set
            for source in sources
            for bar in source.bars
        ):
            raise ValueError("原档缺少成交量或成交额，不补零重算")
        if self.study:
            required = {
                "volume_multiple",
                "squeeze_quantile",
                "ma_periods",
                "window_bars",
                "window_start",
                "window_end",
            }
            if not required <= self.study.model_fields_set:
                raise ValueError("多周期旧档缺少研究参数，不能用当前默认值补造")
            if any("bar_time" not in row.model_fields_set for row in self.study.series):
                raise ValueError("多周期旧档缺少行情时间标签，不能猜测起止口径")
        return self


@router.post("/chanlun/archive-recompute")
def recompute_archive(req: ArchiveRecomputeRequest, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    before = execution_version()
    indicator_data = None
    if req.chart is not None:
        result = replay_snapshot(req.chart, ownership_history="summary")
        parameters = req.chart.structure_settings.engine_config().to_dict()
        parameters["zs_min_lines"] = req.chart.structure_settings.zs_min_lines
        scope = (
            "structure_and_macd_saved_settings"
            if "structure_settings" in req.chart.model_fields_set
            else "structure_and_macd_current_defaults"
        )
        source = req.chart.model_dump(mode="json")
        if req.chart_indicators is not None:
            source["chart_indicators"] = req.chart_indicators.model_dump(mode="json")
            try:
                indicator_data = recompute_chart_indicators(source["bars"], req.chart_indicators)
            except (ValueError, TypeError, IndexError, ZeroDivisionError) as exc:
                raise HTTPException(
                    422, "保存的指标参数或行情不足以完成计算；未返回部分结果"
                ) from exc
            scope = "structure_macd_and_saved_chart_indicators"
    else:
        assert req.study is not None
        result = observations(req.study)
        parameters = result["parameters"]
        scope = "study_saved_parameters_current_algorithm"
        source = req.study.model_dump(mode="json")
    if execution_version() != before:
        raise HTTPException(409, "计算期间执行版本发生变化，请重试；未返回混合版本结果")
    return {
        "contract": "archive-recompute-v2"
        if indicator_data is not None
        else "archive-recompute-v1",
        "request_id": str(req.request_id),
        "kind": req.kind,
        "input_digest": fingerprint(source),
        "execution_version": before,
        "scope": scope,
        "parameters": parameters,
        "result": result,
        "source": "client_supplied_archived_bars_not_market_verified",
        "historical_data_vintage": False,
        **({"indicator_data": indicator_data} if indicator_data is not None else {}),
    }
