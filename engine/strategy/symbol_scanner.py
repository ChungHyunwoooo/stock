"""종목 스캐너 — 전 종목 walk-forward 검증 + 유효 목록 갱신.

주기적으로 실행하여 알트_데일리_봇의 종목 리스트를 최신화.

사용:
    .venv/bin/python -m engine.strategy.symbol_scanner
    → data/validated_symbols.json 갱신
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from engine.data.provider_crypto import CryptoProvider, _build_futures_exchange

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "data" / "validated_symbols.json"


def scan_all_symbols(
    min_annual_return: float = 10.0,
    pump_threshold: float = 2.0,
    vol_multiplier: float = 2.0,
    tp_pct: float = 5.0,
    sl_pct: float = 3.0,
    max_hold: int = 3,
    min_trades: int = 10,
    lookback_months: int = 18,
) -> dict:
    """전 종목 스캔 + walk-forward 검증.

    Returns:
        {
            "validated": [심볼 리스트],
            "details": {심볼: {건수, 승률, 연수익, ...}},
            "scanned_at": ISO timestamp,
            "total_scanned": int,
            "params": {...},
        }
    """
    provider = CryptoProvider("binance")
    ex = _build_futures_exchange("binance")
    markets = ex.load_markets()

    perps = sorted([
        s for s, m in markets.items()
        if m.get("swap") and m.get("quote") == "USDT" and m.get("active")
        and "BTC" not in s
    ])
    logger.info("스캔 대상: %d개", len(perps))

    end_date = pd.Timestamp.now(tz="UTC")
    start_date = end_date - pd.DateOffset(months=lookback_months)

    results = {}
    scanned = 0

    for fsym in perps:
        sym = fsym.replace(":USDT", "")
        try:
            df = provider.fetch_ohlcv(sym, str(start_date), str(end_date), "1h")
            c = df["close"].values.astype(float)
            h = df["high"].values.astype(float)
            l = df["low"].values.astype(float)
            v = df["volume"].values.astype(float)
            n = len(c)
            if n < 500:
                continue

            ret_1h = np.zeros(n)
            ret_1h[1:] = (c[1:] - c[:-1]) / c[:-1] * 100
            vol_ma = np.full(n, np.nan)
            for i in range(20, n):
                vol_ma[i] = np.mean(v[i - 20:i])

            mid = n // 2

            def run_period(start_idx, end_idx):
                trades = []
                position = None
                for i in range(max(20, start_idx), min(end_idx, n)):
                    if position is not None:
                        eidx, ep, bars = position
                        bars += 1
                        exited = False
                        if h[i] >= ep * (1 + tp_pct / 100):
                            trades.append(tp_pct); exited = True
                        elif l[i] <= ep * (1 - sl_pct / 100):
                            trades.append(-sl_pct); exited = True
                        elif bars >= max_hold:
                            trades.append((c[i] - ep) / ep * 100); exited = True
                        if exited:
                            position = None
                        else:
                            position = (eidx, ep, bars)
                        continue
                    if (ret_1h[i] > pump_threshold
                            and not np.isnan(vol_ma[i])
                            and vol_ma[i] > 0
                            and v[i] > vol_ma[i] * vol_multiplier):
                        position = (i, c[i], 0)
                return trades

            train = run_period(0, mid)
            test = run_period(mid, n)

            if len(train) < min_trades or len(test) < min_trades:
                continue

            cost = 0.08
            train_net = np.mean(train) - cost
            test_net = np.mean(test) - cost
            months_test = (n - mid) / (24 * 30)
            test_annual = (np.sum(test) - len(test) * cost) / (months_test / 12) if months_test > 0 else 0
            test_wr = np.mean(np.array(test) > 0) * 100

            if train_net > 0 and test_net > 0 and test_annual >= min_annual_return:
                results[sym] = {
                    "train_n": len(train),
                    "test_n": len(test),
                    "train_net": round(train_net, 4),
                    "test_net": round(test_net, 4),
                    "test_annual": round(test_annual, 1),
                    "test_wr": round(test_wr, 1),
                }

            scanned += 1
            if scanned % 50 == 0:
                logger.info("스캔 진행: %d/%d, 유효: %d", scanned, len(perps), len(results))

        except Exception as e:
            logger.debug("스캔 실패 %s: %s", sym, e)

    # 연수익 기준 정렬
    validated = sorted(results.keys(), key=lambda s: results[s]["test_annual"], reverse=True)

    output = {
        "validated": validated,
        "details": results,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": scanned,
        "total_validated": len(validated),
        "params": {
            "min_annual_return": min_annual_return,
            "pump_threshold": pump_threshold,
            "vol_multiplier": vol_multiplier,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "max_hold": max_hold,
            "lookback_months": lookback_months,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    logger.info("스캔 완료: %d/%d 유효 → %s", len(validated), scanned, OUTPUT_PATH)

    return output


def load_validated_symbols() -> list[str]:
    """저장된 유효 심볼 목록 로드. 없으면 하드코딩된 기본값."""
    if OUTPUT_PATH.exists():
        try:
            data = json.loads(OUTPUT_PATH.read_text())
            syms = data.get("validated", [])
            if syms:
                return syms
        except Exception:
            pass
    # fallback: 하드코딩 기본값
    from engine.strategy.alt_momentum import VALIDATED_SYMBOLS
    return VALIDATED_SYMBOLS


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = scan_all_symbols()
    print(f"\n=== 결과 ===")
    print(f"스캔: {result['total_scanned']}개")
    print(f"유효: {result['total_validated']}개")
    print(f"저장: {OUTPUT_PATH}")
    print(f"\n상위 10:")
    for sym in result["validated"][:10]:
        d = result["details"][sym]
        print(f"  {sym:>16} | test {d['test_n']}건 승률{d['test_wr']}% 연{d['test_annual']:+.0f}%")
