"""고정 금액 백테스트 — 10만원 자본, 1만원 고정 거래금액."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest

FEE = 0.0004  # taker 0.04%
CAPITAL = 100_000  # 10만원
TRADE_SIZE = 10_000  # 1만원 고정
LEVERAGE = 3


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    configs = [
        {"atr_sl_mult": 1.5, "tp_ratios": [1.0, 1.5, 2.5], "label": "SL1.5_3TP"},
        {"atr_sl_mult": 2.0, "tp_ratios": [1.5], "label": "SL2.0_TP1.5"},
        {"atr_sl_mult": 2.5, "tp_ratios": [2.0], "label": "SL2.5_TP2.0"},
    ]

    for cfg in configs:
        label = cfg["label"]
        print(f"\n{'='*60}")
        print(f"CONFIG: {label} | 자본 {CAPITAL:,}원 | 거래금액 {TRADE_SIZE:,}원 고정 | {LEVERAGE}x")
        print(f"{'='*60}")

        total_pnl = 0
        total_trades = 0
        total_wins = 0
        peak = CAPITAL
        max_dd = 0
        equity = CAPITAL
        all_pnls = []

        for sym in symbols:
            try:
                result = run_confluence_backtest(
                    symbol=sym, start="2024-06-01", end="2025-03-01",
                    entry_tf="4h", leverage=LEVERAGE, risk_pct=0.01,
                    min_score=2, atr_sl_mult=cfg["atr_sl_mult"],
                    tp_ratios=cfg["tp_ratios"], max_hold_bars=30,
                    fee_rate=FEE, use_real_funding=True,
                )

                sym_pnl = 0
                sym_wins = 0
                for t in result.trades:
                    # pnl_pct는 레버리지 반영된 수익률 (%)
                    # 고정 거래금액 기준 실현손익
                    pnl_won = TRADE_SIZE * (t.pnl_pct / 100)
                    sym_pnl += pnl_won
                    equity += pnl_won
                    all_pnls.append(pnl_won)

                    if equity > peak:
                        peak = equity
                    dd = (peak - equity) / peak * 100
                    if dd > max_dd:
                        max_dd = dd

                    if t.pnl_pct > 0:
                        sym_wins += 1

                n = len(result.trades)
                wr = round(sym_wins / n * 100, 1) if n > 0 else 0
                print(f"  {sym}: {n}건 WR {wr}% | 손익 {sym_pnl:+,.0f}원")
                total_pnl += sym_pnl
                total_trades += n
                total_wins += sym_wins

            except Exception as e:
                print(f"  {sym}: ERROR - {e}")

        if total_trades > 0:
            wr = round(total_wins / total_trades * 100, 1)
            avg_pnl = round(total_pnl / total_trades)
            print(f"\n  합산: {total_trades}건 WR {wr}%")
            print(f"  총 손익: {total_pnl:+,.0f}원 (수익률 {total_pnl/CAPITAL*100:+.1f}%)")
            print(f"  거래당 평균: {avg_pnl:+,}원")
            print(f"  최종 자본: {CAPITAL + total_pnl:,.0f}원")
            print(f"  MDD: {max_dd:.1f}%")
            if all_pnls:
                win_pnls = [p for p in all_pnls if p > 0]
                loss_pnls = [p for p in all_pnls if p <= 0]
                print(f"  평균 승: +{sum(win_pnls)/len(win_pnls):,.0f}원" if win_pnls else "")
                print(f"  평균 패: {sum(loss_pnls)/len(loss_pnls):,.0f}원" if loss_pnls else "")


if __name__ == "__main__":
    main()
