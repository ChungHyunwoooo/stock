"""ABM 시뮬 결과 비교 — stylized facts + 실제 데이터 대비 유사도.

비교 메트릭:
  - 수익률 분포: KS-test, 첨도, 왜도
  - 시계열 특성: 변동성 클러스터링 (수익률² 자기상관)
  - 거래량-변동성 상관
  - L3 패턴: OI-가격 관계, 펀딩비-반전 확률
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


def calc_stylized_facts(df: pd.DataFrame) -> dict[str, float]:
    """OHLCV DataFrame에서 stylized facts 추출.

    Args:
        df: open, high, low, close, volume 컬럼 필요

    Returns:
        통계 지표 dict
    """
    close = df["close"].values.astype(float)
    returns = np.diff(np.log(close))
    returns = returns[~np.isnan(returns)]

    if len(returns) < 20:
        return {"error": "insufficient_data"}

    volume = df["volume"].values.astype(float) if "volume" in df.columns else np.ones(len(close))
    abs_returns = np.abs(returns)

    # 수익률 분포
    kurtosis = float(sp_stats.kurtosis(returns, fisher=True))
    skewness = float(sp_stats.skew(returns))

    # 변동성 클러스터링: |r_t|와 |r_{t-1}|의 자기상관
    if len(abs_returns) > 2:
        vol_autocorr = float(np.corrcoef(abs_returns[:-1], abs_returns[1:])[0, 1])
    else:
        vol_autocorr = 0.0

    # 수익률² 자기상관 (ARCH 효과)
    sq_returns = returns ** 2
    if len(sq_returns) > 2:
        sq_autocorr = float(np.corrcoef(sq_returns[:-1], sq_returns[1:])[0, 1])
    else:
        sq_autocorr = 0.0

    # 거래량-변동성 상관
    vol_aligned = volume[1:]  # returns는 diff이므로 1개 짧음
    if len(vol_aligned) == len(abs_returns) and len(abs_returns) > 2:
        vol_volume_corr = float(np.corrcoef(abs_returns, vol_aligned)[0, 1])
    else:
        vol_volume_corr = 0.0

    # 수익률 자기상관 (효율적 시장이면 0에 가까움)
    if len(returns) > 2:
        return_autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
    else:
        return_autocorr = 0.0

    # Hurst exponent 근사 (R/S 분석 간소화)
    hurst = _estimate_hurst(returns)

    return {
        "kurtosis": round(kurtosis, 4),
        "skewness": round(skewness, 4),
        "vol_autocorr": round(vol_autocorr, 4),
        "sq_return_autocorr": round(sq_autocorr, 4),
        "vol_volume_corr": round(vol_volume_corr, 4),
        "return_autocorr": round(return_autocorr, 4),
        "hurst": round(hurst, 4),
        "mean_return": round(float(np.mean(returns)), 6),
        "std_return": round(float(np.std(returns)), 6),
    }


def calc_l3_facts(l3_df: pd.DataFrame, ohlcv_df: pd.DataFrame) -> dict[str, float]:
    """L3 데이터의 stylized facts.

    Args:
        l3_df: funding_rate, oi, cvd, ls_ratio, liquidation_count
        ohlcv_df: close 필요
    """
    if len(l3_df) < 20 or len(ohlcv_df) < 20:
        return {}

    close = ohlcv_df["close"].values[:len(l3_df)].astype(float)
    returns = np.diff(np.log(close))

    result: dict[str, float] = {}

    # OI-가격 상관
    if "oi" in l3_df.columns:
        oi = l3_df["oi"].values[:len(returns)].astype(float)
        oi_change = np.diff(oi)
        min_len = min(len(returns), len(oi_change))
        if min_len > 2:
            result["oi_return_corr"] = round(
                float(np.corrcoef(returns[:min_len], oi_change[:min_len])[0, 1]), 4,
            )

    # 펀딩비-수익률 후행 상관 (펀딩 극단 → 다음 구간 반전?)
    if "funding_rate" in l3_df.columns:
        funding = l3_df["funding_rate"].values.astype(float)
        if len(funding) > 10 and len(returns) > 10:
            min_len = min(len(funding) - 1, len(returns) - 1)
            # 펀딩비[t] vs 수익률[t+1]
            result["funding_lead_corr"] = round(
                float(np.corrcoef(funding[:min_len], returns[1:min_len + 1])[0, 1]), 4,
            )

    # 청산 집중도: 전체 청산 중 상위 10% 구간에 몇 % 집중?
    if "liquidation_count" in l3_df.columns:
        liqs = l3_df["liquidation_count"].values.astype(float)
        total_liqs = liqs.sum()
        if total_liqs > 0:
            sorted_liqs = np.sort(liqs)[::-1]
            top_10pct = int(max(1, len(sorted_liqs) * 0.1))
            result["liquidation_concentration"] = round(
                float(sorted_liqs[:top_10pct].sum() / total_liqs), 4,
            )

    return result


def compare_with_real(
    sim_ohlcv: pd.DataFrame,
    real_ohlcv: pd.DataFrame,
    sim_l3: pd.DataFrame | None = None,
    real_l3: pd.DataFrame | None = None,
) -> dict[str, float]:
    """시뮬 vs 실제 유사도 비교.

    Returns:
        각 메트릭별 유사도 점수 + total_score (0~1)
    """
    sim_facts = calc_stylized_facts(sim_ohlcv)
    real_facts = calc_stylized_facts(real_ohlcv)

    if "error" in sim_facts or "error" in real_facts:
        return {"total_score": 0.0, "error": "insufficient_data"}

    scores: dict[str, float] = {}

    # KS-test: 수익률 분포 유사도
    sim_returns = np.diff(np.log(sim_ohlcv["close"].values.astype(float)))
    real_returns = np.diff(np.log(real_ohlcv["close"].values.astype(float)))
    ks_stat, ks_p = sp_stats.ks_2samp(sim_returns, real_returns)
    scores["ks_pvalue"] = round(float(ks_p), 4)

    # 각 fact의 상대 오차 → 유사도
    for key in ["kurtosis", "vol_autocorr", "sq_return_autocorr", "vol_volume_corr"]:
        sim_val = sim_facts.get(key, 0)
        real_val = real_facts.get(key, 0)
        denominator = max(abs(real_val), 0.01)
        relative_error = abs(sim_val - real_val) / denominator
        # 오차 → 유사도 (0~1)
        scores[f"{key}_similarity"] = round(max(0, 1 - relative_error), 4)

    # L3 비교 (있을 때만)
    if sim_l3 is not None and real_l3 is not None:
        sim_l3_facts = calc_l3_facts(sim_l3, sim_ohlcv)
        real_l3_facts = calc_l3_facts(real_l3, real_ohlcv)
        for key in sim_l3_facts:
            if key in real_l3_facts:
                sim_val = sim_l3_facts[key]
                real_val = real_l3_facts[key]
                denominator = max(abs(real_val), 0.01)
                relative_error = abs(sim_val - real_val) / denominator
                scores[f"l3_{key}_similarity"] = round(max(0, 1 - relative_error), 4)

    # 종합 점수: 모든 similarity 점수의 평균
    sim_scores = [v for k, v in scores.items() if k.endswith("_similarity")]
    # KS p-value도 포함 (높을수록 분포가 유사)
    sim_scores.append(min(scores.get("ks_pvalue", 0), 1.0))

    scores["total_score"] = round(float(np.mean(sim_scores)) if sim_scores else 0.0, 4)
    scores["sim_facts"] = sim_facts  # type: ignore[assignment]
    scores["real_facts"] = real_facts  # type: ignore[assignment]

    return scores


def _estimate_hurst(returns: np.ndarray, max_lag: int = 20) -> float:
    """Hurst 지수 간이 추정 (R/S 분석).

    H > 0.5: 추세 지속성 (모멘텀)
    H = 0.5: 랜덤워크
    H < 0.5: 평균회귀
    """
    if len(returns) < max_lag * 4:
        return 0.5

    lags = range(2, max_lag + 1)
    rs_values = []

    for lag in lags:
        rs_list = []
        for start in range(0, len(returns) - lag, lag):
            segment = returns[start:start + lag]
            mean_seg = np.mean(segment)
            cumdev = np.cumsum(segment - mean_seg)
            r = np.max(cumdev) - np.min(cumdev)
            s = np.std(segment, ddof=1) if np.std(segment, ddof=1) > 0 else 1e-10
            rs_list.append(r / s)
        if rs_list:
            rs_values.append((np.log(lag), np.log(np.mean(rs_list))))

    if len(rs_values) < 3:
        return 0.5

    x = np.array([v[0] for v in rs_values])
    y = np.array([v[1] for v in rs_values])
    slope, _, _, _, _ = sp_stats.linregress(x, y)
    return max(0.0, min(1.0, float(slope)))
