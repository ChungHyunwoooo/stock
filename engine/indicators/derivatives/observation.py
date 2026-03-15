"""L3 통합 관측 벡터 — HMM 에이전트 레짐 분류기 입력.

실제 시장 데이터(OHLCV + L3 API) 또는 ABM 시뮬 결과에서
정규화된 관측 벡터를 구성. HMM의 emission 입력으로 사용.

관측 벡터 columns:
  [0] log_returns       가격 변화 방향 (L1)
  [1] volatility        가격 변동성 (L1)
  [2] funding_zscore    펀딩비 z-score (L3)
  [3] oi_change_pct     OI 변화율 (L3)
  [4] cvd_slope         CVD 기울기 (L2)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_from_sim(
    ohlcv: pd.DataFrame,
    l3: pd.DataFrame,
    vol_window: int = 20,
    cvd_window: int = 10,
    funding_window: int = 50,
) -> np.ndarray:
    """ABM 시뮬 결과에서 관측 벡터 구성.

    Args:
        ohlcv: open, high, low, close, volume
        l3: funding_rate, oi, cvd, ls_ratio, liquidation_count

    Returns:
        shape=(n, 5) ndarray — NaN 행은 유효한 윈도우 이전
    """
    close = ohlcv["close"].values.astype(float)
    n = len(close)

    # log returns
    log_ret = np.zeros(n)
    log_ret[1:] = np.diff(np.log(np.maximum(close, 1e-10)))

    # rolling volatility
    vol = np.full(n, np.nan)
    for i in range(vol_window, n):
        vol[i] = np.std(log_ret[i - vol_window:i])

    # funding z-score (rolling window 기준)
    funding = l3["funding_rate"].values.astype(float) if "funding_rate" in l3.columns else np.zeros(n)
    funding_z = np.full(n, np.nan)
    for i in range(funding_window, n):
        window = funding[i - funding_window:i]
        std = np.std(window)
        if std > 1e-10:
            funding_z[i] = (funding[i] - np.mean(window)) / std
        else:
            funding_z[i] = 0.0

    # OI change %
    oi = l3["oi"].values.astype(float) if "oi" in l3.columns else np.zeros(n)
    oi_change = np.full(n, np.nan)
    for i in range(1, n):
        if oi[i - 1] > 0:
            oi_change[i] = (oi[i] - oi[i - 1]) / oi[i - 1]
        else:
            oi_change[i] = 0.0

    # CVD slope (linear regression over window)
    cvd = l3["cvd"].values.astype(float) if "cvd" in l3.columns else np.zeros(n)
    cvd_slope = np.full(n, np.nan)
    x = np.arange(cvd_window, dtype=float)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean) ** 2)
    for i in range(cvd_window, n):
        y = cvd[i - cvd_window:i]
        y_mean = y.mean()
        if x_var > 0:
            slope = np.sum((x - x_mean) * (y - y_mean)) / x_var
            # 정규화: 현재 가격 대비
            cvd_slope[i] = slope / max(close[i], 1e-10)
        else:
            cvd_slope[i] = 0.0

    return np.column_stack([log_ret, vol, funding_z, oi_change, cvd_slope])


def build_from_real(
    ohlcv: pd.DataFrame,
    funding_series: np.ndarray | None = None,
    oi_series: np.ndarray | None = None,
    vol_window: int = 20,
    cvd_window: int = 10,
    funding_window: int = 50,
) -> np.ndarray:
    """실제 시장 데이터에서 관측 벡터 구성.

    Args:
        ohlcv: open, high, low, close, volume
        funding_series: 펀딩비 시계열 (없으면 NaN)
        oi_series: OI 시계열 (없으면 NaN)

    Returns:
        shape=(n, 5) ndarray
    """
    close = ohlcv["close"].values.astype(float)
    n = len(close)

    # log returns + volatility (L1)
    log_ret = np.zeros(n)
    log_ret[1:] = np.diff(np.log(np.maximum(close, 1e-10)))

    vol = np.full(n, np.nan)
    for i in range(vol_window, n):
        vol[i] = np.std(log_ret[i - vol_window:i])

    # CVD from OHLCV estimation (L2)
    o = ohlcv["open"].values.astype(float)
    h = ohlcv["high"].values.astype(float)
    low = ohlcv["low"].values.astype(float)
    v = ohlcv["volume"].values.astype(float)
    hl_range = h - low
    safe_range = np.where(hl_range == 0, 1.0, hl_range)
    buy_ratio = np.clip((close - low) / safe_range, 0.0, 1.0)
    delta = v * (2 * buy_ratio - 1)
    cvd = np.cumsum(delta)

    x = np.arange(cvd_window, dtype=float)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean) ** 2)
    cvd_slope = np.full(n, np.nan)
    for i in range(cvd_window, n):
        y = cvd[i - cvd_window:i]
        y_mean = y.mean()
        if x_var > 0:
            slope = np.sum((x - x_mean) * (y - y_mean)) / x_var
            cvd_slope[i] = slope / max(close[i], 1e-10)
        else:
            cvd_slope[i] = 0.0

    # Funding z-score (L3, optional)
    funding_z = np.full(n, np.nan)
    if funding_series is not None and len(funding_series) == n:
        for i in range(funding_window, n):
            window = funding_series[i - funding_window:i]
            std = np.std(window)
            if std > 1e-10:
                funding_z[i] = (funding_series[i] - np.mean(window)) / std
            else:
                funding_z[i] = 0.0

    # OI change % (L3, optional)
    oi_change = np.full(n, np.nan)
    if oi_series is not None and len(oi_series) == n:
        for i in range(1, n):
            if oi_series[i - 1] > 0:
                oi_change[i] = (oi_series[i] - oi_series[i - 1]) / oi_series[i - 1]
            else:
                oi_change[i] = 0.0

    return np.column_stack([log_ret, vol, funding_z, oi_change, cvd_slope])


def drop_nan_rows(obs: np.ndarray) -> np.ndarray:
    """NaN이 포함된 행 제거."""
    mask = ~np.any(np.isnan(obs), axis=1)
    return obs[mask]


def normalize(obs: np.ndarray, clip_std: float = 3.0) -> np.ndarray:
    """열별 z-score 정규화 + 극단값 클리핑.

    HMM 학습 전 적용 권장 — 스케일 차이와 극단값이 학습을 왜곡.
    """
    result = obs.copy()
    for j in range(result.shape[1]):
        col = result[:, j]
        valid = col[~np.isnan(col)]
        if len(valid) == 0:
            continue
        mean = np.mean(valid)
        std = np.std(valid)
        if std > 1e-10:
            result[:, j] = (col - mean) / std
            result[:, j] = np.clip(result[:, j], -clip_std, clip_std)
    return result
