"""Cross-exchange analysis utilities.

Includes:
- lead/lag proxy score
- kimchi premium estimate
- execution price gap to reference exchange
"""

from __future__ import annotations

import pandas as pd


def _returns(s: pd.Series) -> pd.Series:
    return s.pct_change().dropna()


def _lag_corr(a: pd.Series, b: pd.Series, lag: int) -> float:
    if lag > 0:
        x = a.iloc[:-lag]
        y = b.iloc[lag:]
    elif lag < 0:
        x = a.iloc[-lag:]
        y = b.iloc[:lag]
    else:
        x = a
        y = b
    if len(x) < 10 or len(y) < 10:
        return 0.0
    v = x.corr(y)
    return 0.0 if pd.isna(v) else float(v)


def lead_lag_score(ref_close: pd.Series, target_close: pd.Series, max_lag: int = 5) -> dict:
    r_ref = _returns(ref_close)
    r_tgt = _returns(target_close)
    if r_ref.empty or r_tgt.empty:
        return {"best_lag": 0, "best_corr": 0.0, "leader": "UNKNOWN"}

    aligned = pd.concat([r_ref.rename("ref"), r_tgt.rename("tgt")], axis=1).dropna()
    if len(aligned) < 20:
        return {"best_lag": 0, "best_corr": 0.0, "leader": "UNKNOWN"}

    ref = aligned["ref"]
    tgt = aligned["tgt"]
    best_lag = 0
    best_corr = -1.0
    for lag in range(-max_lag, max_lag + 1):
        c = abs(_lag_corr(ref, tgt, lag))
        if c > best_corr:
            best_corr = c
            best_lag = lag

    # lag > 0: ref changes earlier than target (ref leader)
    # lag < 0: target changes earlier (target leader)
    if best_lag > 0:
        leader = "REFERENCE"
    elif best_lag < 0:
        leader = "TARGET"
    else:
        leader = "SYNC"
    return {"best_lag": int(best_lag), "best_corr": round(best_corr, 4), "leader": leader}


def kimchi_premium(krw_price: float, usdt_price: float, usdkrw: float) -> float:
    if usdt_price <= 0 or usdkrw <= 0:
        return 0.0
    fair_krw = usdt_price * usdkrw
    return (krw_price / fair_krw - 1.0) * 100.0


def execution_gap_pct(execution_price: float, reference_price: float) -> float:
    if execution_price <= 0 or reference_price <= 0:
        return 0.0
    return (execution_price / reference_price - 1.0) * 100.0


def summarize_cross_exchange(
    krw_price: float,
    usdt_price: float,
    usdkrw: float,
    execution_price: float | None = None,
    reference_price: float | None = None,
) -> dict:
    kp = kimchi_premium(krw_price, usdt_price, usdkrw)
    eg = 0.0
    if execution_price is not None and reference_price is not None:
        eg = execution_gap_pct(execution_price, reference_price)
    return {
        "kimchi_premium_pct": round(kp, 3),
        "execution_gap_pct": round(eg, 3),
    }
