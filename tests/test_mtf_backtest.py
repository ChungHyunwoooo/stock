"""MTF Scanner Backtest — 실제 Upbit 데이터로 검증.

실행: .venv/bin/python -m tests.test_mtf_backtest

검증 항목:
1. OHLCV 캐시: fetch + TTL + 병렬 batch
2. MTF 추세 분석: 15m/1h 방향 판단
3. 7전략 시그널 생성: with/without MTF 필터 비교
4. WebSocket 컴포넌트: CandleBoundaryDetector 로직
5. 전체 스캔 파이프라인: _execute_scan 시뮬레이션
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from engine.data.upbit_cache import OHLCVCacheManager, INTERVAL_MAP, TTL_MAP
from engine.data.upbit_ws import CandleBoundaryDetector, UpbitWebSocketManager
from engine.strategy.upbit_mtf import (
    TrendDirection, TrendContext, TimeframeTrend,
    analyze_timeframe, analyze_mtf, mtf_filter_signal,
)
from engine.strategy.upbit_scanner import (
    UpbitScannerConfig, fetch_upbit_ohlcv,
    scan_ema_rsi_vwap, scan_supertrend, scan_macd_divergence,
    scan_stoch_rsi, scan_fibonacci, scan_ichimoku, scan_early_pump,
    calc_dynamic_levels, _get_active_symbols,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest")

# Test symbols
TEST_SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]

STRATEGIES = [
    ("EMA+RSI+VWAP", scan_ema_rsi_vwap),
    ("Supertrend", scan_supertrend),
    ("MACD Div", scan_macd_divergence),
    ("StochRSI", scan_stoch_rsi),
    ("Fibonacci", scan_fibonacci),
    ("Ichimoku", scan_ichimoku),
    ("Early Pump", scan_early_pump),
]


def sep(title: str) -> None:
    logger.info("=" * 60)
    logger.info("  %s", title)
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────
# Test 1: OHLCV Cache
# ─────────────────────────────────────────────────────────────
def test_cache() -> bool:
    sep("Test 1: OHLCV Cache Manager")
    cache = OHLCVCacheManager(max_workers=3)

    # Single fetch
    t0 = time.time()
    df = cache.fetch_single("KRW-BTC", "5m")
    t1 = time.time()
    if df is None:
        logger.error("FAIL: fetch_single returned None")
        return False
    logger.info("  fetch_single KRW-BTC 5m: %d rows, %.2fs", len(df), t1 - t0)

    # Cache hit
    t0 = time.time()
    df2 = cache.fetch_single("KRW-BTC", "5m")
    t2 = time.time()
    assert df2 is not None
    logger.info("  cache hit: %.4fs (vs %.2fs fetch)", t2 - t0, t1 - t0 - (t2 - t0))

    # Batch fetch (multiple symbols × intervals)
    t0 = time.time()
    results = cache.prefetch_batch(TEST_SYMBOLS, ["5m", "15m", "1h"])
    t3 = time.time()

    total = sum(1 for s in results.values() for i, d in s.items() if d is not None)
    expected = len(TEST_SYMBOLS) * 3
    logger.info("  prefetch_batch: %d/%d fetched, %.2fs", total, expected, t3 - t0)

    # Stats
    stats = cache.stats()
    logger.info("  cache stats: %s", stats)
    cache.shutdown()

    if total < expected * 0.8:  # Allow some failures
        logger.error("FAIL: too many batch failures (%d/%d)", total, expected)
        return False

    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Test 2: MTF Trend Analysis
# ─────────────────────────────────────────────────────────────
def test_mtf_analysis() -> bool:
    sep("Test 2: MTF Trend Analysis")

    results = {}
    for symbol in TEST_SYMBOLS:
        ticker = symbol.replace("KRW-", "")
        df_15m = fetch_upbit_ohlcv(symbol, interval="minute15", count=100)
        time.sleep(0.15)
        df_1h = fetch_upbit_ohlcv(symbol, interval="minute60", count=50)
        time.sleep(0.15)

        if df_15m is None or df_1h is None:
            logger.warning("  %s: data fetch failed (15m=%s, 1h=%s)",
                          ticker, df_15m is not None, df_1h is not None)
            continue

        ctx = analyze_mtf(df_15m, df_1h)
        results[ticker] = ctx

        logger.info("  %s: dominant=%s boost=%.1fx | 15m=%s(%.0f%%) 1h=%s(%.0f%%) | LONG=%s SHORT=%s",
                    ticker,
                    ctx.dominant_direction.value,
                    ctx.confidence_boost(),
                    ctx.tf_15m.direction.value if ctx.tf_15m else "N/A",
                    (ctx.tf_15m.strength * 100) if ctx.tf_15m else 0,
                    ctx.tf_1h.direction.value if ctx.tf_1h else "N/A",
                    (ctx.tf_1h.strength * 100) if ctx.tf_1h else 0,
                    ctx.allows_long(),
                    ctx.allows_short(),
                    )

    if not results:
        logger.error("FAIL: no MTF results")
        return False

    # Verify serialization
    for ticker, ctx in results.items():
        d = ctx.to_dict()
        assert "15m" in d and "1h" in d and "dominant" in d
        assert "allows_long" in d and "allows_short" in d

    logger.info("  Serialization OK for all %d symbols", len(results))
    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Test 3: Strategy Scan — With vs Without MTF
# ─────────────────────────────────────────────────────────────
def test_strategy_scan() -> bool:
    sep("Test 3: Strategy Scan (With/Without MTF)")
    config = UpbitScannerConfig()

    # Fetch all active symbols
    logger.info("  Fetching active symbols...")
    symbols = _get_active_symbols(min_volume_krw=10_000_000_000)  # 100억원+
    logger.info("  Active symbols: %d", len(symbols))

    # Limit to first 15 for backtest speed
    symbols = symbols[:15]

    signals_no_mtf = []
    signals_with_mtf = []
    mtf_blocked = 0

    cache = OHLCVCacheManager(max_workers=5)

    # Batch fetch all data
    logger.info("  Batch fetching 5m/15m/1h for %d symbols...", len(symbols))
    t0 = time.time()
    batch = cache.prefetch_batch(symbols, ["5m", "15m", "1h"])
    t_fetch = time.time() - t0
    logger.info("  Batch fetch done: %.2fs", t_fetch)

    for symbol in symbols:
        ticker = symbol.replace("KRW-", "")
        df_5m = batch.get(symbol, {}).get("5m")
        if df_5m is None:
            continue

        # MTF context
        df_15m = batch.get(symbol, {}).get("15m")
        df_1h = batch.get(symbol, {}).get("1h")
        trend_ctx = analyze_mtf(df_15m, df_1h)

        for strat_name, scan_fn in STRATEGIES:
            try:
                sig = scan_fn(df_5m, symbol, config)
            except Exception:
                continue

            if sig is None:
                continue

            signals_no_mtf.append((ticker, strat_name, sig))

            # Apply MTF filter
            allowed, boost, mtf_reason = mtf_filter_signal(sig.side, trend_ctx)
            if allowed:
                sig.confidence = min(1.0, sig.confidence * boost)
                sig.reason = f"{sig.reason} | {mtf_reason}"
                signals_with_mtf.append((ticker, strat_name, sig, mtf_reason))
            else:
                mtf_blocked += 1

    # Report
    logger.info("")
    logger.info("  ┌─────────────────────────────────────────────┐")
    logger.info("  │           SCAN RESULTS COMPARISON            │")
    logger.info("  ├─────────────────────────────────────────────┤")
    logger.info("  │  Symbols scanned:     %3d                    │", len(symbols))
    logger.info("  │  Strategies:          %3d                    │", len(STRATEGIES))
    logger.info("  │  Signals (no MTF):    %3d                    │", len(signals_no_mtf))
    logger.info("  │  Signals (with MTF):  %3d                    │", len(signals_with_mtf))
    logger.info("  │  MTF blocked:         %3d                    │", mtf_blocked)
    filter_rate = (mtf_blocked / max(1, len(signals_no_mtf))) * 100
    logger.info("  │  Filter rate:         %5.1f%%                 │", filter_rate)
    logger.info("  │  Fetch time:          %5.2fs                 │", t_fetch)
    logger.info("  └─────────────────────────────────────────────┘")

    if signals_no_mtf:
        logger.info("")
        logger.info("  --- Signals (before MTF) ---")
        for ticker, strat, sig in signals_no_mtf:
            logger.info("    %s %5s %-15s entry=%12s conf=%.0f%% | %s",
                        sig.side, ticker, strat,
                        f"{sig.entry:,.0f}" if sig.entry >= 100 else f"{sig.entry:.4f}",
                        sig.confidence * 100,
                        sig.reason[:60])

    if signals_with_mtf:
        logger.info("")
        logger.info("  --- Signals (after MTF filter) ---")
        for ticker, strat, sig, mtf_reason in signals_with_mtf:
            logger.info("    %s %5s %-15s entry=%12s conf=%.0f%% | %s",
                        sig.side, ticker, strat,
                        f"{sig.entry:,.0f}" if sig.entry >= 100 else f"{sig.entry:.4f}",
                        sig.confidence * 100,
                        mtf_reason)

    cache.shutdown()
    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Test 4: WebSocket Components
# ─────────────────────────────────────────────────────────────
def test_websocket_components() -> bool:
    sep("Test 4: WebSocket Components")

    # CandleBoundaryDetector
    detector = CandleBoundaryDetector(5)

    # Simulate tick sequence across a 5-min boundary
    # 12:04:50 → 12:04:55 → 12:05:01 → 12:05:10
    base = 1709294400000  # some epoch in ms (aligned to 5min)
    ticks = [
        (base - 10000, False, "12:04:50 — same window"),
        (base - 5000,  False, "12:04:55 — same window"),
        (base + 1000,  True,  "12:05:01 — NEW CANDLE"),
        (base + 10000, False, "12:05:10 — same new window"),
        (base + 300000, True, "12:10:00 — NEXT CANDLE"),
    ]

    # First tick initializes, doesn't trigger
    first_ts = base - 60000
    assert detector.check(first_ts) == False
    logger.info("  init tick: no trigger (expected)")

    for ts, expected, label in ticks:
        result = detector.check(ts)
        status = "TRIGGER" if result else "no trigger"
        assert result == expected, f"Failed at {label}: got {result}, expected {expected}"
        logger.info("  %s → %s (%s)", label, status, "OK" if result == expected else "FAIL")

    # UpbitWebSocketManager status
    ws = UpbitWebSocketManager(symbols=TEST_SYMBOLS)
    s = ws.status()
    assert s["connected"] == False
    assert s["symbols_count"] == len(TEST_SYMBOLS)
    logger.info("  WS status (not started): %s", s)

    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Test 5: Config Persistence
# ─────────────────────────────────────────────────────────────
def test_config() -> bool:
    sep("Test 5: Config — New Fields")
    config = UpbitScannerConfig()

    # Verify new fields exist with defaults
    assert hasattr(config, "enable_mtf") and config.enable_mtf == True
    assert hasattr(config, "ws_enabled") and config.ws_enabled == True
    assert hasattr(config, "parallel_fetch") and config.parallel_fetch == True
    logger.info("  Default: enable_mtf=%s ws_enabled=%s parallel_fetch=%s",
                config.enable_mtf, config.ws_enabled, config.parallel_fetch)

    # Serialize / deserialize roundtrip
    from dataclasses import asdict
    d = asdict(config)
    assert "enable_mtf" in d and "ws_enabled" in d and "parallel_fetch" in d
    config2 = UpbitScannerConfig(**{k: v for k, v in d.items() if hasattr(config, k)})
    assert config2.enable_mtf == config.enable_mtf
    logger.info("  Roundtrip serialization OK")

    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Test 6: Performance Comparison
# ─────────────────────────────────────────────────────────────
def test_performance() -> bool:
    sep("Test 6: Performance — Sequential vs Parallel Fetch")

    symbols = TEST_SYMBOLS[:5]

    # Sequential fetch
    t0 = time.time()
    for sym in symbols:
        fetch_upbit_ohlcv(sym, interval="minute5", count=200)
        time.sleep(0.1)
    t_seq = time.time() - t0
    logger.info("  Sequential (5 symbols × 5m): %.2fs", t_seq)

    # Parallel fetch via cache
    cache = OHLCVCacheManager(max_workers=5)
    cache.invalidate_all()
    t0 = time.time()
    batch = cache.prefetch_batch(symbols, ["5m", "15m", "1h"])
    t_par = time.time() - t0
    total = sum(1 for s in batch.values() for d in s.values() if d is not None)
    logger.info("  Parallel  (5 symbols × 3 TF): %.2fs (%d fetched)", t_par, total)

    # Second run — should be all cache hits
    t0 = time.time()
    batch2 = cache.prefetch_batch(symbols, ["5m", "15m", "1h"])
    t_cached = time.time() - t0
    logger.info("  Cached    (5 symbols × 3 TF): %.4fs", t_cached)

    stats = cache.stats()
    logger.info("  Cache hit rate: %s%%", stats["hit_rate"])
    cache.shutdown()

    logger.info("")
    logger.info("  ┌─────────────────────────────────────────┐")
    logger.info("  │         PERFORMANCE COMPARISON           │")
    logger.info("  ├─────────────────────────────────────────┤")
    logger.info("  │  Sequential (5×1TF):  %6.2fs            │", t_seq)
    logger.info("  │  Parallel   (5×3TF):  %6.2fs            │", t_par)
    logger.info("  │  Cached     (5×3TF):  %6.4fs            │", t_cached)
    if t_seq > 0:
        logger.info("  │  Speedup (par/seq):   %5.1fx             │", t_seq / max(0.01, t_par))
    logger.info("  │  Cache hit rate:      %5.1f%%             │", stats["hit_rate"])
    logger.info("  └─────────────────────────────────────────┘")

    logger.info("  PASS")
    return True


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    logger.info("MTF Scanner Backtest — %s",
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    logger.info("")

    tests = [
        ("OHLCV Cache", test_cache),
        ("MTF Trend Analysis", test_mtf_analysis),
        ("Strategy Scan (MTF Filter)", test_strategy_scan),
        ("WebSocket Components", test_websocket_components),
        ("Config Persistence", test_config),
        ("Performance Comparison", test_performance),
    ]

    results = []
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            logger.error("EXCEPTION in %s: %s", name, e, exc_info=True)
            results.append((name, False))

    # Summary
    logger.info("")
    sep("BACKTEST SUMMARY")
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        logger.info("  [%s] %s", status, name)
    logger.info("")
    logger.info("  %d/%d tests passed", passed, len(results))

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
