"""Phase C + Option B 전체 기능 TDD 테스트.

Coverage targets:
- 일별/주별 사이클 필터 (cache 1d/1w, MTF tf_1d/tf_1w)
- 롤링윈도우 스캐너 백테스터
- 그리드 파라미터 최적화
- 파라미터 config 이관 (scan_*() → config 참조)
- 자동 재최적화
- metrics (win_rate, profit_factor)
- Discord 커맨드 연동
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers: generate synthetic OHLCV data
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 200, base: float = 50000.0, seed: int = 42) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame with realistic price movement."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range(end=datetime.now(), periods=n, freq="5min")
    closes = [base]
    for _ in range(n - 1):
        change = rng.normal(0, base * 0.002)
        closes.append(max(closes[-1] + change, base * 0.8))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0.001, 0.005, n))
    lows = closes * (1 - rng.uniform(0.001, 0.005, n))
    opens = closes * (1 + rng.uniform(-0.003, 0.003, n))
    volumes = rng.uniform(10, 100, n)

    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
        "value": closes * volumes,
    }, index=dates)


def _make_daily_ohlcv(n: int = 60, base: float = 50000.0) -> pd.DataFrame:
    """Create synthetic daily OHLCV."""
    return _make_ohlcv(n, base, seed=100).resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "value": "sum",
    }).dropna()


def _make_weekly_ohlcv(n: int = 30, base: float = 50000.0) -> pd.DataFrame:
    """Create synthetic weekly OHLCV."""
    return _make_ohlcv(n * 5, base, seed=200).resample("1W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "value": "sum",
    }).dropna()


# ===========================================================================
# 1. OHLCV Cache — 1d/1w intervals + fetch_historical
# ===========================================================================

class TestCacheIntervals:
    """upbit_cache.py: 1d/1w 인터벌 지원."""

    def test_interval_map_contains_1d_1w(self):
        from engine.data.upbit_cache import INTERVAL_MAP
        assert "1d" in INTERVAL_MAP
        assert "1w" in INTERVAL_MAP
        assert INTERVAL_MAP["1d"] == "day"
        assert INTERVAL_MAP["1w"] == "week"

    def test_bar_counts_1d_1w(self):
        from engine.data.upbit_cache import BAR_COUNTS
        assert BAR_COUNTS["1d"] == 60
        assert BAR_COUNTS["1w"] == 26

    def test_ttl_map_1d_1w(self):
        from engine.data.upbit_cache import TTL_MAP
        assert TTL_MAP["1d"] == 3600
        assert TTL_MAP["1w"] == 7200

    def test_cache_put_get_1d(self):
        from engine.data.upbit_cache import OHLCVCacheManager
        cache = OHLCVCacheManager()
        df = _make_ohlcv(60)
        cache.put("KRW-BTC", "1d", df)
        result = cache.get("KRW-BTC", "1d")
        assert result is not None
        assert len(result) == 60
        cache.shutdown()

    def test_cache_put_get_1w(self):
        from engine.data.upbit_cache import OHLCVCacheManager
        cache = OHLCVCacheManager()
        df = _make_ohlcv(26)
        cache.put("KRW-BTC", "1w", df)
        result = cache.get("KRW-BTC", "1w")
        assert result is not None
        assert len(result) == 26
        cache.shutdown()

    def test_fetch_historical_method_exists(self):
        from engine.data.upbit_cache import OHLCVCacheManager
        cache = OHLCVCacheManager()
        assert hasattr(cache, "fetch_historical")
        cache.shutdown()

    @patch("pyupbit.get_ohlcv")
    def test_fetch_historical_pagination(self, mock_get_ohlcv):
        """fetch_historical이 200봉씩 역방향 페이징하는지 확인."""
        from engine.data.upbit_cache import OHLCVCacheManager

        # 200봉짜리 DataFrame 2개 (총 400봉 시뮬레이션)
        df1 = _make_ohlcv(200, seed=1)
        df2 = _make_ohlcv(200, seed=2)
        # 세번째 호출은 빈 결과 → 종료
        mock_get_ohlcv.side_effect = [df1, df2, None]

        cache = OHLCVCacheManager()
        result = cache.fetch_historical("KRW-BTC", "5m", days=2, max_bars=400)
        assert result is not None
        assert mock_get_ohlcv.call_count >= 2
        cache.shutdown()

    @patch("pyupbit.get_ohlcv")
    def test_fetch_historical_empty_result(self, mock_get_ohlcv):
        """데이터 없으면 None 반환."""
        from engine.data.upbit_cache import OHLCVCacheManager
        mock_get_ohlcv.return_value = None
        cache = OHLCVCacheManager()
        result = cache.fetch_historical("KRW-UNKNOWN", "5m", days=1)
        assert result is None
        cache.shutdown()


# ===========================================================================
# 2. MTF TrendContext — tf_1d/tf_1w 확장
# ===========================================================================

class TestMTFExtension:
    """upbit_mtf.py: TrendContext tf_1d/tf_1w + 필터 확장."""

    def test_trend_context_has_1d_1w_fields(self):
        from engine.strategy.upbit_mtf import TrendContext
        fields = list(TrendContext.__dataclass_fields__.keys())
        assert "tf_1d" in fields
        assert "tf_1w" in fields

    def test_trend_context_defaults_none(self):
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext()
        assert ctx.tf_1d is None
        assert ctx.tf_1w is None

    def test_analyze_mtf_accepts_1d_1w(self):
        import inspect
        from engine.strategy.upbit_mtf import analyze_mtf
        sig = inspect.signature(analyze_mtf)
        assert "df_1d" in sig.parameters
        assert "df_1w" in sig.parameters

    def test_analyze_mtf_with_daily_data(self):
        from engine.strategy.upbit_mtf import analyze_mtf
        df_15m = _make_ohlcv(100)
        df_1h = _make_ohlcv(50)
        df_1d = _make_ohlcv(60, seed=300)
        ctx = analyze_mtf(df_15m, df_1h, df_1d=df_1d)
        assert ctx.tf_15m is not None
        assert ctx.tf_1h is not None
        assert ctx.tf_1d is not None
        assert ctx.tf_1w is None

    def test_analyze_mtf_with_weekly_data(self):
        from engine.strategy.upbit_mtf import analyze_mtf
        df_15m = _make_ohlcv(100)
        df_1h = _make_ohlcv(50)
        df_1w = _make_ohlcv(30, seed=400)
        ctx = analyze_mtf(df_15m, df_1h, df_1w=df_1w)
        assert ctx.tf_1w is not None

    def test_analyze_mtf_skip_short_daily(self):
        """일봉 데이터 20봉 미만이면 tf_1d = None."""
        from engine.strategy.upbit_mtf import analyze_mtf
        df_15m = _make_ohlcv(100)
        df_1h = _make_ohlcv(50)
        df_1d_short = _make_ohlcv(10)  # < 20
        ctx = analyze_mtf(df_15m, df_1h, df_1d=df_1d_short)
        assert ctx.tf_1d is None

    def test_analyze_mtf_skip_short_weekly(self):
        """주봉 데이터 10봉 미만이면 tf_1w = None."""
        from engine.strategy.upbit_mtf import analyze_mtf
        df_15m = _make_ohlcv(100)
        df_1h = _make_ohlcv(50)
        df_1w_short = _make_ohlcv(5)  # < 10
        ctx = analyze_mtf(df_15m, df_1h, df_1w=df_1w_short)
        assert ctx.tf_1w is None

    def _make_trend(self, direction, strength=0.7, interval="1h"):
        from engine.strategy.upbit_mtf import TimeframeTrend, TrendDirection
        dir_map = {"BULLISH": TrendDirection.BULLISH, "BEARISH": TrendDirection.BEARISH, "NEUTRAL": TrendDirection.NEUTRAL}
        return TimeframeTrend(interval, dir_map[direction], strength, 100, 98, 55, 100, "")

    def test_allows_long_blocked_by_daily_bearish(self):
        """일봉 BEARISH (strength > 0.6)이면 LONG 차단."""
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH"),
            tf_1h=self._make_trend("BULLISH"),
            tf_1d=self._make_trend("BEARISH", strength=0.7),
        )
        assert ctx.allows_long() is False

    def test_allows_long_not_blocked_by_weekly(self):
        """주봉 BEARISH여도 LONG 차단하지 않음 (soft penalty만)."""
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH"),
            tf_1h=self._make_trend("BULLISH"),
            tf_1w=self._make_trend("BEARISH", strength=0.9),
        )
        assert ctx.allows_long() is True

    def test_allows_short_blocked_by_daily_bullish(self):
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BEARISH"),
            tf_1h=self._make_trend("BEARISH"),
            tf_1d=self._make_trend("BULLISH", strength=0.8),
        )
        assert ctx.allows_short() is False

    def test_confidence_boost_daily_aligned(self):
        """일봉이 순방향이면 1.2x 추가 boost."""
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH"),
            tf_1h=self._make_trend("BULLISH"),
            tf_1d=self._make_trend("BULLISH", strength=0.7),
        )
        boost = ctx.confidence_boost()
        # 15m+1h aligned (1.3) * 1d boost (1.2) = 1.56
        assert boost > 1.3

    def test_confidence_boost_weekly_penalty(self):
        """주봉 역방향 (strength > 0.7)이면 0.8x penalty."""
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH"),
            tf_1h=self._make_trend("BULLISH"),
            tf_1w=self._make_trend("BEARISH", strength=0.8),
        )
        boost = ctx.confidence_boost()
        # 1.3 * 0.8 = 1.04
        assert boost < 1.3

    def test_summary_includes_1d_1w(self):
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH", interval="15m"),
            tf_1h=self._make_trend("BEARISH", interval="1h"),
            tf_1d=self._make_trend("BULLISH", interval="1d"),
            tf_1w=self._make_trend("NEUTRAL", interval="1w"),
        )
        s = ctx.summary()
        assert "1d=BULLISH" in s
        assert "1w=NEUTRAL" in s

    def test_to_dict_includes_1d_1w(self):
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH", interval="15m"),
            tf_1h=self._make_trend("BULLISH", interval="1h"),
            tf_1d=self._make_trend("BEARISH", interval="1d"),
        )
        d = ctx.to_dict()
        assert "1d" in d
        assert "1w" in d
        assert d["1d"] is not None
        assert d["1w"] is None

    def test_mtf_filter_signal_blocker_info(self):
        """차단 시 어떤 타임프레임이 차단했는지 표시."""
        from engine.strategy.upbit_mtf import TrendContext, mtf_filter_signal
        ctx = TrendContext(
            tf_15m=self._make_trend("BULLISH", interval="15m"),
            tf_1h=self._make_trend("BULLISH", interval="1h"),
            tf_1d=self._make_trend("BEARISH", strength=0.8, interval="1d"),
        )
        allowed, boost, reason = mtf_filter_signal("LONG", ctx)
        assert allowed is False
        assert "차단" in reason
        assert "1d" in reason


# ===========================================================================
# 3. Scanner Config — 사이클 필터 + 지표 파라미터
# ===========================================================================

class TestScannerConfig:
    """UpbitScannerConfig: 사이클 필터 + 전략별 파라미터 필드."""

    def test_daily_filter_default_on(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.enable_daily_filter is True

    def test_weekly_filter_default_on(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.enable_weekly_filter is True

    def test_bb_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.bb_period == 20
        assert cfg.bb_std == 2.0

    def test_supertrend_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.supertrend_period == 10
        assert cfg.supertrend_multiplier == 3.0

    def test_macd_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.macd_fast == 12
        assert cfg.macd_slow == 26
        assert cfg.macd_signal == 9

    def test_stoch_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.stoch_period == 14
        assert cfg.stoch_k == 3
        assert cfg.stoch_d == 3

    def test_ichimoku_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.ichimoku_tenkan == 9
        assert cfg.ichimoku_kijun == 26
        assert cfg.ichimoku_senkou == 52

    def test_adx_atr_params(self):
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig()
        assert cfg.adx_period == 14
        assert cfg.atr_period == 14

    def test_config_serialization_new_fields(self):
        """새 필드가 JSON 직렬화/역직렬화에 포함되는지."""
        from dataclasses import asdict
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig(supertrend_period=15, ichimoku_tenkan=7)
        d = asdict(cfg)
        assert d["supertrend_period"] == 15
        assert d["ichimoku_tenkan"] == 7
        assert "enable_daily_filter" in d
        assert "bb_period" in d


# ===========================================================================
# 4. Metrics — win_rate / profit_factor
# ===========================================================================

class TestMetrics:
    """metrics.py: compute_win_rate, compute_profit_factor."""

    def test_win_rate_basic(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([0.01, 0.02, -0.01]) == pytest.approx(2 / 3, abs=0.01)

    def test_win_rate_all_winners(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([0.01, 0.02, 0.03]) == 1.0

    def test_win_rate_all_losers(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([-0.01, -0.02]) == 0.0

    def test_win_rate_empty(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([]) == 0.0

    def test_win_rate_zero_pnl_not_winner(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([0.0, 0.01]) == 0.5

    def test_profit_factor_basic(self):
        from engine.backtest.metrics import compute_profit_factor
        # wins: 0.03+0.01=0.04, losses: abs(-0.02)=0.02 → PF=2.0
        pf = compute_profit_factor([0.03, -0.02, 0.01])
        assert pf == pytest.approx(2.0, abs=0.01)

    def test_profit_factor_no_losses(self):
        from engine.backtest.metrics import compute_profit_factor
        assert compute_profit_factor([0.01, 0.02]) == float("inf")

    def test_profit_factor_no_wins(self):
        from engine.backtest.metrics import compute_profit_factor
        assert compute_profit_factor([-0.01, -0.02]) == 0.0

    def test_profit_factor_empty(self):
        from engine.backtest.metrics import compute_profit_factor
        assert compute_profit_factor([]) == 0.0

    def test_profit_factor_balanced(self):
        from engine.backtest.metrics import compute_profit_factor
        # Equal win and loss → PF = 1.0
        assert compute_profit_factor([0.01, -0.01]) == pytest.approx(1.0)


# ===========================================================================
# 5. Scanner Backtest — 롤링윈도우 백테스터
# ===========================================================================

class TestScannerBacktest:
    """scanner_backtest.py: ScannerBacktester, TradeResult, BacktestReport."""

    def test_trade_result_creation(self):
        from engine.backtest.scanner_backtest import TradeResult
        tr = TradeResult(
            entry_time=datetime.now(),
            entry_price=50000,
            side="LONG",
            sl=49000,
            tp1=51000,
            tp2=52000,
            tp3=53000,
        )
        assert tr.side == "LONG"
        assert tr.pnl_pct == 0.0
        assert tr.exit_reason == ""

    def test_trade_result_to_dict(self):
        from engine.backtest.scanner_backtest import TradeResult
        tr = TradeResult(
            entry_time=datetime.now(),
            entry_price=50000,
            side="SHORT",
            sl=51000,
            tp1=49000,
            tp2=None,
            tp3=None,
            pnl_pct=-0.02,
        )
        d = tr.to_dict()
        assert d["side"] == "SHORT"
        assert d["pnl_pct"] == -0.02

    def test_backtest_report_summary_text(self):
        from engine.backtest.scanner_backtest import BacktestReport
        report = BacktestReport(
            strategy_name="SMC",
            symbol="KRW-BTC",
            interval="5m",
            period="2026-01-01 ~ 2026-01-31",
            total_trades=50,
            win_rate=0.6,
            profit_factor=1.8,
            total_return_pct=5.5,
            max_drawdown_pct=3.2,
            sharpe_ratio=1.5,
            avg_trade_pct=0.11,
            avg_winner_pct=0.3,
            avg_loser_pct=-0.18,
        )
        text = report.summary_text()
        assert "SMC" in text
        assert "60.0%" in text
        assert "1.80" in text

    def test_backtest_report_to_dict(self):
        from engine.backtest.scanner_backtest import BacktestReport
        report = BacktestReport(
            strategy_name="EMA", symbol="KRW-ETH", interval="5m",
            period="test", total_trades=10, win_rate=0.5,
            profit_factor=1.2, total_return_pct=2.0,
            max_drawdown_pct=1.5, sharpe_ratio=0.8,
            avg_trade_pct=0.2, avg_winner_pct=0.5, avg_loser_pct=-0.3,
        )
        d = report.to_dict()
        assert d["strategy_name"] == "EMA"
        assert d["total_trades"] == 10

    def test_empty_report_on_insufficient_data(self):
        """데이터 부족 시 빈 리포트 반환."""
        from engine.backtest.scanner_backtest import ScannerBacktester, ScannerBacktestConfig
        from engine.data.upbit_cache import OHLCVCacheManager

        cache = MagicMock(spec=OHLCVCacheManager)
        cache.fetch_historical.return_value = _make_ohlcv(10)  # Too short

        bt = ScannerBacktester(cache)
        config = ScannerBacktestConfig(
            strategy_fn=lambda df, sym, cfg: None,
            strategy_name="Test",
            symbol="KRW-BTC",
            lookback_bars=100,
        )
        report = asyncio.get_event_loop().run_until_complete(bt.run(config))
        assert report.total_trades == 0

    def test_backtester_pnl_calculation(self):
        """PnL 계산 정확성 (수수료 포함)."""
        from engine.backtest.scanner_backtest import ScannerBacktester, TradeResult
        cache = MagicMock()
        bt = ScannerBacktester(cache)

        trade = TradeResult(
            entry_time=datetime.now(), entry_price=100,
            side="LONG", sl=95, tp1=105, tp2=None, tp3=None,
            exit_price=105,
        )
        pnl = bt._calc_pnl(trade, commission=0.001)
        # (105-100)/100 - 0.001 = 0.049
        assert abs(pnl - 0.049) < 0.001

    def test_backtester_pnl_short(self):
        """SHORT PnL 계산."""
        from engine.backtest.scanner_backtest import ScannerBacktester, TradeResult
        cache = MagicMock()
        bt = ScannerBacktester(cache)

        trade = TradeResult(
            entry_time=datetime.now(), entry_price=100,
            side="SHORT", sl=105, tp1=95, tp2=None, tp3=None,
            exit_price=95,
        )
        pnl = bt._calc_pnl(trade, commission=0.001)
        # (100-95)/100 - 0.001 = 0.049
        assert abs(pnl - 0.049) < 0.001

    def test_backtester_exit_price_sl(self):
        from engine.backtest.scanner_backtest import ScannerBacktester, TradeResult
        bt = ScannerBacktester(MagicMock())
        trade = TradeResult(
            entry_time=datetime.now(), entry_price=100,
            side="LONG", sl=95, tp1=105, tp2=110, tp3=115,
        )
        bar = pd.Series({"high": 104, "low": 94, "close": 96})
        price = bt._get_exit_price(trade, bar, "SL")
        assert price == 95

    def test_backtester_exit_price_tp_levels(self):
        from engine.backtest.scanner_backtest import ScannerBacktester, TradeResult
        bt = ScannerBacktester(MagicMock())
        trade = TradeResult(
            entry_time=datetime.now(), entry_price=100,
            side="LONG", sl=95, tp1=105, tp2=110, tp3=115,
        )
        bar = pd.Series({"high": 116, "low": 99, "close": 112})
        assert bt._get_exit_price(trade, bar, "TP1") == 105
        assert bt._get_exit_price(trade, bar, "TP2") == 110
        assert bt._get_exit_price(trade, bar, "TP3") == 115

    def test_compile_report_with_trades(self):
        """거래 목록으로 리포트 컴파일."""
        from engine.backtest.scanner_backtest import ScannerBacktester, ScannerBacktestConfig, TradeResult

        bt = ScannerBacktester(MagicMock())
        df = _make_ohlcv(200)
        trades = [
            TradeResult(datetime.now(), 100, "LONG", 95, 105, None, None,
                        datetime.now(), 105, "TP1", 0.049, 0.7),
            TradeResult(datetime.now(), 100, "LONG", 95, 105, None, None,
                        datetime.now(), 95, "SL", -0.051, 0.6),
            TradeResult(datetime.now(), 100, "LONG", 95, 105, None, None,
                        datetime.now(), 103, "TIMEOUT", 0.029, 0.5),
        ]
        config = ScannerBacktestConfig(
            strategy_fn=lambda *a: None,
            strategy_name="Test", symbol="KRW-BTC",
        )
        report = bt._compile_report(trades, config, df)
        assert report.total_trades == 3
        assert report.win_rate == pytest.approx(2 / 3, abs=0.01)
        assert report.profit_factor > 0


# ===========================================================================
# 6. Scanner Optimizer — 그리드 파라미터 최적화
# ===========================================================================

class TestScannerOptimizer:
    """scanner_optimizer.py: ParamRange, OptimizeResult, ScannerOptimizer."""

    def test_param_range_creation(self):
        from engine.backtest.scanner_optimizer import ParamRange
        pr = ParamRange("rsi_period", [10, 14, 20])
        assert pr.name == "rsi_period"
        assert len(pr.values) == 3

    def test_optimize_result_summary(self):
        from engine.backtest.scanner_optimizer import OptimizeResult
        result = OptimizeResult(
            best_params={"rsi_period": 14, "sl_pct": 0.01},
            best_sharpe=1.5,
            best_win_rate=0.6,
            best_profit_factor=2.0,
        )
        text = result.summary_text()
        assert "rsi_period" in text
        assert "1.50" in text

    def test_default_param_ranges_all_strategies(self):
        from engine.backtest.scanner_optimizer import DEFAULT_PARAM_RANGES
        assert len(DEFAULT_PARAM_RANGES) == 10
        expected = [
            "EMA+RSI+VWAP", "Supertrend", "MACD Divergence", "StochRSI",
            "Fibonacci", "Ichimoku", "Early Pump", "SMC", "Hidden Div", "BB+RSI+Stoch",
        ]
        for name in expected:
            assert name in DEFAULT_PARAM_RANGES, f"{name} missing"

    def test_default_param_ranges_use_indicator_params(self):
        """새로 이관된 지표 파라미터가 범위에 포함되는지."""
        from engine.backtest.scanner_optimizer import DEFAULT_PARAM_RANGES
        # Supertrend
        st_params = [r.name for r in DEFAULT_PARAM_RANGES["Supertrend"]]
        assert "supertrend_period" in st_params
        assert "supertrend_multiplier" in st_params
        # MACD
        macd_params = [r.name for r in DEFAULT_PARAM_RANGES["MACD Divergence"]]
        assert "macd_fast" in macd_params
        assert "macd_slow" in macd_params
        assert "macd_signal" in macd_params
        # Ichimoku
        ichi_params = [r.name for r in DEFAULT_PARAM_RANGES["Ichimoku"]]
        assert "ichimoku_tenkan" in ichi_params
        assert "ichimoku_kijun" in ichi_params
        # StochRSI
        stoch_params = [r.name for r in DEFAULT_PARAM_RANGES["StochRSI"]]
        assert "stoch_period" in stoch_params
        # BB+RSI+Stoch
        bb_params = [r.name for r in DEFAULT_PARAM_RANGES["BB+RSI+Stoch"]]
        assert "bb_period" in bb_params

    def test_optimizer_min_trades_filter(self):
        """최소 거래 수 미달 시 결과 제외."""
        from engine.backtest.scanner_optimizer import ScannerOptimizer, ParamRange
        from engine.backtest.scanner_backtest import ScannerBacktester, BacktestReport

        mock_bt = MagicMock(spec=ScannerBacktester)
        # Return report with only 2 trades (below min_trades=10)
        mock_report = BacktestReport(
            strategy_name="Test", symbol="KRW-BTC", interval="5m",
            period="test", total_trades=2, win_rate=1.0,
            profit_factor=float("inf"), total_return_pct=10.0,
            max_drawdown_pct=0.0, sharpe_ratio=5.0,
            avg_trade_pct=5.0, avg_winner_pct=5.0, avg_loser_pct=0.0,
        )
        mock_bt.run = AsyncMock(return_value=mock_report)

        optimizer = ScannerOptimizer(mock_bt)
        result = asyncio.get_event_loop().run_until_complete(
            optimizer.grid_search(
                strategy_fn=lambda *a: None,
                strategy_name="Test",
                symbol="KRW-BTC",
                param_ranges=[ParamRange("rsi_period", [10, 14])],
                days=30,
                min_trades=10,
            )
        )
        assert result.best_params == {}  # No valid results


# ===========================================================================
# 7. Auto Re-optimization
# ===========================================================================

class TestAutoReoptimize:
    """auto_reoptimize.py: 스케줄러 + 파라미터 저장/로드."""

    def test_strategy_map_complete(self):
        from engine.backtest.auto_reoptimize import STRATEGY_MAP
        assert len(STRATEGY_MAP) == 10
        assert "SMC" in STRATEGY_MAP
        assert "Ichimoku" in STRATEGY_MAP

    def test_load_optimized_params_no_file(self):
        from engine.backtest.auto_reoptimize import load_optimized_params
        # Should return empty dict if file doesn't exist
        with patch("engine.backtest.auto_reoptimize.OPTIMIZED_PARAMS_PATH") as mock_path:
            mock_path.exists.return_value = False
            result = load_optimized_params()
            assert result == {}

    def test_scheduler_creation(self):
        from engine.backtest.auto_reoptimize import ReoptimizeScheduler
        sched = ReoptimizeScheduler(
            symbols=["KRW-BTC"],
            interval_sec=86400,
            days=14,
        )
        assert sched._running is False
        assert sched.symbols == ["KRW-BTC"]
        assert sched.interval_sec == 86400
        assert sched.days == 14

    def test_scheduler_status(self):
        from engine.backtest.auto_reoptimize import ReoptimizeScheduler
        sched = ReoptimizeScheduler()
        st = sched.status()
        assert st["running"] is False
        assert st["interval_sec"] == 604800
        assert st["last_run"] is None
        assert isinstance(st["symbols"], list)

    def test_scheduler_default_symbols(self):
        from engine.backtest.auto_reoptimize import ReoptimizeScheduler
        sched = ReoptimizeScheduler()
        assert "KRW-BTC" in sched.symbols
        assert "KRW-ETH" in sched.symbols


# ===========================================================================
# 8. scan_*() config 파라미터 연동
# ===========================================================================

class TestScanConfigIntegration:
    """scan_*() 함수들이 config에서 파라미터를 읽는지 확인."""

    def test_supertrend_uses_config_period(self):
        """scan_supertrend이 config.supertrend_period를 사용하는지."""
        import inspect
        from engine.strategy.upbit_scanner import scan_supertrend
        sig = inspect.signature(scan_supertrend)
        # period default is now None (reads from config)
        assert sig.parameters["period"].default is None

    def test_supertrend_uses_config_multiplier(self):
        import inspect
        from engine.strategy.upbit_scanner import scan_supertrend
        sig = inspect.signature(scan_supertrend)
        assert sig.parameters["multiplier"].default is None

    def test_macd_uses_config_params(self):
        import inspect
        from engine.strategy.upbit_scanner import scan_macd_divergence
        sig = inspect.signature(scan_macd_divergence)
        assert sig.parameters["fast"].default is None
        assert sig.parameters["slow"].default is None
        assert sig.parameters["signal_period"].default is None

    def test_stoch_rsi_uses_config_params(self):
        import inspect
        from engine.strategy.upbit_scanner import scan_stoch_rsi
        sig = inspect.signature(scan_stoch_rsi)
        assert sig.parameters["rsi_period"].default is None
        assert sig.parameters["stoch_period"].default is None
        assert sig.parameters["k_period"].default is None
        assert sig.parameters["d_period"].default is None

    def test_ichimoku_uses_config_params(self):
        import inspect
        from engine.strategy.upbit_scanner import scan_ichimoku
        sig = inspect.signature(scan_ichimoku)
        assert sig.parameters["tenkan_period"].default is None
        assert sig.parameters["kijun_period"].default is None
        assert sig.parameters["senkou_period"].default is None

    def test_scan_functions_work_with_default_config(self):
        """모든 scan 함수가 기본 config로 에러 없이 실행되는지."""
        from engine.strategy.upbit_scanner import (
            UpbitScannerConfig,
            scan_supertrend, scan_macd_divergence, scan_stoch_rsi,
            scan_fibonacci, scan_ichimoku, scan_hidden_divergence,
            scan_bb_rsi_stoch, scan_ema_rsi_vwap,
        )
        cfg = UpbitScannerConfig()
        df = _make_ohlcv(200)

        # These should not raise — signal may be None (no valid signal in synthetic data)
        for name, fn in [
            ("ema_rsi_vwap", scan_ema_rsi_vwap),
            ("supertrend", scan_supertrend),
            ("macd", scan_macd_divergence),
            ("stoch_rsi", scan_stoch_rsi),
            ("fibonacci", scan_fibonacci),
            ("ichimoku", scan_ichimoku),
            ("hidden_div", scan_hidden_divergence),
            ("bb_rsi_stoch", scan_bb_rsi_stoch),
        ]:
            try:
                result = fn(df, "KRW-BTC", cfg)
                # result can be None or Signal — both OK
            except Exception as e:
                pytest.fail(f"{name} raised {type(e).__name__}: {e}")

    def test_scan_with_custom_config(self):
        """커스텀 파라미터로 scan 함수 실행."""
        from engine.strategy.upbit_scanner import UpbitScannerConfig, scan_supertrend
        cfg = UpbitScannerConfig(supertrend_period=7, supertrend_multiplier=2.0)
        df = _make_ohlcv(200)
        # Should not raise
        result = scan_supertrend(df, "KRW-BTC", cfg)
        # result can be None

    def test_scan_with_explicit_params_override(self):
        """함수 인자로 직접 전달하면 config보다 우선."""
        from engine.strategy.upbit_scanner import UpbitScannerConfig, scan_supertrend
        cfg = UpbitScannerConfig(supertrend_period=10)
        df = _make_ohlcv(200)
        # Explicit period=7 should override config's 10
        result = scan_supertrend(df, "KRW-BTC", cfg, period=7, multiplier=2.0)
        # No error = success


# ===========================================================================
# 9. __init__.py exports
# ===========================================================================

class TestExports:
    """engine/backtest/__init__.py re-exports."""

    def test_all_exports_available(self):
        from engine.backtest import (
            BacktestRunner, BacktestResult, TradeRecord,
            compute_total_return, compute_sharpe_ratio, compute_max_drawdown,
            compute_win_rate, compute_profit_factor,
            generate_report, generate_summary,
            GridOptimizer, OptimizationResult,
            ScannerBacktester, ScannerBacktestConfig, BacktestReport, TradeResult,
            ScannerOptimizer, OptimizeResult, ParamRange,
            ReoptimizeScheduler, reoptimize_symbol,
        )
        # All should be importable
        assert ScannerBacktester is not None
        assert ReoptimizeScheduler is not None


# ===========================================================================
# 10. Edge cases & error handling
# ===========================================================================

class TestEdgeCases:
    """경계 케이스 + 에러 핸들링."""

    def test_trend_context_all_none(self):
        from engine.strategy.upbit_mtf import TrendContext
        ctx = TrendContext()
        assert ctx.allows_long() is True
        assert ctx.allows_short() is True
        assert ctx.confidence_boost() == 1.0
        assert ctx.dominant_direction.value == "NEUTRAL"
        assert "N/A" in ctx.summary()

    def test_analyze_timeframe_empty_array(self):
        """빈 배열에서 np.isnan 에러 안 나는지."""
        from engine.strategy.upbit_mtf import analyze_timeframe
        df = _make_ohlcv(5)  # Too short
        result = analyze_timeframe(df, "5m")
        assert result is None

    def test_profit_factor_single_trade(self):
        from engine.backtest.metrics import compute_profit_factor
        assert compute_profit_factor([0.05]) == float("inf")
        assert compute_profit_factor([-0.05]) == 0.0

    def test_win_rate_single_trade(self):
        from engine.backtest.metrics import compute_win_rate
        assert compute_win_rate([0.01]) == 1.0
        assert compute_win_rate([-0.01]) == 0.0

    def test_cache_stats_with_1d_1w(self):
        from engine.data.upbit_cache import OHLCVCacheManager
        cache = OHLCVCacheManager()
        cache.put("KRW-BTC", "1d", _make_ohlcv(60))
        cache.put("KRW-BTC", "1w", _make_ohlcv(26))
        stats = cache.stats()
        assert "1d" in stats["by_interval"]
        assert "1w" in stats["by_interval"]
        cache.shutdown()

    def test_backtest_report_inf_profit_factor_to_dict(self):
        """profit_factor=inf일 때 to_dict 직렬화 가능."""
        from engine.backtest.scanner_backtest import BacktestReport
        report = BacktestReport(
            strategy_name="Test", symbol="KRW-BTC", interval="5m",
            period="test", total_trades=5, win_rate=1.0,
            profit_factor=float("inf"), total_return_pct=10.0,
            max_drawdown_pct=0.0, sharpe_ratio=3.0,
            avg_trade_pct=2.0, avg_winner_pct=2.0, avg_loser_pct=0.0,
        )
        d = report.to_dict()
        assert d["profit_factor"] == 999.0  # Capped for serialization


# ===========================================================================
# 11. 누락 기능별 테스트 — 기능당 최소 1개 보장
# ===========================================================================

class TestAutoReoptimizeExtended:
    """auto_reoptimize.py 추가 커버리지."""

    def test_save_load_optimized_params_roundtrip(self, tmp_path):
        """save → load 라운드트립."""
        from engine.backtest.auto_reoptimize import save_optimized_params, load_optimized_params, OPTIMIZED_PARAMS_PATH
        import json
        # 임시 경로로 덮어씌워 테스트
        original = OPTIMIZED_PARAMS_PATH
        import engine.backtest.auto_reoptimize as mod
        mod.OPTIMIZED_PARAMS_PATH = tmp_path / "optimized_params.json"
        try:
            data = {"KRW-BTC": {"strategies": {"SMC": {"params": {"rsi_period": 14}}}}}
            save_optimized_params(data)
            loaded = load_optimized_params()
            assert loaded["KRW-BTC"]["strategies"]["SMC"]["params"]["rsi_period"] == 14
        finally:
            mod.OPTIMIZED_PARAMS_PATH = original

    def test_get_scan_fn_lazy_import(self):
        """_get_scan_fn으로 scan 함수 lazy import."""
        from engine.backtest.auto_reoptimize import _get_scan_fn
        fn = _get_scan_fn("scan_smc")
        assert callable(fn)
        assert fn.__name__ == "scan_smc"

    def test_get_scan_fn_all_strategies(self):
        """STRATEGY_MAP의 모든 함수가 lazy import 가능."""
        from engine.backtest.auto_reoptimize import _get_scan_fn, STRATEGY_MAP
        for strat_name, fn_name in STRATEGY_MAP.items():
            fn = _get_scan_fn(fn_name)
            assert callable(fn), f"{strat_name} → {fn_name} not callable"

    def test_scheduler_start_stop(self):
        """스케줄러 start/stop 토글."""
        from engine.backtest.auto_reoptimize import ReoptimizeScheduler
        sched = ReoptimizeScheduler(symbols=["KRW-BTC"], interval_sec=9999)
        assert not sched._running
        sched.start()
        assert sched._running
        assert sched._task is not None
        sched.stop()
        assert not sched._running
        assert sched._task is None

    def test_apply_best_params(self):
        """_apply_best_params가 config에 파라미터 적용."""
        from engine.backtest.auto_reoptimize import _apply_best_params
        from engine.strategy.upbit_scanner import UpbitScannerConfig, update_config, _config
        # 원래 값 백업
        import engine.strategy.upbit_scanner as scanner_mod
        orig_rsi = scanner_mod._config.rsi_period if scanner_mod._config else 14
        try:
            results = {
                "SMC": {"params": {"rsi_period": 18}, "train_sharpe": 2.0},
                "Ichimoku": {"params": {"rsi_period": 20}, "train_sharpe": 1.5},
            }
            _apply_best_params(results)
            # SMC가 Sharpe 더 높으므로 rsi_period=18이 우선
            assert scanner_mod._config.rsi_period == 18
        finally:
            update_config({"rsi_period": orig_rsi})


class TestScannerBacktestExtended:
    """scanner_backtest.py 추가 커버리지."""

    def test_run_with_mock_signals(self):
        """시그널 발생 시 트레이드가 기록되는지."""
        from engine.backtest.scanner_backtest import ScannerBacktester, ScannerBacktestConfig, BacktestReport
        from engine.data.upbit_cache import OHLCVCacheManager

        # 300봉 데이터
        df = _make_ohlcv(300, base=50000)

        # 50번째 봉마다 시그널 반환하는 mock 전략
        call_count = {"n": 0}
        class FakeSignal:
            def __init__(self):
                self.side = "LONG"
                self.sl = 49000
                self.tp1 = 51000
                self.tp2 = 52000
                self.tp3 = 53000
                self.confidence = 0.8

        def mock_strategy(df_window, symbol, cfg, **kwargs):
            call_count["n"] += 1
            if call_count["n"] % 50 == 0:
                return FakeSignal()
            return None

        cache = MagicMock(spec=OHLCVCacheManager)
        cache.fetch_historical.return_value = df

        bt = ScannerBacktester(cache)
        config = ScannerBacktestConfig(
            strategy_fn=mock_strategy,
            strategy_name="MockStrat",
            symbol="KRW-BTC",
            lookback_bars=100,
            days=5,
        )
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(bt.run(config))
        finally:
            loop.close()

        assert isinstance(report, BacktestReport)
        assert report.strategy_name == "MockStrat"
        # mock이 50봉마다 시그널 → 최소 1개 트레이드 발생
        assert report.total_trades >= 1

    def test_trade_timeout_via_run(self):
        """50봉 내 SL/TP 미도달 시 TIMEOUT으로 청산."""
        from engine.backtest.scanner_backtest import ScannerBacktester, ScannerBacktestConfig
        from engine.data.upbit_cache import OHLCVCacheManager

        df = _make_ohlcv(300, base=50000)

        # 아주 먼 SL/TP로 시그널 → 반드시 TIMEOUT
        class FakeSignal:
            side = "LONG"
            sl = 1000       # 매우 낮은 SL (절대 안 닿음)
            tp1 = 999999    # 매우 높은 TP (절대 안 닿음)
            tp2 = 999999
            tp3 = 999999
            confidence = 0.7

        call_count = {"n": 0}
        def timeout_strategy(df_window, symbol, cfg, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 50:  # 딱 1번만 시그널
                return FakeSignal()
            return None

        cache = MagicMock(spec=OHLCVCacheManager)
        cache.fetch_historical.return_value = df
        bt = ScannerBacktester(cache)
        config = ScannerBacktestConfig(
            strategy_fn=timeout_strategy, strategy_name="Timeout",
            symbol="KRW-BTC", lookback_bars=100, days=5,
        )
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            report = loop.run_until_complete(bt.run(config))
        finally:
            loop.close()
        # TIMEOUT 트레이드가 있어야 함
        timeout_trades = [t for t in report.trades if t.exit_reason == "TIMEOUT"]
        assert len(timeout_trades) >= 1

    def test_backtest_report_zero_sharpe(self):
        """sharpe_ratio=0일 때 summary_text 정상."""
        from engine.backtest.scanner_backtest import BacktestReport
        report = BacktestReport(
            strategy_name="Test", symbol="X", interval="5m",
            period="t", total_trades=1, win_rate=0.0,
            profit_factor=0.0, total_return_pct=-1.0,
            max_drawdown_pct=1.0, sharpe_ratio=0.0,
            avg_trade_pct=-1.0, avg_winner_pct=0.0, avg_loser_pct=-1.0,
        )
        text = report.summary_text()
        assert "0.00" in text  # sharpe 0.00


class TestScannerOptimizerExtended:
    """scanner_optimizer.py 추가 커버리지."""

    def test_grid_search_full_flow(self):
        """grid_search 전체 플로우 (mock backtester)."""
        from engine.backtest.scanner_optimizer import ScannerOptimizer, ParamRange
        from engine.backtest.scanner_backtest import ScannerBacktester, BacktestReport

        # Mock backtester
        mock_bt = MagicMock(spec=ScannerBacktester)

        # 파라미터에 따라 다른 성능을 반환하는 mock
        async def mock_run(config):
            period = config.scanner_config.rsi_period if hasattr(config.scanner_config, 'rsi_period') else 14
            sharpe = 1.0 + (period - 10) * 0.1  # period가 클수록 sharpe 높음
            return BacktestReport(
                strategy_name="Test", symbol="KRW-BTC", interval="5m",
                period="test", total_trades=20, win_rate=0.55,
                profit_factor=1.3, total_return_pct=3.0,
                max_drawdown_pct=2.0, sharpe_ratio=sharpe,
                avg_trade_pct=0.15, avg_winner_pct=0.5, avg_loser_pct=-0.3,
            )

        mock_bt.run = mock_run
        optimizer = ScannerOptimizer(mock_bt)

        param_ranges = [ParamRange("rsi_period", [10, 14, 20])]

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                optimizer.grid_search(
                    strategy_fn=lambda df, sym, cfg: None,
                    strategy_name="Test",
                    symbol="KRW-BTC",
                    param_ranges=param_ranges,
                    days=14,
                    min_trades=5,
                )
            )
        finally:
            loop.close()

        assert result.best_params["rsi_period"] == 20  # highest sharpe
        assert result.best_sharpe > 1.5
        assert len(result.grid_results) == 3

    def test_optimize_result_summary_with_test(self):
        """test 결과 포함된 summary_text."""
        from engine.backtest.scanner_optimizer import OptimizeResult
        opt = OptimizeResult(
            best_params={"rsi_period": 14},
            best_sharpe=1.5,
            best_win_rate=0.65,
            best_profit_factor=1.8,
            test_sharpe=1.2,
            test_win_rate=0.60,
            test_profit_factor=1.5,
            grid_results=[{}, {}, {}],
        )
        text = opt.summary_text()
        assert "Train" in text
        assert "Test" in text
        assert "3개 조합" in text


class TestMTFFilterSignal:
    """mtf_filter_signal() 실제 필터링 동작."""

    def test_long_allowed_when_aligned(self):
        from engine.strategy.upbit_mtf import mtf_filter_signal, TrendContext, TimeframeTrend, TrendDirection
        def _tt(d, s):
            return TimeframeTrend(interval='1h', direction=d, strength=s, ema_fast=100, ema_slow=99, rsi=55, price=50000, detail='test')
        ctx = TrendContext(tf_15m=_tt(TrendDirection.BULLISH, 0.7), tf_1h=_tt(TrendDirection.BULLISH, 0.6))
        allowed, boost, reason = mtf_filter_signal("LONG", ctx)
        assert allowed is True
        assert boost >= 1.0

    def test_long_blocked_by_bearish_1h(self):
        from engine.strategy.upbit_mtf import mtf_filter_signal, TrendContext, TimeframeTrend, TrendDirection
        def _tt(d, s):
            return TimeframeTrend(interval='1h', direction=d, strength=s, ema_fast=100, ema_slow=101, rsi=40, price=50000, detail='test')
        ctx = TrendContext(tf_15m=_tt(TrendDirection.BEARISH, 0.8), tf_1h=_tt(TrendDirection.BEARISH, 0.8))
        allowed, boost, reason = mtf_filter_signal("LONG", ctx)
        assert allowed is False

    def test_short_blocked_by_bullish_daily(self):
        from engine.strategy.upbit_mtf import mtf_filter_signal, TrendContext, TimeframeTrend, TrendDirection
        def _tt(d, s):
            return TimeframeTrend(interval='1d', direction=d, strength=s, ema_fast=100, ema_slow=99, rsi=60, price=50000, detail='test')
        ctx = TrendContext(
            tf_15m=_tt(TrendDirection.NEUTRAL, 0.3),
            tf_1h=_tt(TrendDirection.NEUTRAL, 0.3),
            tf_1d=_tt(TrendDirection.BULLISH, 0.8),
        )
        allowed, boost, reason = mtf_filter_signal("SHORT", ctx)
        assert allowed is False

    def test_weekly_penalty_in_boost(self):
        """주봉 역방향 시 boost < 1.0 (soft penalty)."""
        from engine.strategy.upbit_mtf import mtf_filter_signal, TrendContext, TimeframeTrend, TrendDirection
        def _tt(d, s):
            return TimeframeTrend(interval='1h', direction=d, strength=s, ema_fast=100, ema_slow=99, rsi=55, price=50000, detail='test')
        ctx = TrendContext(
            tf_15m=_tt(TrendDirection.BULLISH, 0.7),
            tf_1h=_tt(TrendDirection.BULLISH, 0.7),
            tf_1w=_tt(TrendDirection.BEARISH, 0.8),
        )
        allowed, boost, reason = mtf_filter_signal("LONG", ctx)
        assert allowed is True
        assert boost < 1.3  # weekly penalty applied


class TestUpdateConfig:
    """update_config() 테스트."""

    def test_update_config_applies_values(self):
        from engine.strategy.upbit_scanner import update_config
        import engine.strategy.upbit_scanner as mod
        orig = mod._config.rsi_period if mod._config else 14
        try:
            update_config({"rsi_period": 20})
            assert mod._config.rsi_period == 20
        finally:
            update_config({"rsi_period": orig})

    def test_update_config_ignores_unknown_fields(self):
        from engine.strategy.upbit_scanner import update_config
        import engine.strategy.upbit_scanner as mod
        # Should not raise
        update_config({"nonexistent_field_xyz": 999})


class TestScanEarlyPumpSMC:
    """scan_early_pump / scan_smc config 연동."""

    def test_scan_early_pump_no_crash(self):
        from engine.strategy.upbit_scanner import scan_early_pump, UpbitScannerConfig
        cfg = UpbitScannerConfig()
        df = _make_ohlcv(300, base=50000)
        result = scan_early_pump(df, "KRW-BTC", cfg)
        # None or Signal — both OK

    def test_scan_smc_no_crash(self):
        from engine.strategy.upbit_scanner import scan_smc, UpbitScannerConfig
        cfg = UpbitScannerConfig()
        df = _make_ohlcv(300, base=50000)
        result = scan_smc(df, "KRW-BTC", cfg)
        # None or Signal — both OK

    def test_scan_smc_uses_config_sl_tp_mode(self):
        """scan_smc가 cfg.sl_mode/tp_mode를 참조하는지."""
        import inspect
        from engine.strategy.upbit_scanner import scan_smc
        src = inspect.getsource(scan_smc)
        assert "cfg.sl_mode" in src and "cfg.tp_mode" in src
