"""Confluence 백테스트 실행 스크립트 — 실제 펀딩비 데이터 사용."""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    configs = [
        {"atr_sl_mult": 2.5, "tp_ratios": [2.0], "label": "SL2.5_TP2.0"},
        {"atr_sl_mult": 2.0, "tp_ratios": [1.5], "label": "SL2.0_TP1.5"},
        {"atr_sl_mult": 1.5, "tp_ratios": [1.0, 1.5, 2.5], "label": "SL1.5_3TP"},
    ]

    for cfg in configs:
        label = cfg["label"]
        print(f"\n{'='*60}")
        print(f"CONFIG: {label}")
        print(f"{'='*60}")

        all_trades = 0
        all_wins = 0
        all_pnl = []
        funding_hits = 0
        funding_total = 0

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
                    atr_sl_mult=cfg["atr_sl_mult"],
                    tp_ratios=cfg["tp_ratios"],
                    max_hold_bars=30,
                    use_real_funding=True,
                )

                print(f"\n--- {sym} ---")
                print(f"  거래: {result.total_trades}건 | WR: {result.win_rate}%")
                print(f"  평균승: +{result.avg_win_pct}% | 평균패: {result.avg_loss_pct}%")
                print(f"  PF: {result.profit_factor} | 수익: {result.total_return_pct}%")
                print(f"  MDD: {result.max_drawdown_pct}% | Sharpe: {result.sharpe_ratio}")
                print(f"  점수분포: {result.score_distribution}")
                print(f"  평균점수: {result.avg_confluence_score}")

                # 펀딩비 엣지 분석
                for t in result.trades:
                    funding_total += 1
                    if t.funding_point:
                        funding_hits += 1

                all_trades += result.total_trades
                all_wins += result.wins
                all_pnl.extend([t.pnl_pct for t in result.trades])

            except Exception as e:
                print(f"\n--- {sym} --- ERROR: {e}")

        if all_trades > 0:
            total_wr = round(all_wins / all_trades * 100, 1)
            avg_pnl = round(sum(all_pnl) / len(all_pnl), 2) if all_pnl else 0
            funding_rate_pct = round(funding_hits / funding_total * 100, 1) if funding_total > 0 else 0
            print(f"\n{'='*60}")
            print(f"[{label}] 전체 합산")
            print(f"  총 거래: {all_trades}건 | WR: {total_wr}%")
            print(f"  평균 PnL: {avg_pnl}%/거래")
            print(f"  펀딩비 히트: {funding_hits}/{funding_total} ({funding_rate_pct}%)")
            print(f"{'='*60}")


if __name__ == "__main__":
    main()
