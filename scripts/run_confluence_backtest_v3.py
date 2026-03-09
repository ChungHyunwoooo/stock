"""Confluence 백테스트 v3 — 방향 필터 적용 (실시간 판단 가능한 필터만)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.confluence_backtest import run_confluence_backtest


def analyze(trades, label=""):
    if not trades:
        print(f"  {label}: 0건")
        return 0, 0
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    wr = round(wins / len(trades) * 100, 1)
    avg_pnl = round(sum(t.pnl_pct for t in trades) / len(trades), 2)
    win_pnls = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    loss_pnls = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    avg_w = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0
    avg_l = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0
    gw = sum(win_pnls) if win_pnls else 0
    gl = abs(sum(loss_pnls)) if loss_pnls else 0
    pf = round(gw / gl, 2) if gl > 0 else float("inf")
    print(f"  {label}: {len(trades)}건 WR {wr}% 평균PnL {avg_pnl}% PF {pf} (승+{avg_w}%/패{avg_l}%)")
    return len(trades), wins


def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    FEE = 0.0004

    print("=" * 70)
    print("BACKTEST v3: 방향 필터 검증")
    print("필터: BULL→LONG만, BEAR→SHORT만, RANGE→SHORT만")
    print("수수료: 0.04% taker, SL1.5ATR, 3TP, 3x leverage")
    print("=" * 70)

    all_trades = []
    filtered_trades = []

    for sym in symbols:
        try:
            result = run_confluence_backtest(
                symbol=sym, start="2024-06-01", end="2025-03-01",
                entry_tf="4h", leverage=3, risk_pct=0.01, min_score=2,
                atr_sl_mult=1.5, tp_ratios=[1.0, 1.5, 2.5],
                max_hold_bars=30, fee_rate=FEE, use_real_funding=True,
            )
            all_trades.extend(result.trades)
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")

    # --- 방향 필터 적용 ---
    for t in all_trades:
        regime = t.market_regime
        side = t.side
        # BULL → LONG만, BEAR → SHORT만, RANGE → SHORT만
        if regime == "BULL" and side == "LONG":
            filtered_trades.append(t)
        elif regime == "BEAR" and side == "SHORT":
            filtered_trades.append(t)
        elif regime == "RANGE" and side == "SHORT":
            filtered_trades.append(t)

    print(f"\n--- 필터 없음 (기존) ---")
    analyze(all_trades, "ALL")

    print(f"\n--- 방향 필터 적용 ---")
    analyze(filtered_trades, "FILTERED")

    # --- 방향 필터 + 변동성 필터 (ATR/price 기반) ---
    # 변동성이 너무 높으면 SL 히트 확률 상승 → 필터 효과 검증
    print(f"\n--- 방향 필터 + exit_reason 분석 ---")
    for reason in ["TP1", "SL", "TIME", "END"]:
        subset = [t for t in filtered_trades if t.exit_reason == reason]
        if subset:
            analyze(subset, f"  {reason}")

    # --- 방향 필터 레짐별 상세 ---
    print(f"\n--- 방향 필터 내 레짐별 ---")
    for regime in ["BULL", "BEAR", "RANGE"]:
        subset = [t for t in filtered_trades if t.market_regime == regime]
        analyze(subset, regime)

    # --- 대안 필터: RANGE에서 양방향 허용 ---
    print(f"\n--- 대안: BULL→LONG, BEAR→SHORT, RANGE→양방향 ---")
    alt_trades = []
    for t in all_trades:
        regime = t.market_regime
        side = t.side
        if regime == "BULL" and side == "LONG":
            alt_trades.append(t)
        elif regime == "BEAR" and side == "SHORT":
            alt_trades.append(t)
        elif regime == "RANGE":
            alt_trades.append(t)
    analyze(alt_trades, "ALT")

    # --- 대안2: 역방향만 제거 (BULL-SHORT, BEAR-LONG 제거) ---
    print(f"\n--- 대안2: 역방향만 제거 ---")
    alt2 = [t for t in all_trades
            if not (t.market_regime == "BULL" and t.side == "SHORT")
            and not (t.market_regime == "BEAR" and t.side == "LONG")]
    analyze(alt2, "NO_COUNTER")

    # --- 심볼별 필터 후 성과 ---
    print(f"\n--- 방향 필터 후 심볼별 ---")
    sym_map = {}
    for t in filtered_trades:
        # entry_date로 심볼 추적 불가 → 전체 재실행 대신 비율 확인
        pass

    # 심볼별 필터 후 재계산
    for sym in symbols:
        try:
            result = run_confluence_backtest(
                symbol=sym, start="2024-06-01", end="2025-03-01",
                entry_tf="4h", leverage=3, risk_pct=0.01, min_score=2,
                atr_sl_mult=1.5, tp_ratios=[1.0, 1.5, 2.5],
                max_hold_bars=30, fee_rate=FEE, use_real_funding=True,
            )
            sym_filtered = []
            for t in result.trades:
                r, s = t.market_regime, t.side
                if (r == "BULL" and s == "LONG") or (r == "BEAR" and s == "SHORT") or (r == "RANGE" and s == "SHORT"):
                    sym_filtered.append(t)
            analyze(sym_filtered, sym)
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")


if __name__ == "__main__":
    main()
