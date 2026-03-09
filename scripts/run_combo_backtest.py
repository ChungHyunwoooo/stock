"""Combo A 백테스트 — BB Squeeze + BB Bounce + EMA Stack 3개 전략 병렬 실행.

5개 심볼, 2년 기간, 고정금액(10만원 자본 / 1만원 거래), 3x vs 5x 비교.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.strategy_base import StrategyTrade

FEE = 0.0004
CAPITAL = 100_000
TRADE_SIZE = 10_000


def calc_fixed_size(trades: list[StrategyTrade], label: str, leverage: int = 3) -> dict:
    """고정 금액 기준 손익 계산."""
    equity = CAPITAL
    peak = CAPITAL
    max_dd = 0.0
    wins = 0
    monthly_pnl: dict[str, float] = {}

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
        month = t.exit_date[:7]
        monthly_pnl[month] = monthly_pnl.get(month, 0) + pnl_won

    n = len(trades)
    if n == 0:
        print(f"  {label}: 0건")
        return {"total_pnl": 0, "trades": 0, "wr": 0, "max_dd": 0}

    wr = round(wins / n * 100, 1)
    total_pnl = equity - CAPITAL
    avg = round(total_pnl / n)
    win_pnls = [TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3) for t in trades if t.pnl_pct > 0]
    loss_pnls = [TRADE_SIZE * (t.pnl_pct / 100) * (leverage / 3) for t in trades if t.pnl_pct <= 0]
    avg_w = round(sum(win_pnls) / len(win_pnls)) if win_pnls else 0
    avg_l = round(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0

    print(f"  {label}: {n}건 WR {wr}%")
    print(f"    총손익: {total_pnl:+,.0f}원 ({total_pnl / CAPITAL * 100:+.1f}%) | 거래당 {avg:+,}원")
    print(f"    평균승 {avg_w:+,}원 / 평균패 {avg_l:,}원 | MDD {max_dd:.1f}%")

    # 레짐별
    regimes: dict[str, list[StrategyTrade]] = {}
    for t in trades:
        regimes.setdefault(t.market_regime, []).append(t)
    print("    레짐: ", end="")
    for r in ["BULL", "BEAR", "RANGE"]:
        rt = regimes.get(r, [])
        if rt:
            rw = sum(1 for t in rt if t.pnl_pct > 0)
            print(f"{r} {len(rt)}건 WR{round(rw / len(rt) * 100)}%  ", end="")
    print()

    # 월별
    profit_months = sum(1 for v in monthly_pnl.values() if v > 0)
    loss_months = sum(1 for v in monthly_pnl.values() if v <= 0)
    print(f"    월별: 흑자 {profit_months}개월 / 적자 {loss_months}개월")

    # 연도별
    yearly: dict[str, float] = {}
    for m, p in monthly_pnl.items():
        y = m[:4]
        yearly[y] = yearly.get(y, 0) + p
    for y in sorted(yearly):
        print(f"      {y}: {yearly[y]:+,.0f}원")

    return {"total_pnl": total_pnl, "trades": n, "wr": wr, "max_dd": max_dd}


def main():
    from engine.backtest.bb_squeeze_backtest import run_bb_squeeze_backtest
    from engine.backtest.bb_bounce_backtest import run_bb_bounce_backtest
    from engine.backtest.ema_stack_backtest import run_ema_stack_backtest

    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    start = "2023-03-01"
    end = "2025-03-01"

    strategies = [
        ("BB_SQUEEZE", run_bb_squeeze_backtest),
        ("BB_BOUNCE", run_bb_bounce_backtest),
        ("EMA_STACK", run_ema_stack_backtest),
    ]

    print("=" * 70)
    print("Combo A 백테스트 (BB Squeeze + BB Bounce + EMA Stack)")
    print(f"기간: {start} ~ {end} | 자본 {CAPITAL:,}원 | 거래금액 {TRADE_SIZE:,}원 고정")
    print(f"수수료: {FEE * 100:.2f}% (taker)")
    print("=" * 70)

    all_trades: list[StrategyTrade] = []
    strategy_trades: dict[str, list[StrategyTrade]] = {}

    for strat_name, run_fn in strategies:
        strat_trades: list[StrategyTrade] = []
        print(f"\n--- {strat_name} ---")
        for idx, sym in enumerate(symbols):
            t0 = time.time()
            print(f"  [{idx+1}/{len(symbols)}] {sym}...", end=" ", flush=True)
            try:
                result = run_fn(
                    symbol=sym, start=start, end=end,
                    timeframe="1h", leverage=3, fee_rate=FEE,
                )
                n = len(result.trades)
                w = result.wins
                wr = round(w / n * 100, 1) if n > 0 else 0
                print(f"{n}건 WR {wr}% ({time.time()-t0:.1f}초)")
                strat_trades.extend(result.trades)
            except Exception as e:
                print(f"ERROR - {e}")
                import traceback
                traceback.print_exc()

        strategy_trades[strat_name] = strat_trades
        all_trades.extend(strat_trades)

    if not all_trades:
        print("\n거래 없음. 종료.")
        return

    # 시간순 정렬
    all_trades.sort(key=lambda t: t.entry_date)

    # === 전략별 결과 ===
    print(f"\n{'=' * 70}")
    print("전략별 결과 (3x)")
    print(f"{'=' * 70}")
    for strat_name in ["BB_SQUEEZE", "BB_BOUNCE", "EMA_STACK"]:
        st = strategy_trades.get(strat_name, [])
        if st:
            st.sort(key=lambda t: t.entry_date)
            print()
            calc_fixed_size(st, f"{strat_name} 3x", leverage=3)

    # === 합산 결과 ===
    print(f"\n{'=' * 70}")
    print(f"합산 {len(all_trades)}건")
    print(f"{'=' * 70}")

    print(f"\n--- 3x 레버리지 ---")
    calc_fixed_size(all_trades, "전체 3x", leverage=3)

    print(f"\n--- 5x 레버리지 ---")
    calc_fixed_size(all_trades, "전체 5x", leverage=5)

    # === LONG/SHORT 분석 ===
    longs = [t for t in all_trades if t.side == "LONG"]
    shorts = [t for t in all_trades if t.side == "SHORT"]
    print(f"\n--- 방향별 (3x) ---")
    calc_fixed_size(longs, "LONG 3x", leverage=3)
    calc_fixed_size(shorts, "SHORT 3x", leverage=3)

    # === 레짐별 분석 ===
    print(f"\n--- 레짐별 (3x) ---")
    for regime in ["BULL", "BEAR", "RANGE"]:
        regime_trades = [t for t in all_trades if t.market_regime == regime]
        if regime_trades:
            calc_fixed_size(regime_trades, f"{regime} 3x", leverage=3)

    # === 청산 사유 분포 ===
    print(f"\n--- 청산 사유 분포 ---")
    reasons: dict[str, int] = {}
    for t in all_trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    for reason in ["TP", "SL", "TIME", "END"]:
        cnt = reasons.get(reason, 0)
        pct = round(cnt / len(all_trades) * 100, 1) if all_trades else 0
        print(f"  {reason}: {cnt}건 ({pct}%)")

    # === 전략별 × 레짐 교차 분석 ===
    print(f"\n--- 전략 × 레짐 교차 (3x) ---")
    for strat_name in ["BB_SQUEEZE", "BB_BOUNCE", "EMA_STACK"]:
        st = strategy_trades.get(strat_name, [])
        if not st:
            continue
        print(f"\n  {strat_name}:")
        for regime in ["BULL", "BEAR", "RANGE"]:
            rt = [t for t in st if t.market_regime == regime]
            if rt:
                w = sum(1 for t in rt if t.pnl_pct > 0)
                wr = round(w / len(rt) * 100, 1)
                pnl = sum(TRADE_SIZE * (t.pnl_pct / 100) for t in rt)
                print(f"    {regime}: {len(rt)}건 WR {wr}% | {pnl:+,.0f}원")


if __name__ == "__main__":
    main()
