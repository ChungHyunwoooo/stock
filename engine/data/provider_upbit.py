"""Upbit DataProvider — pyupbit 기반 KRW 마켓 데이터 제공.

ccxt의 Upbit 지원이 제한적이므로 (역방향 페이징 미지원, D1 데이터 빈 반환),
pyupbit를 직접 사용하여 DataProvider 인터페이스를 구현.

심볼 변환: "BTC/KRW" → "KRW-BTC" (pyupbit 형식)
"""

import logging

import pandas as pd

from engine.data.provider_base import DataProvider
from engine.data.upbit_cache import OHLCVCacheManager

logger = logging.getLogger(__name__)

# 타임프레임별 하루 봉 수
_BARS_PER_DAY = {
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "4h": 6,
    "1d": 1,
    "1w": 1 / 7,
}

def _to_upbit_symbol(symbol: str) -> str:
    """BTC/KRW → KRW-BTC 변환."""
    if "/" not in symbol:
        return symbol
    base, quote = symbol.split("/", 1)
    return f"{quote}-{base}"

def _from_upbit_symbol(upbit_symbol: str) -> str:
    """KRW-BTC → BTC/KRW 변환."""
    if "-" not in upbit_symbol:
        return upbit_symbol
    quote, base = upbit_symbol.split("-", 1)
    return f"{base}/{quote}"

class UpbitProvider(DataProvider):
    """pyupbit 기반 Upbit 데이터 프로바이더."""

    def __init__(self, realtime: bool = False) -> None:
        self._cache = OHLCVCacheManager(max_workers=3, rate_limit_per_sec=8.0)
        self._realtime = realtime  # True: 마감봉 캐시 + 현재봉 재조회

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1d",
    ) -> pd.DataFrame:
        upbit_sym = _to_upbit_symbol(symbol)

        start_ts = pd.Timestamp(start, tz="Asia/Seoul")
        end_ts = pd.Timestamp(end, tz="Asia/Seoul")
        days = max(1, (end_ts - start_ts).days + 1)

        # to 파라미터: end 날짜의 다음날 00:00 (KST) → 해당 날짜까지 포함
        to_dt = (end_ts + pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=None)

        # 실시간 모드: 마감봉 캐시 + 현재봉 재조회
        if self._realtime:
            # 먼저 히스토리 캐시 확보 (없으면 full fetch)
            cached = self._cache.get(upbit_sym, timeframe)
            if cached is None:
                df = self._cache.fetch_historical(
                    upbit_sym, interval=timeframe, days=days,
                    max_bars=50000, to=to_dt,
                )
                if df is not None and not df.empty:
                    self._cache.put(upbit_sym, timeframe, df)
            else:
                df = cached

            # 현재 봉 1건 갱신
            current = self._cache._fetch_current_bar(upbit_sym, timeframe)
            if current is not None and not current.empty and df is not None:
                df = df.copy()
                cidx = current.index[0]
                if cidx in df.index:
                    df.loc[cidx] = current.iloc[0]
                else:
                    df = pd.concat([df, current])
                    df.sort_index(inplace=True)
        else:
            df = self._cache.fetch_historical(
                upbit_sym, interval=timeframe, days=days,
                max_bars=50000, to=to_dt,
            )

        if df is None or df.empty:
            logger.warning("%s (%s) 데이터 없음", symbol, upbit_sym)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # pyupbit 인덱스는 KST(Asia/Seoul) → UTC 변환
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Seoul")
        df.index = df.index.tz_convert("UTC")

        # 기간 필터
        start_utc = pd.Timestamp(start, tz="UTC")
        end_utc = pd.Timestamp(end, tz="UTC")
        df = df[(df.index >= start_utc) & (df.index <= end_utc)]

        # 컬럼 정규화 (pyupbit: open, high, low, close, volume, value)
        cols = ["open", "high", "low", "close", "volume"]
        for col in cols:
            if col not in df.columns:
                df[col] = 0.0
        df = df[cols]

        logger.info(
            "%s %s: %d봉 (%s ~ %s)",
            symbol, timeframe, len(df),
            df.index[0] if len(df) > 0 else "N/A",
            df.index[-1] if len(df) > 0 else "N/A",
        )
        return df

    def shutdown(self) -> None:
        self._cache.shutdown()
