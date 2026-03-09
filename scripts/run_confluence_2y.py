"""2년 백테스트 — 2023-03-01 ~ 2025-03-01, 고정금액."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest

FEE = 0.0004
CAPITAL = 100_000
TRADE_SIZE = 10_000


def calc(trades, label, leverage=3):
    equity = CAPITAL
    peak = CAPITAL
    max_dd = 0
    wins = 0

    monthly_pnl = {}  # "YYYY-MM" -> pnl
    for t in trades:
        pnl_won = TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3)
        equity += pnl_won
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
        if t.pnl_pct > 0:
            wins += 1
        # 월별 집계
        month = t.exit_date[:7]
        monthly_pnl[month] = monthly_pnl.get(month, 0) + pnl_won

    n = len(trades)
    if n == 0:
        print(f"  {label}: 0건")
        return
    wr = round(wins / n * 100, 1)
    total_pnl = equity - CAPITAL
    avg = round(total_pnl / n)
    win_pnls = [TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3) for t in trades if t.pnl_pct > 0]
    loss_pnls = [TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3) for t in trades if t.pnl_pct <= 0]
    avg_w = round(sum(win_pnls) / len(win_pnls)) if win_pnls else 0
    avg_l = round(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0

    print(f"  {label}: {n}건 WR {wr}%")
    print(f"    총손익: {total_pnl:+,.0f}원 ({total_pnl/CAPITAL*100:+.1f}%) | 거래당 {avg:+,}원")
    print(f"    평균승 {avg_w:+,}원 / 평균패 {avg_l:,}원 | MDD {max_dd:.1f}%")

    # 레짐별
    regimes = {}
    for t in trades:
        r = t.market_regime
        regimes.setdefault(r, []).append(t)
    print(f"    레짐: ", end="")
    for r in ["BULL", "BEAR", "RANGE"]:
        rt = regimes.get(r, [])
        if rt:
            rw = sum(1 for t in rt if t.pnl_pct > 0)
            print(f"{r} {len(rt)}건 WR{round(rw/len(rt)*100)}%  ", end="")
    print()

    # 월별 손익
    print(f"    월별: ", end="")
    profit_months = sum(1 for v in monthly_pnl.values() if v > 0)
    loss_months = sum(1 for v in monthly_pnl.values() if v <= 0)
    print(f"흑자 {profit_months}개월 / 적자 {loss_months}개월")

    # 연도별
    yearly = {}
    for m, p in monthly_pnl.items():
        y = m[:4]
        yearly[y] = yearly.get(y, 0) + p
    for y in sorted(yearly):
        print(f"      {y}: {yearly[y]:+,.0f}원")


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

    print("=" * 70)
    print("2년 백테스트 (2023-03 ~ 2025-03)")
    print("SL2.5_TP2.0 | 고정 1만원 | 수수료 0.04%")
    print("=" * 70)

    all_trades = []
    for sym in symbols:
        try:
            result = run_confluence_backtest(
                symbol=sym, start="2023-03-01", end="2025-03-01",
                entry_tf="4h", leverage=3, risk_pct=0.01,
                min_score=2, atr_sl_mult=2.5, tp_ratios=[2.0],
                max_hold_bars=30, fee_rate=FEE, use_real_funding=True,
            )
            all_trades.extend(result.trades)
            print(f"  {sym}: {len(result.trades)}건")
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")

    print(f"\n총 {len(all_trades)}건")

    # 시간순 정렬
    all_trades.sort(key=lambda t: t.entry_date)

    print(f"\n--- 3x 레버리지 ---")
    calc(all_trades, "3x", leverage=3)

    print(f"\n--- 5x 레버리지 ---")
    calc(all_trades, "5x", leverage=5)

    # LONG/SHORT 분석
    print(f"\n--- 방향별 ---")
    longs = [t for t in all_trades if t.side == "LONG"]
    shorts = [t for t in all_trades if t.side == "SHORT"]
    calc(longs, "LONG 3x", leverage=3)
    calc(shorts, "SHORT 3x", leverage=3)


if __name__ == "__main__":
    main()
