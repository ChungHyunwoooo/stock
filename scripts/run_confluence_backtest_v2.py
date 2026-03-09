"""Confluence 백테스트 v2 — 수수료 반영 + 상승/하락장 구분 + 심볼별 분석."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest


def analyze_trades(trades, label=""):
    if not trades:
        print(f"  {label}: 0건")
        return
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    wr = round(wins / len(trades) * 100, 1)
    avg_pnl = round(sum(t.pnl_pct for t in trades) / len(trades), 2)
    win_pnls = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    loss_pnls = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    avg_win = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0
    gross_w = sum(win_pnls) if win_pnls else 0
    gross_l = abs(sum(loss_pnls)) if loss_pnls else 0
    pf = round(gross_w / gross_l, 2) if gross_l > 0 else float("inf")
    print(f"  {label}: {len(trades)}건 WR {wr}% 평균PnL {avg_pnl}% PF {pf}")
    print(f"    평균승 +{avg_win}% / 평균패 {avg_loss}%")


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    # Binance Futures taker fee: 0.04% (VIP0)
    FEE_RATE = 0.0004

    print("=" * 70)
    print("BACKTEST v2: 수수료 반영 (0.04% taker) + 상승/하락장 분석")
    print("설정: SL1.5ATR, 3TP(1.0/1.5/2.5R), 레버리지3x, min_score=2")
    print("=" * 70)

    all_trades = []
    trades_by_symbol = {}

    for sym in symbols:
        try:
            result = run_confluence_backtest(
                symbol=sym,
                start="2024-06-01",
                end="2025-03-01",
                entry_tf="4h",
                leverage=3,
                risk_pct=0.01,
                min_score=2,
                atr_sl_mult=1.5,
                tp_ratios=[1.0, 1.5, 2.5],
                max_hold_bars=30,
                fee_rate=FEE_RATE,
                use_real_funding=True,
            )
            trades_by_symbol[sym] = result.trades
            all_trades.extend(result.trades)
            print(f"\n{sym}: {result.total_trades}건, WR {result.win_rate}%, "
                  f"수익 {result.total_return_pct}%, MDD {result.max_drawdown_pct}%")
        except Exception as e:
            print(f"\n{sym}: ERROR - {e}")

    if not all_trades:
        print("거래 없음")
        return

    # --- 전체 합산 ---
    print(f"\n{'='*70}")
    print("전체 합산 (수수료 포함)")
    analyze_trades(all_trades, "ALL")

    # --- 심볼별 ---
    print(f"\n--- 심볼별 ---")
    for sym, trades in trades_by_symbol.items():
        analyze_trades(trades, sym)

    # --- 상승/하락/횡보장별 ---
    print(f"\n--- 시장 레짐별 (D1 트렌드 기준) ---")
    regime_trades = {}
    for t in all_trades:
        r = t.market_regime
        regime_trades.setdefault(r, []).append(t)
    for regime in ["BULL", "BEAR", "RANGE"]:
        analyze_trades(regime_trades.get(regime, []), f"{regime}장")

    # --- 상승/하락장 × LONG/SHORT ---
    print(f"\n--- 레짐 × 방향 ---")
    for regime in ["BULL", "BEAR", "RANGE"]:
        for side in ["LONG", "SHORT"]:
            subset = [t for t in all_trades if t.market_regime == regime and t.side == side]
            if subset:
                analyze_trades(subset, f"{regime}-{side}")

    # --- SOL 제외 ---
    print(f"\n--- SOL 제외 ---")
    no_sol = [t for t in all_trades if "SOL" not in getattr(t, 'entry_date', '')]
    # symbol 정보가 trade에 없으므로 trades_by_symbol에서 필터
    no_sol = []
    for sym, trades in trades_by_symbol.items():
        if sym != "SOL/USDT":
            no_sol.extend(trades)
    analyze_trades(no_sol, "SOL제외")

    # --- ETH+XRP만 ---
    print(f"\n--- ETH+XRP ---")
    best = []
    for sym in ["ETH/USDT", "XRP/USDT"]:
        best.extend(trades_by_symbol.get(sym, []))
    analyze_trades(best, "ETH+XRP")

    # --- Score별 × 레짐별 ---
    print(f"\n--- Score별 ---")
    for score in [2, 3]:
        subset = [t for t in all_trades if t.confluence_score == score]
        analyze_trades(subset, f"Score={score}")

    # --- 수수료 영향 비교 ---
    print(f"\n--- 수수료 영향 (거래당) ---")
    fee_per_trade = FEE_RATE * 2 * 3 * 100  # fee × 2(왕복) × leverage × 100(%)
    print(f"  거래당 수수료: {fee_per_trade:.2f}% (0.04% × 2 × 3x leverage)")
    avg_pnl = sum(t.pnl_pct for t in all_trades) / len(all_trades)
    print(f"  수수료 후 평균PnL: {avg_pnl:.2f}%")
    print(f"  수수료 전 평균PnL (추정): {avg_pnl + fee_per_trade:.2f}%")


if __name__ == "__main__":
    main()
