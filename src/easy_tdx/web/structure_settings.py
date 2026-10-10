"""Bounded UI settings; never permit weakening strict price/fractal checks."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from easy_tdx.chanlun.config import ChanlunConfig


class StructureSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bi_type: Literal["new", "old", "simple"] = "new"
    zs_min_lines: int = Field(default=3, ge=3, le=6, strict=True)

    def engine_config(self) -> ChanlunConfig:
        # The threshold is a base-layer output filter, NOT a recursive seed size.
        return ChanlunConfig(bi_type=self.bi_type)
