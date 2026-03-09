"""거래량 프로파일 분석 — OBV, MFI, 거래량 추세, 다이버전스.

의존성: talib, numpy, pandas
성능: ~2ms
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def calc_volume_profile(df: pd.DataFrame, lookback: int = 20) -> dict:
    """거래량 프로파일 분석.

    OBV 스마트머니 방향, MFI 자금 유입/유출,
    거래량 추세, 가격-거래량 다이버전스, 클라이맥스 감지.

    Returns:
        {
            vol_ratio: float,           # 현재 거래량 / 20봉 평균
            vol_trend: str,             # "RISING" | "FALLING" | "FLAT"
            obv_trend: str,             # "RISING" | "FALLING" | "FLAT"
            vol_price_divergence: bool, # 가격 신고점 + OBV 미달
            mfi: float,                 # Money Flow Index (0-100)
            is_climactic: bool,         # vol > 4x avg (고점 소진 가능)
        }
    """
    result = {
        "vol_ratio": 0.0,
        "vol_trend": "FLAT",
        "obv_trend": "FLAT",
        "vol_price_divergence": False,
        "mfi": 50.0,
        "is_climactic": False,
    }

    if len(df) < lookback + 5:
        return result

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values

    # --- 거래량 비율 ---
    vol_avg = float(np.mean(vol[-lookback:]))
    if vol_avg > 0:
        result["vol_ratio"] = round(float(vol[-1]) / vol_avg, 2)
    result["is_climactic"] = result["vol_ratio"] >= 4.0

    # --- 거래량 추세: 최근 5봉 평균 vs 이전 5봉 평균 ---
    if len(vol) >= lookback:
        recent_5 = float(np.mean(vol[-5:]))
        prev_5 = float(np.mean(vol[-10:-5]))
        if prev_5 > 0:
            ratio = recent_5 / prev_5
            if ratio > 1.2:
                result["vol_trend"] = "RISING"
            elif ratio < 0.8:
                result["vol_trend"] = "FALLING"
            else:
                result["vol_trend"] = "FLAT"

    # --- OBV 추세 (기울기 분석) ---
    obv = talib.OBV(close, vol.astype(float))
    if not np.isnan(obv[-1]) and not np.isnan(obv[-5]):
        obv_recent = float(obv[-1])
        obv_prev = float(obv[-5])
        if obv_prev != 0:
            obv_change = (obv_recent - obv_prev) / abs(obv_prev)
            if obv_change > 0.02:
                result["obv_trend"] = "RISING"
            elif obv_change < -0.02:
                result["obv_trend"] = "FALLING"
            else:
                result["obv_trend"] = "FLAT"

    # --- MFI ---
    mfi = talib.MFI(high, low, close, vol.astype(float), timeperiod=14)
    if not np.isnan(mfi[-1]):
        result["mfi"] = round(float(mfi[-1]), 2)

    # --- 가격-거래량 다이버전스 ---
    # 가격 신고점 + OBV 미달 = 경고
    price_lb = close[-lookback:]
    obv_lb = obv[-lookback:]

    if not np.any(np.isnan(obv_lb)):
        # 최근 절반 vs 이전 절반
        half = lookback // 2
        early_price_max = float(np.max(price_lb[:half]))
        late_price_max = float(np.max(price_lb[half:]))
        early_obv_max = float(np.max(obv_lb[:half]))
        late_obv_max = float(np.max(obv_lb[half:]))

        # Bearish divergence: 가격 신고점 but OBV 못 따라감
        if late_price_max > early_price_max and late_obv_max < early_obv_max:
            result["vol_price_divergence"] = True

    result["vpvr"] = calc_vpvr(df)
    return result


def calc_vpvr(df: pd.DataFrame, num_bins: int = 50, value_area_pct: float = 0.70) -> dict:
    """Volume Profile Visible Range 계산.

    가격 범위를 num_bins개 구간으로 나누고 각 구간의 거래량을 합산.
    POC(최다 거래량 가격), VAH/VAL(전체 거래량의 70% 차지하는 영역 상하한) 산출.

    Returns:
        {
            "poc": float,           # Point of Control (최다 거래량 가격)
            "vah": float,           # Value Area High
            "val": float,           # Value Area Low
            "at_poc": bool,         # 현재가가 POC ±0.5% 이내
            "at_vah": bool,         # 현재가가 VAH ±0.3% 이내
            "at_val": bool,         # 현재가가 VAL ±0.3% 이내
            "in_value_area": bool,  # VAL <= 현재가 <= VAH
            "at_hvn": bool,         # High Volume Node (상위 20% 거래량 구간)
            "at_lvn": bool,         # Low Volume Node (하위 20% 거래량 구간)
        }
    """
    default = {
        "poc": 0.0,
        "vah": 0.0,
        "val": 0.0,
        "at_poc": False,
        "at_vah": False,
        "at_val": False,
        "in_value_area": False,
        "at_hvn": False,
        "at_lvn": False,
    }

    if len(df) < 20:
        return default

    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    current_price = float(df["close"].iloc[-1])

    price_min = float(np.min(low))
    price_max = float(np.max(high))

    if price_max <= price_min:
        return default

    # 균등 분할 bin edges
    edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_vols = np.zeros(num_bins, dtype=float)

    # 각 캔들의 거래량을 걸치는 bin에 비례 분배
    for i in range(len(df)):
        candle_low = float(low[i])
        candle_high = float(high[i])
        candle_vol = float(vol[i])
        candle_range = candle_high - candle_low

        for b in range(num_bins):
            bin_low = edges[b]
            bin_high = edges[b + 1]
            overlap_low = max(candle_low, bin_low)
            overlap_high = min(candle_high, bin_high)
            if overlap_high > overlap_low:
                if candle_range > 0:
                    fraction = (overlap_high - overlap_low) / candle_range
                else:
                    fraction = 1.0 / num_bins
                bin_vols[b] += candle_vol * fraction

    total_vol = float(np.sum(bin_vols))
    if total_vol == 0:
        return default

    # POC: 최다 거래량 bin 중간값
    poc_idx = int(np.argmax(bin_vols))
    poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

    # VAH/VAL: POC에서 양쪽으로 확장하며 누적 거래량이 value_area_pct 도달 시점
    target_vol = total_vol * value_area_pct
    accumulated = bin_vols[poc_idx]
    lo_idx = poc_idx
    hi_idx = poc_idx

    while accumulated < target_vol:
        can_expand_lo = lo_idx > 0
        can_expand_hi = hi_idx < num_bins - 1

        if not can_expand_lo and not can_expand_hi:
            break

        next_lo_vol = bin_vols[lo_idx - 1] if can_expand_lo else -1.0
        next_hi_vol = bin_vols[hi_idx + 1] if can_expand_hi else -1.0

        if next_hi_vol >= next_lo_vol:
            hi_idx += 1
            accumulated += bin_vols[hi_idx]
        else:
            lo_idx -= 1
            accumulated += bin_vols[lo_idx]

    vah = float(edges[hi_idx + 1])
    val = float(edges[lo_idx])

    # 현재가와 레벨 비교
    at_poc = abs(current_price - poc) / poc <= 0.01 if poc > 0 else False
    at_vah = abs(current_price - vah) / vah <= 0.008 if vah > 0 else False
    at_val = abs(current_price - val) / val <= 0.008 if val > 0 else False
    in_value_area = val <= current_price <= vah

    # HVN/LVN: 현재가가 속한 bin 거래량 판별
    current_bin = int(np.searchsorted(edges[1:], current_price, side="left"))
    current_bin = min(current_bin, num_bins - 1)
    hvn_threshold = float(np.percentile(bin_vols, 80))
    lvn_threshold = float(np.percentile(bin_vols, 20))
    at_hvn = float(bin_vols[current_bin]) >= hvn_threshold
    at_lvn = float(bin_vols[current_bin]) <= lvn_threshold

    return {
        "poc": round(poc, 4),
        "vah": round(vah, 4),
        "val": round(val, 4),
        "at_poc": at_poc,
        "at_vah": at_vah,
        "at_val": at_val,
        "in_value_area": in_value_area,
        "at_hvn": at_hvn,
        "at_lvn": at_lvn,
    }
