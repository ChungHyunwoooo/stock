"""symbol_info 테스트 — 정밀도 변환, 반올림, 포맷."""

import math

from engine.core.symbol_info import (
    SymbolInfo,
    _precision_decimals,
    round_price,
    round_quantity,
    format_price,
)


class TestPrecisionDecimals:
    def test_standard(self):
        assert _precision_decimals(0.01) == 2
        assert _precision_decimals(0.001) == 3
        assert _precision_decimals(0.1) == 1

    def test_scientific(self):
        assert _precision_decimals(1e-05) == 5
        assert _precision_decimals(1e-07) == 7

    def test_one_or_above(self):
        assert _precision_decimals(1.0) == 0
        assert _precision_decimals(10.0) == 0

    def test_zero_or_negative(self):
        assert _precision_decimals(0) == 0
        assert _precision_decimals(-0.01) == 0


class TestSymbolInfo:
    def test_frozen(self):
        info = SymbolInfo("BTC/USDT", 0.1, 0.001, 5.0, 0.001)
        assert info.symbol == "BTC/USDT"
        assert info.price_precision == 0.1

    def test_equality(self):
        a = SymbolInfo("BTC/USDT", 0.1, 0.001, 5.0, 0.001)
        b = SymbolInfo("BTC/USDT", 0.1, 0.001, 5.0, 0.001)
        assert a == b
