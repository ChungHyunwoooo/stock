"""OHLCV 인메모리 캐시 + 병렬 REST fetch.

심볼 × 타임프레임별 DataFrame을 TTL 기반으로 캐시하고,
ThreadPoolExecutor를 사용해 8개씩 병렬 fetch한다.
Upbit API 속도 제한(10 req/s)을 준수.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Upbit interval string mapping
INTERVAL_MAP = {
    "5m": "minute5",
    "15m": "minute15",
    "30m": "minute30",
    "1h": "minute60",
    "4h": "minute240",
    "1d": "day",
    "1w": "week",
}

# Default bar counts per interval
BAR_COUNTS = {
    "5m": 200,
    "15m": 100,
    "30m": 200,
    "1h": 200,
    "4h": 200,
    "1d": 60,    # 60일 = ~2개월
    "1w": 26,    # 26주 = ~6개월
}

# TTL per interval (seconds)
TTL_MAP = {
    "5m": 4 * 60,     # 4분 (5분봉 주기보다 짧게)
    "15m": 10 * 60,    # 10분
    "30m": 20 * 60,    # 20분
    "1h": 30 * 60,     # 30분
    "4h": 2 * 3600,    # 2시간
    "1d": 3600,        # 1시간 (일봉은 자주 안바뀜)
    "1w": 7200,        # 2시간
}


@dataclass
class CacheEntry:
    """캐시 항목."""
    df: pd.DataFrame
    fetched_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return time.time() - self.fetched_at > self.ttl


class OHLCVCacheManager:
    """OHLCV 인메모리 캐시 매니저.

    - 심볼 × 타임프레임별 DataFrame 캐시
    - TTL 기반 자동 만료
    - 병렬 batch fetch (ThreadPoolExecutor)
    - Upbit 10 req/s 제한 준수
    """

    def __init__(self, max_workers: int = 5, rate_limit_per_sec: float = 8.0) -> None:
        self._cache: dict[str, CacheEntry] = {}  # "symbol:interval" -> CacheEntry
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._rate_limit = rate_limit_per_sec
        self._last_fetch_time: float = 0.0
        self._fetch_lock = Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "fetches": 0,
            "errors": 0,
        }

    def _cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}:{interval}"

    def get(self, symbol: str, interval: str = "5m") -> pd.DataFrame | None:
        """캐시에서 OHLCV 조회. TTL 만료 시 None."""
        key = self._cache_key(symbol, interval)
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.expired:
                self._stats["hits"] += 1
                return entry.df.copy()
            self._stats["misses"] += 1
            return None

    def put(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """캐시에 OHLCV 저장."""
        key = self._cache_key(symbol, interval)
        ttl = TTL_MAP.get(interval, 4 * 60)
        with self._lock:
            self._cache[key] = CacheEntry(df=df, fetched_at=time.time(), ttl=ttl)

    def invalidate(self, symbol: str, interval: str | None = None) -> None:
        """캐시 무효화."""
        with self._lock:
            if interval:
                key = self._cache_key(symbol, interval)
                self._cache.pop(key, None)
            else:
                keys = [k for k in self._cache if k.startswith(f"{symbol}:")]
                for k in keys:
                    del self._cache[k]

    def invalidate_all(self) -> None:
        """전체 캐시 무효화."""
        with self._lock:
            self._cache.clear()

    def _rate_limited_fetch(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """Rate-limited 단일 fetch."""
        import pyupbit

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")
        count = BAR_COUNTS.get(interval, 200)

        # Rate limiting
        with self._fetch_lock:
            elapsed = time.time() - self._last_fetch_time
            min_interval = 1.0 / self._rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_fetch_time = time.time()

        try:
            df = pyupbit.get_ohlcv(symbol, interval=upbit_interval, count=count)
            if df is not None and not df.empty:
                self._stats["fetches"] += 1
                self.put(symbol, interval, df)
                return df
        except Exception as e:
            self._stats["errors"] += 1
            logger.warning("Cache fetch failed: %s %s — %s", symbol, interval, e)

        return None

    def _fetch_current_bar(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """현재 봉 1건만 재조회 (rate-limited)."""
        import pyupbit

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")

        with self._fetch_lock:
            elapsed = time.time() - self._last_fetch_time
            min_interval = 1.0 / self._rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_fetch_time = time.time()

        try:
            df = pyupbit.get_ohlcv(symbol, interval=upbit_interval, count=1)
            if df is not None and not df.empty:
                self._stats["fetches"] += 1
                return df
        except Exception as e:
            logger.warning("Current bar fetch failed: %s %s — %s", symbol, interval, e)
        return None

    def fetch_single(self, symbol: str, interval: str = "5m") -> pd.DataFrame | None:
        """단일 심볼 fetch (캐시 히트 시 캐시 반환)."""
        cached = self.get(symbol, interval)
        if cached is not None:
            return cached
        return self._rate_limited_fetch(symbol, interval)

    def fetch_realtime(self, symbol: str, interval: str = "5m") -> pd.DataFrame | None:
        """실시간 조회: 마감 봉은 캐시 + 현재 봉만 재조회.

        캐시 히트 시 현재 봉 1건만 API 호출 → 속도 극대화.
        캐시 미스 시 전체 fetch 후 캐시 저장.
        """
        cached = self.get(symbol, interval)
        if cached is None:
            return self._rate_limited_fetch(symbol, interval)

        # 현재 봉 1건 재조회
        current = self._fetch_current_bar(symbol, interval)
        if current is None or current.empty:
            return cached

        # 캐시된 마감 봉 + 현재 봉 교체
        result = cached.copy()
        current_idx = current.index[0]

        if current_idx in result.index:
            # 같은 시간 봉 교체 (현재 봉 업데이트)
            result.loc[current_idx] = current.iloc[0]
        else:
            # 새 봉 추가
            result = pd.concat([result, current])

        return result

    def prefetch_batch(
        self,
        symbols: list[str],
        intervals: list[str] | None = None,
        batch_size: int = 8,
    ) -> dict[str, dict[str, pd.DataFrame | None]]:
        """여러 심볼 × 타임프레임 병렬 fetch.

        Returns: {symbol: {interval: DataFrame | None}}
        """
        if intervals is None:
            intervals = ["5m"]

        results: dict[str, dict[str, pd.DataFrame | None]] = {
            s: {i: None for i in intervals} for s in symbols
        }

        # Collect tasks: skip cache hits
        tasks: list[tuple[str, str]] = []
        for symbol in symbols:
            for interval in intervals:
                cached = self.get(symbol, interval)
                if cached is not None:
                    results[symbol][interval] = cached
                else:
                    tasks.append((symbol, interval))

        if not tasks:
            return results

        # Batch fetch using ThreadPoolExecutor
        for batch_start in range(0, len(tasks), batch_size):
            batch = tasks[batch_start:batch_start + batch_size]
            futures = {}
            for symbol, interval in batch:
                future = self._executor.submit(self._rate_limited_fetch, symbol, interval)
                futures[future] = (symbol, interval)

            for future in as_completed(futures):
                symbol, interval = futures[future]
                try:
                    df = future.result()
                    if df is not None:
                        results[symbol][interval] = df
                except Exception as e:
                    logger.warning("Batch fetch error: %s %s — %s", symbol, interval, e)

        return results

    def prune_expired(self) -> int:
        """만료된 캐시 항목 제거. 제거된 개수 반환."""
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.expired]
            for k in expired_keys:
                del self._cache[k]
            return len(expired_keys)

    def stats(self) -> dict[str, Any]:
        """캐시 통계."""
        with self._lock:
            total = len(self._cache)
            expired = sum(1 for v in self._cache.values() if v.expired)
            intervals = {}
            for key in self._cache:
                _, interval = key.rsplit(":", 1)
                intervals[interval] = intervals.get(interval, 0) + 1

        return {
            "total_entries": total,
            "active_entries": total - expired,
            "expired_entries": expired,
            "by_interval": intervals,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "fetches": self._stats["fetches"],
            "errors": self._stats["errors"],
            "hit_rate": (
                round(self._stats["hits"] / max(1, self._stats["hits"] + self._stats["misses"]) * 100, 1)
            ),
        }

    def fetch_historical(
        self,
        symbol: str,
        interval: str = "5m",
        days: int = 30,
        max_bars: int = 10000,
        to: "datetime | None" = None,
    ) -> pd.DataFrame | None:
        """백테스트용 과거 데이터 수집.

        pyupbit 200봉 제한 → 반복 호출로 이어붙이기.
        `to` 파라미터로 역방향 페이징.

        Args:
            symbol: 심볼 (e.g. "KRW-BTC")
            interval: 타임프레임 ("5m", "15m", "1h", "1d", "1w")
            days: 수집 기간 (일)
            max_bars: 최대 봉 수 제한
            to: 수집 종료 시점 (None이면 현재)

        Returns:
            시간순 정렬된 OHLCV DataFrame 또는 None
        """
        import pyupbit
        from datetime import datetime, timedelta

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")

        # 예상 봉 수 계산
        bars_per_day = {"5m": 288, "15m": 96, "1h": 24, "1d": 1, "1w": 1 / 7}
        estimated_bars = int(days * bars_per_day.get(interval, 288))
        target_bars = min(estimated_bars, max_bars)

        all_dfs: list[pd.DataFrame] = []
        collected = 0
        to_dt = to if to is not None else datetime.now()
        batch_size = 200

        while collected < target_bars:
            remaining = min(batch_size, target_bars - collected)

            # Rate limiting
            with self._fetch_lock:
                elapsed = time.time() - self._last_fetch_time
                min_interval = 1.0 / self._rate_limit
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                self._last_fetch_time = time.time()

            try:
                df = pyupbit.get_ohlcv(
                    symbol, interval=upbit_interval,
                    count=remaining, to=to_dt,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)
                collected += len(df)
                self._stats["fetches"] += 1

                # 다음 페이지: 가장 오래된 봉의 시간 전으로 이동
                to_dt = df.index[0] - timedelta(seconds=1)

                # 반환된 봉 수가 요청보다 적으면 더 이상 데이터 없음
                if len(df) < remaining:
                    break

            except Exception as e:
                self._stats["errors"] += 1
                logger.warning("Historical fetch error: %s %s — %s", symbol, interval, e)
                break

        if not all_dfs:
            return None

        # 역순 concat → 중복 제거 → 시간순 정렬
        result = pd.concat(all_dfs)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)

        logger.info(
            "Historical fetch: %s %s — %d bars (%s ~ %s)",
            symbol, interval, len(result),
            result.index[0], result.index[-1],
        )
        return result

    def shutdown(self) -> None:
        """ExecutorI 종료."""
        self._executor.shutdown(wait=False)
