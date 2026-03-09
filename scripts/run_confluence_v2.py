"""Confluence v2 백테스트 러너 — 멀티TF 아키텍처 (1H scoring + 5m entry).

5개 심볼, 2년 기간, 고정금액(10만원 자본 / 1만원 거래), 3x vs 5x 비교.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest_v2 import ConfluenceTradeV2, run_confluence_backtest_v2

FEE = 0.0004
CAPITAL = 100_000  # 10만원
TRADE_SIZE = 10_000  # 1만원 고정


def calc_fixed_size(trades: list[ConfluenceTradeV2], label: str, leverage: int = 3) -> dict:
    """고정 금액 기준 손익 계산 + 출력."""
    equity = CAPITAL
    peak = CAPITAL
    max_dd = 0.0
    wins = 0

    monthly_pnl: dict[str, float] = {}

    for t in trades:
        # pnl_pct는 이미 레버리지 반영됨 (v2 기본 leverage)
        # leverage 파라미터로 다른 레버리지 비교 시 비율 조정
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
        return {"total_pnl": 0, "trades": 0, "wins": 0, "max_dd": 0}

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
    regimes: dict[str, list[ConfluenceTradeV2]] = {}
    for t in trades:
        regimes.setdefault(t.market_regime, []).append(t)
    print("    레짐: ", end="")
    for r in ["BULL", "BEAR", "RANGE"]:
        rt = regimes.get(r, [])
        if rt:
            rw = sum(1 for t in rt if t.pnl_pct > 0)
            print(f"{r} {len(rt)}건 WR{round(rw / len(rt) * 100)}%  ", end="")
    print()

    # 월별 손익
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

    # SL % 통계
    sl_pcts = [t.entry_tf_sl_pct for t in trades if t.entry_tf_sl_pct > 0]
    if sl_pcts:
        print(f"    5m SL%: 평균 {sum(sl_pcts)/len(sl_pcts):.3f}% | "
              f"최소 {min(sl_pcts):.3f}% | 최대 {max(sl_pcts):.3f}%")

    return {"total_pnl": total_pnl, "trades": n, "wins": wins, "max_dd": max_dd}


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    start = "2023-03-01"
    end = "2025-03-01"

    print("=" * 70)
    print("Confluence v2 백테스트 (멀티TF: D1/4H 방향 + 1H 스코어링 + 5m 진입)")
    print(f"기간: {start} ~ {end} | 자본 {CAPITAL:,}원 | 거래금액 {TRADE_SIZE:,}원 고정")
    print(f"ADX >= 25 | D1 EMA200 방향필터 | SHORT min_score=3")
    print("=" * 70)

    all_trades: list[ConfluenceTradeV2] = []

    # --- 심볼별 실행 ---
    print("\n--- 심볼별 결과 ---")
    import time
    for idx_s, sym in enumerate(symbols):
        t0 = time.time()
        print(f"\n  [{idx_s+1}/{len(symbols)}] {sym} 처리 중...", flush=True)
        try:
            result = run_confluence_backtest_v2(
                symbol=sym,
                start=start,
                end=end,
                scoring_tf="1h",
                entry_tf="5m",
                leverage=3,
                risk_pct=0.01,
                min_score=2,
                min_score_short=3,
                tp_ratio=2.0,
                max_armed_bars=12,
                adx_threshold=25,
                mtf_threshold_long=0.55,
                mtf_threshold_short=0.70,
                fee_rate=FEE,
                use_real_funding=True,
            )
            n = len(result.trades)
            w = result.wins
            wr = round(w / n * 100, 1) if n > 0 else 0
            longs = [t for t in result.trades if t.side == "LONG"]
            shorts = [t for t in result.trades if t.side == "SHORT"]
            print(f"\n  {sym}: {n}건 (L:{len(longs)} S:{len(shorts)}) WR {wr}%")
            print(f"    PF {result.profit_factor} | "
                  f"평균승 {result.avg_win_pct}% / 평균패 {result.avg_loss_pct}%")
            print(f"    점수분포: {result.score_distribution}")
            print(f"    소요: {time.time()-t0:.1f}초", flush=True)

            all_trades.extend(result.trades)

        except Exception as e:
            print(f"\n  {sym}: ERROR - {e}")
            import traceback
            traceback.print_exc()

    if not all_trades:
        print("\n거래 없음. 종료.")
        return

    # 시간순 정렬
    all_trades.sort(key=lambda t: t.entry_date)

    print(f"\n{'=' * 70}")
    print(f"합산 {len(all_trades)}건")
    print(f"{'=' * 70}")

    # --- 3x 레버리지 ---
    print(f"\n--- 3x 레버리지 ---")
    calc_fixed_size(all_trades, "전체 3x", leverage=3)

    # --- 5x 레버리지 ---
    print(f"\n--- 5x 레버리지 ---")
    calc_fixed_size(all_trades, "전체 5x", leverage=5)

    # --- LONG/SHORT 분석 ---
    longs = [t for t in all_trades if t.side == "LONG"]
    shorts = [t for t in all_trades if t.side == "SHORT"]

    print(f"\n--- 방향별 (3x) ---")
    calc_fixed_size(longs, "LONG 3x", leverage=3)
    calc_fixed_size(shorts, "SHORT 3x", leverage=3)

    # --- 레짐별 분석 ---
    print(f"\n--- 레짐별 (3x) ---")
    for regime in ["BULL", "BEAR", "RANGE"]:
        regime_trades = [t for t in all_trades if t.market_regime == regime]
        if regime_trades:
            calc_fixed_size(regime_trades, f"{regime} 3x", leverage=3)

    # --- Exit reason 분포 ---
    print(f"\n--- 청산 사유 분포 ---")
    reasons: dict[str, int] = {}
    for t in all_trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    for reason in ["TP", "SL", "TIME", "END"]:
        cnt = reasons.get(reason, 0)
        pct = round(cnt / len(all_trades) * 100, 1) if all_trades else 0
        print(f"  {reason}: {cnt}건 ({pct}%)")

    # --- Armed → Trigger 변환 통계 ---
    print(f"\n--- 변환 통계 ---")
    print(f"  실행된 트레이드: {len(all_trades)}건")
    avg_armed_to_entry_hrs = []
    for t in all_trades:
        armed_ts = pd.Timestamp(t.armed_date)
        entry_ts = pd.Timestamp(t.entry_date)
        delta_hrs = (entry_ts - armed_ts).total_seconds() / 3600
        avg_armed_to_entry_hrs.append(delta_hrs)
    if avg_armed_to_entry_hrs:
        print(f"  Armed→Entry 평균: {sum(avg_armed_to_entry_hrs)/len(avg_armed_to_entry_hrs):.1f}시간")
        print(f"  Armed→Entry 최대: {max(avg_armed_to_entry_hrs):.1f}시간")


if __name__ == "__main__":
    main()
