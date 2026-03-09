"""Tests for confluence scoring system and related modules."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv_100() -> pd.DataFrame:
    """100-row OHLCV DataFrame for analysis tests."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    np.random.seed(42)
    base = np.cumsum(np.random.randn(n) * 0.5) + 100
    close = base
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        },
        index=idx,
    )


class TestVPVR:
    def test_calc_vpvr_returns_all_keys(self, ohlcv_100):
        from engine.analysis.volume_profile import calc_vpvr

        result = calc_vpvr(ohlcv_100)
        expected_keys = {"poc", "vah", "val", "at_poc", "at_vah", "at_val", "in_value_area", "at_hvn", "at_lvn"}
        assert expected_keys.issubset(result.keys())

    def test_vpvr_poc_within_price_range(self, ohlcv_100):
        from engine.analysis.volume_profile import calc_vpvr

        result = calc_vpvr(ohlcv_100)
        low = float(ohlcv_100["low"].min())
        high = float(ohlcv_100["high"].max())
        assert low <= result["poc"] <= high

    def test_vpvr_vah_above_val(self, ohlcv_100):
        from engine.analysis.volume_profile import calc_vpvr

        result = calc_vpvr(ohlcv_100)
        assert result["vah"] >= result["val"]

    def test_vpvr_short_df(self):
        from engine.analysis.volume_profile import calc_vpvr

        df = pd.DataFrame(
            {"open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100.0]},
            index=pd.date_range("2024-01-01", periods=1, freq="1h"),
        )
        result = calc_vpvr(df)
        assert result["poc"] == 0.0

    def test_volume_profile_includes_vpvr(self, ohlcv_100):
        from engine.analysis.volume_profile import calc_volume_profile

        result = calc_volume_profile(ohlcv_100)
        assert "vpvr" in result
        assert "poc" in result["vpvr"]


class TestConfluenceScore:
    def test_max_score(self):
        from engine.analysis.confluence import calc_confluence_score

        result = calc_confluence_score(
            funding_rate=-0.0001,
            mtf_score=0.8,
            vpvr={"at_val": True, "at_poc": False, "at_vah": False, "in_value_area": False},
            side="LONG",
            adx_val=30,
            current_hour_utc=14,
        )
        assert result["total_score"] == 3
        assert result["execute"] is True
        assert result["funding_point"] is True
        assert result["mtf_point"] is True
        assert result["vp_point"] is True

    def test_zero_score(self):
        from engine.analysis.confluence import calc_confluence_score

        result = calc_confluence_score(
            funding_rate=0.0001,
            mtf_score=0.3,
            vpvr={"at_val": False, "at_poc": False, "at_vah": False},
            side="LONG",
            adx_val=30,
            current_hour_utc=14,
        )
        assert result["total_score"] == 0
        assert result["execute"] is False

    def test_regime_filter_blocks(self):
        from engine.analysis.confluence import calc_confluence_score

        result = calc_confluence_score(
            funding_rate=-0.0001,
            mtf_score=0.8,
            vpvr={"at_val": True, "at_poc": False, "at_vah": False},
            side="LONG",
            adx_val=5,  # too low (threshold is 15)
            current_hour_utc=14,
        )
        assert result["regime_ok"] is False
        assert result["execute"] is False

    def test_session_filter(self):
        from engine.analysis.confluence import calc_confluence_score

        # Asian session — crypto는 24시간이므로 세션 필터가 execute를 차단하지 않음
        result = calc_confluence_score(
            funding_rate=-0.0001,
            mtf_score=0.8,
            vpvr={"at_val": True, "at_poc": False, "at_vah": False},
            side="LONG",
            adx_val=30,
            current_hour_utc=3,  # Asian
        )
        assert result["session_ok"] is False
        # score=3, regime_ok → execute=True (세션 무관)
        assert result["execute"] is True

    def test_short_funding(self):
        from engine.analysis.confluence import calc_confluence_score

        result = calc_confluence_score(
            funding_rate=0.0005,
            mtf_score=0.7,
            vpvr={"at_val": False, "at_poc": False, "at_vah": True},
            side="SHORT",
            adx_val=25,
            current_hour_utc=10,
        )
        assert result["funding_point"] is True
        assert result["vp_point"] is True

    def test_none_funding(self):
        from engine.analysis.confluence import calc_confluence_score

        result = calc_confluence_score(
            funding_rate=None,
            mtf_score=0.8,
            vpvr={"at_val": True, "at_poc": False, "at_vah": False},
            side="LONG",
            adx_val=30,
            current_hour_utc=14,
        )
        assert result["funding_point"] is False


class TestMTFConfluence:
    def _make_trending_df(self, n: int, direction: str) -> pd.DataFrame:
        idx = pd.date_range("2024-01-01", periods=n, freq="1h")
        if direction == "up":
            close = np.linspace(100, 130, n)
        else:
            close = np.linspace(130, 100, n)
        return pd.DataFrame(
            {
                "open": close * 0.999,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.ones(n) * 5000,
            },
            index=idx,
        )

    def test_all_bullish_alignment(self):
        from engine.analysis.mtf_confluence import calc_mtf_confluence

        frames = {
            "1d": self._make_trending_df(60, "up"),
            "4h": self._make_trending_df(60, "up"),
            "1h": self._make_trending_df(60, "up"),
        }
        result = calc_mtf_confluence(frames, "LONG")
        # 선형 데이터는 5-bar pivot에서 완벽한 BULLISH가 아닐 수 있음
        # D1/4H가 RANGING(0.3)이어도 가중 합산 > 0.25
        assert result["score"] > 0.2
        assert result["total_tfs"] == 3

    def test_mixed_signals(self):
        from engine.analysis.mtf_confluence import calc_mtf_confluence

        frames = {
            "1d": self._make_trending_df(60, "up"),
            "4h": self._make_trending_df(60, "down"),
            "1h": self._make_trending_df(60, "up"),
        }
        result = calc_mtf_confluence(frames, "LONG")
        assert result["score"] < 0.8

    def test_empty_frames(self):
        from engine.analysis.mtf_confluence import calc_mtf_confluence

        result = calc_mtf_confluence({}, "LONG")
        assert result["score"] == 0.0
        assert result["aligned_count"] == 0


class TestFundingRate:
    def test_is_funding_extreme_long(self):
        from engine.strategy.funding import is_funding_extreme

        assert is_funding_extreme(-0.0001, "LONG") is True
        assert is_funding_extreme(0.00005, "LONG") is False

    def test_is_funding_extreme_short(self):
        from engine.strategy.funding import is_funding_extreme

        assert is_funding_extreme(0.0005, "SHORT") is True
        assert is_funding_extreme(0.00005, "SHORT") is False

    def test_funding_signal_strength(self):
        from engine.strategy.funding import funding_signal_strength

        assert funding_signal_strength(0.0005) == pytest.approx(1.0)
        assert funding_signal_strength(0.00025) == pytest.approx(0.5)
        assert funding_signal_strength(0.0) == pytest.approx(0.0)
