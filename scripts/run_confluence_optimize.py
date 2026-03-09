"""수익률 개선 탐색 — 1회 백테스트 후 필터 조합 비교."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest

FEE = 0.0004
CAPITAL = 100_000
TRADE_SIZE = 10_000


def calc(trades, label, leverage=3, direction_filter=False):
    equity = CAPITAL
    peak = CAPITAL
    max_dd = 0
    wins = 0
    filtered = []

    for t in trades:
        if direction_filter:
            r, s = t.market_regime, t.side
            if (r == "BULL" and s == "SHORT") or (r == "BEAR" and s == "LONG"):
                continue
        filtered.append(t)
        pnl_won = TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3)  # 기존 3x 대비 스케일
        equity += pnl_won
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
        if t.pnl_pct > 0:
            wins += 1

    n = len(filtered)
    if n == 0:
        print(f"  {label}: 0건")
        return
    wr = round(wins / n * 100, 1)
    total_pnl = equity - CAPITAL
    avg = round(total_pnl / n)
    print(f"  {label}: {n}건 WR {wr}% | {total_pnl:+,.0f}원 ({total_pnl/CAPITAL*100:+.1f}%) "
          f"| 거래당 {avg:+,}원 | MDD {max_dd:.1f}%")


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

    # 1회만 백테스트 실행 (SL2.5_TP2.0)
    print("데이터 로딩 중...")
    all_trades = []
    for sym in symbols:
        try:
            result = run_confluence_backtest(
                symbol=sym, start="2024-06-01", end="2025-03-01",
                entry_tf="4h", leverage=3, risk_pct=0.01,
                min_score=2, atr_sl_mult=2.5, tp_ratios=[2.0],
                max_hold_bars=30, fee_rate=FEE, use_real_funding=True,
            )
            all_trades.extend(result.trades)
            print(f"  {sym}: {len(result.trades)}건 로드")
        except Exception as e:
            print(f"  {sym}: SKIP - {e}")

    print(f"\n총 {len(all_trades)}건 로드 완료")
    print("=" * 70)

    # 필터/레버리지 조합을 trades에서 재계산 (API 호출 없음)
    print("\n[1] 기본 3x")
    calc(all_trades, "기본 3x", leverage=3, direction_filter=False)

    print("\n[2] 방향 필터 + 3x")
    calc(all_trades, "방향필터 3x", leverage=3, direction_filter=True)

    print("\n[3] 기본 5x")
    calc(all_trades, "기본 5x", leverage=5, direction_filter=False)

    print("\n[4] 방향 필터 + 5x")
    calc(all_trades, "방향필터 5x", leverage=5, direction_filter=True)

    print("\n[5] 기본 10x")
    calc(all_trades, "기본 10x", leverage=10, direction_filter=False)

    print("\n[6] 방향 필터 + 10x")
    calc(all_trades, "방향필터 10x", leverage=10, direction_filter=True)

    # RANGE-SHORT만 강화
    print("\n[7] RANGE-SHORT + BULL-LONG만 (가장 엄격)")
    equity = CAPITAL; peak = CAPITAL; max_dd = 0; wins = 0; filtered = []
    for t in all_trades:
        r, s = t.market_regime, t.side
        if (r == "RANGE" and s == "SHORT") or (r == "BULL" and s == "LONG"):
            filtered.append(t)
    calc_list = filtered
    n = len(calc_list)
    if n:
        eq = CAPITAL
        pk = CAPITAL
        md = 0
        w = 0
        for t in calc_list:
            pnl = TRADE_SIZE * (t.pnl_pct / 100) * (5/3)
            eq += pnl
            if eq > pk: pk = eq
            dd = (pk - eq) / pk * 100
            if dd > md: md = dd
            if t.pnl_pct > 0: w += 1
        wr = round(w/n*100, 1)
        tp = eq - CAPITAL
        print(f"  엄격필터 5x: {n}건 WR {wr}% | {tp:+,.0f}원 ({tp/CAPITAL*100:+.1f}%) "
              f"| 거래당 {round(tp/n):+,}원 | MDD {md:.1f}%")


if __name__ == "__main__":
    main()
