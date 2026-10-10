# tests/unit/test_factor_base.py
"""Test Factor base class and registry."""

from __future__ import annotations

import pandas as pd
import pytest

from easy_tdx.factor.base import (
    FACTORY_REGISTRY,
    Factor,
    register_factor,
)


class _StubFactor(Factor):
    """测试用因子。"""

    name = "test_stub"
    category = "test"
    description = "stub for testing"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(1)


class TestFactorABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Factor()  # type: ignore[abstract]

    def test_subclass_must_define_name(self):
        class NoName(Factor):
            category = "test"
            description = "x"
            inputs = ("close",)

            def compute(self, df):
                return df["close"]

        with pytest.raises(TypeError):
            NoName()

    def test_subclass_must_define_category(self):
        class NoCategory(Factor):
            name = "x"
            description = "x"
            inputs = ("close",)

            def compute(self, df):
                return df["close"]

        with pytest.raises(TypeError):
            NoCategory()

    def test_subclass_must_implement_compute(self):
        class NoCompute(Factor):
            name = "x"
            category = "test"
            description = "x"
            inputs = ("close",)

        with pytest.raises(TypeError):
            NoCompute()

    def test_concrete_subclass_works(self):
        f = _StubFactor()
        assert f.name == "test_stub"
        assert f.category == "test"
        assert f.inputs == ("close",)


class TestRegistry:
    def test_register_factor_decorator(self):
        @register_factor
        class RegFactor(Factor):
            name = "reg_test_factor"
            category = "test"
            description = "registered factor"
            inputs = ("close",)

            def compute(self, df):
                return df["close"]

        assert "reg_test_factor" in FACTORY_REGISTRY
        assert FACTORY_REGISTRY["reg_test_factor"] is RegFactor

    def test_duplicate_name_raises(self):
        @register_factor
        class Dup(Factor):
            name = "dup_test_factor"
            category = "test"
            description = "dup"
            inputs = ("close",)

            def compute(self, df):
                return df["close"]

        with pytest.raises(ValueError, match="已注册"):

            @register_factor
            class Dup2(Factor):
                name = "dup_test_factor"
                category = "test"
                description = "dup2"
                inputs = ("close",)

                def compute(self, df):
                    return df["close"]


class TestFactorCompute:
    def test_compute_returns_series(self):
        f = _StubFactor()
        df = pd.DataFrame({"close": [10.0, 11.0, 10.5, 12.0]})
        result = f.compute(df)
        assert isinstance(result, pd.Series)
        assert len(result) == 4
