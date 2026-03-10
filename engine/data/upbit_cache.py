"""OHLCV 2계층 캐시 (메모리 + Parquet 디스크) + 병렬 REST fetch.

계층 구조:
  1. 메모리 (TTL 기반) — 실시간 조회용, 재시작 시 소실
  2. 디스크 (Parquet, 영속) — 백테스트용, TTL 없음, 증분 업데이트

fetch 흐름:
  메모리 hit → 반환
  메모리 miss → 디스크 hit → 메모리 로드 → 반환
  디스크 miss → API fetch → 디스크+메모리 저장 → 반환

심볼 × 타임프레임별 DataFrame을 캐시하고,
ThreadPoolExecutor를 사용해 병렬 fetch한다.
Upbit API 속도 제한(10 req/s)을 준수.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Upbit interval string mapping
INTERVAL_MAP = {
    "1m": "minute1",
    "3m": "minute3",
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
    "1m": 200,
    "3m": 200,
    "5m": 200,
    "15m": 100,
    "30m": 200,
    "1h": 200,
    "4h": 200,
    "1d": 60,
    "1w": 26,
}

# TTL per interval (seconds) — 메모리 캐시 전용
TTL_MAP = {
    "1m": 50,          # 50초
    "3m": 2 * 60,      # 2분
    "5m": 4 * 60,      # 4분
    "15m": 10 * 60,    # 10분
    "30m": 20 * 60,    # 20분
    "1h": 30 * 60,     # 30분
    "4h": 2 * 3600,    # 2시간
    "1d": 3600,        # 1시간
    "1w": 7200,        # 2시간
}

# 타임프레임별 하루 봉 수
BARS_PER_DAY = {
    "1m": 1440,
    "3m": 480,
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "4h": 6,
    "1d": 1,
    "1w": 1 / 7,
}


@dataclass
class CacheEntry:
    """메모리 캐시 항목."""
    df: pd.DataFrame
    fetched_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return time.time() - self.fetched_at > self.ttl


class OHLCVCacheManager:
    """OHLCV 2계층 캐시 매니저 (메모리 + Parquet 디스크).

    - 메모리: TTL 기반 자동 만료 (실시간 조회용)
    - 디스크: Parquet 영속 저장 (백테스트용, TTL 없음)
    - 증분 업데이트: 디스크에 있는 마지막 봉 이후만 API fetch
    - 병렬 batch fetch (ThreadPoolExecutor)
    - Upbit 10 req/s 제한 준수
    """

    def __init__(
        self,
        max_workers: int = 5,
        rate_limit_per_sec: float = 8.0,
        cache_dir: str | Path = ".cache/ohlcv",
    ) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._rate_limit = rate_limit_per_sec
        self._last_fetch_time: float = 0.0
        self._fetch_lock = Lock()
        self._disk_dir = Path(cache_dir)
        self._disk_dir.mkdir(parents=True, exist_ok=True)
        self._stats = {
            "hits_memory": 0,
            "hits_disk": 0,
            "misses": 0,
            "fetches": 0,
            "errors": 0,
            "disk_saves": 0,
        }

    def _cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}:{interval}"

    def _disk_path(self, symbol: str, interval: str) -> Path:
        """디스크 캐시 경로: .cache/ohlcv/{symbol}_{interval}.parquet"""
        safe_symbol = symbol.replace("/", "_").replace("-", "_")
        return self._disk_dir / f"{safe_symbol}_{interval}.parquet"

    # ── 디스크 I/O ──────────────────────────────────────────

    def _load_from_disk(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """디스크에서 Parquet 로드. 파일 없으면 None."""
        path = self._disk_path(symbol, interval)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            if df.empty:
                return None
            return df
        except Exception as e:
            logger.warning("디스크 캐시 로드 실패: %s — %s", path, e)
            return None

    def _save_to_disk(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """디스크에 Parquet 저장. 기존 데이터와 병합(중복 제거)."""
        if df is None or df.empty:
            return
        path = self._disk_path(symbol, interval)
        try:
            existing = self._load_from_disk(symbol, interval)
            if existing is not None and not existing.empty:
                merged = pd.concat([existing, df])
                merged = merged[~merged.index.duplicated(keep="last")]
                merged.sort_index(inplace=True)
                merged.to_parquet(path)
            else:
                df.to_parquet(path)
            self._stats["disk_saves"] += 1
        except Exception as e:
            logger.warning("디스크 캐시 저장 실패: %s — %s", path, e)

    # ── 메모리 캐시 ─────────────────────────────────────────

    def get(self, symbol: str, interval: str = "5m") -> pd.DataFrame | None:
        """캐시에서 OHLCV 조회.

        1) 메모리 TTL 유효 → 반환
        2) 메모리 만료/없음 → 디스크 로드 → 메모리에 적재 → 반환
        3) 디스크도 없음 → None
        """
        key = self._cache_key(symbol, interval)
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.expired:
                self._stats["hits_memory"] += 1
                return entry.df.copy()

        # 디스크 fallback
        disk_df = self._load_from_disk(symbol, interval)
        if disk_df is not None:
            self._stats["hits_disk"] += 1
            ttl = TTL_MAP.get(interval, 4 * 60)
            with self._lock:
                self._cache[key] = CacheEntry(df=disk_df, fetched_at=time.time(), ttl=ttl)
            return disk_df.copy()

        self._stats["misses"] += 1
        return None

    def put(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """메모리 + 디스크 양쪽에 저장."""
        key = self._cache_key(symbol, interval)
        ttl = TTL_MAP.get(interval, 4 * 60)
        with self._lock:
            self._cache[key] = CacheEntry(df=df, fetched_at=time.time(), ttl=ttl)
        self._save_to_disk(symbol, interval, df)

    def invalidate(self, symbol: str, interval: str | None = None) -> None:
        """메모리 캐시만 무효화 (디스크는 유지)."""
        with self._lock:
            if interval:
                key = self._cache_key(symbol, interval)
                self._cache.pop(key, None)
            else:
                keys = [k for k in self._cache if k.startswith(f"{symbol}:")]
                for k in keys:
                    del self._cache[k]

    def invalidate_all(self) -> None:
        """메모리 캐시 전체 무효화 (디스크는 유지)."""
        with self._lock:
            self._cache.clear()

    def purge_disk(self, symbol: str | None = None, interval: str | None = None) -> int:
        """디스크 캐시 삭제. symbol=None이면 전체 삭제."""
        count = 0
        if symbol and interval:
            path = self._disk_path(symbol, interval)
            if path.exists():
                path.unlink()
                count = 1
        elif symbol:
            for path in self._disk_dir.glob(f"{symbol.replace('/', '_').replace('-', '_')}_*.parquet"):
                path.unlink()
                count += 1
        else:
            for path in self._disk_dir.glob("*.parquet"):
                path.unlink()
                count += 1
        return count

    # ── API Fetch ───────────────────────────────────────────

    def _rate_limited_fetch(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """Rate-limited 단일 fetch."""
        import pyupbit

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")
        count = BAR_COUNTS.get(interval, 200)

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

        current = self._fetch_current_bar(symbol, interval)
        if current is None or current.empty:
            return cached

        result = cached.copy()
        current_idx = current.index[0]

        if current_idx in result.index:
            result.loc[current_idx] = current.iloc[0]
        else:
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

    def diagnose_state(
        self,
        symbol: str,
        interval: str,
        req_start: "pd.Timestamp",
        req_end: "pd.Timestamp",
    ) -> dict[str, Any]:
        """디스크 캐시 상태 진단.

        Returns:
            state: EMPTY | FULL | STALE | PARTIAL_TAIL | PARTIAL_BOTH | GAP | CORRUPTED
            gaps: 누락 구간 리스트 [(start, end), ...]
            disk_start, disk_end: 디스크 데이터 범위
        """
        disk_df = self._load_from_disk(symbol, interval)

        if disk_df is None:
            path = self._disk_path(symbol, interval)
            if path.exists():
                return {"state": "CORRUPTED", "gaps": [(req_start, req_end)]}
            return {"state": "EMPTY", "gaps": [(req_start, req_end)]}

        if disk_df.empty:
            return {"state": "EMPTY", "gaps": [(req_start, req_end)]}

        disk_start = self._to_naive(disk_df.index.min())
        disk_end = self._to_naive(disk_df.index.max())
        req_s = self._to_naive(req_start)
        req_e = self._to_naive(req_end)

        gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []

        # 앞쪽 부족 (PARTIAL_TAIL: 뒤쪽만 있음)
        need_head = disk_start > req_s
        if need_head:
            gaps.append((req_s, disk_start))

        # 뒤쪽 부족 (STALE: 앞쪽만 있음)
        need_tail = disk_end < req_e
        if need_tail:
            gaps.append((disk_end, req_e))

        # 중간 GAP 감지
        inner_gaps = self._detect_gaps(disk_df, interval, req_s, req_e)
        gaps.extend(inner_gaps)

        if not gaps:
            state = "FULL"
        elif need_head and need_tail:
            state = "PARTIAL_BOTH"
        elif need_head:
            state = "PARTIAL_TAIL"
        elif need_tail:
            state = "STALE"
        elif inner_gaps:
            state = "GAP"
        else:
            state = "FULL"

        return {
            "state": state,
            "gaps": gaps,
            "disk_start": disk_start,
            "disk_end": disk_end,
            "disk_bars": len(disk_df),
        }

    @staticmethod
    def _to_naive(ts: "pd.Timestamp") -> pd.Timestamp:
        """tz-aware → tz-naive 변환."""
        ts = pd.Timestamp(ts)
        if ts.tz is not None:
            return ts.tz_localize(None)
        return ts

    def _detect_gaps(
        self,
        df: pd.DataFrame,
        interval: str,
        req_start: pd.Timestamp,
        req_end: pd.Timestamp,
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """DataFrame 내 연속성 검사 → GAP 구간 리스트 반환."""
        if df is None or len(df) < 2:
            return []

        # 요청 범위 내 데이터만
        naive_idx = df.index
        if naive_idx.tz is not None:
            naive_idx = naive_idx.tz_localize(None)

        mask = (naive_idx >= req_start) & (naive_idx <= req_end)
        subset = df[mask]
        if len(subset) < 2:
            return []

        # 예상 간격 (interval → timedelta)
        interval_td = self._interval_to_timedelta(interval)
        # GAP 허용 배수: 2배 이상이면 GAP으로 판정
        threshold = interval_td * 2

        gaps = []
        idx = subset.index
        if idx.tz is not None:
            idx = idx.tz_localize(None)

        for i in range(1, len(idx)):
            delta = idx[i] - idx[i - 1]
            if delta > threshold:
                gaps.append((idx[i - 1], idx[i]))

        return gaps

    @staticmethod
    def _interval_to_timedelta(interval: str) -> pd.Timedelta:
        """타임프레임 문자열 → Timedelta 변환."""
        mapping = {
            "1m": pd.Timedelta(minutes=1),
            "3m": pd.Timedelta(minutes=3),
            "5m": pd.Timedelta(minutes=5),
            "15m": pd.Timedelta(minutes=15),
            "30m": pd.Timedelta(minutes=30),
            "1h": pd.Timedelta(hours=1),
            "4h": pd.Timedelta(hours=4),
            "1d": pd.Timedelta(days=1),
            "1w": pd.Timedelta(weeks=1),
        }
        return mapping.get(interval, pd.Timedelta(minutes=5))

    def fetch_historical(
        self,
        symbol: str,
        interval: str = "5m",
        days: int = 30,
        max_bars: int = 10000,
        to: "datetime | None" = None,
    ) -> pd.DataFrame | None:
        """백테스트용 과거 데이터 수집 (상태 기반 증분 업데이트).

        State별 동작:
          EMPTY/CORRUPTED → 전체 fetch
          FULL → 디스크 반환
          STALE → 뒤쪽만 fetch + 병합
          PARTIAL_TAIL → 앞쪽만 fetch + 병합
          PARTIAL_BOTH → 앞+뒤 fetch + 병합
          GAP → 각 GAP 구간 fetch + 병합

        Args:
            symbol: 심볼 (e.g. "KRW-BTC")
            interval: 타임프레임 ("1m"~"1w")
            days: 수집 기간 (일)
            max_bars: 최대 봉 수 제한
            to: 수집 종료 시점 (None이면 현재)
        """
        from datetime import datetime, timedelta

        to_dt = to if to is not None else datetime.now()
        start_dt = to_dt - timedelta(days=days)

        req_start = pd.Timestamp(start_dt)
        req_end = pd.Timestamp(to_dt)

        diagnosis = self.diagnose_state(symbol, interval, req_start, req_end)
        state = diagnosis["state"]

        logger.info(
            "캐시 상태: %s %s — %s (gaps=%d)",
            symbol, interval, state, len(diagnosis["gaps"]),
        )

        if state == "FULL":
            disk_df = self._load_from_disk(symbol, interval)
            self._load_to_memory(symbol, interval, disk_df)
            return disk_df

        if state in ("EMPTY", "CORRUPTED"):
            return self._fetch_full_historical(symbol, interval, days, max_bars, to_dt)

        # STALE, PARTIAL_TAIL, PARTIAL_BOTH, GAP → 각 gap 구간 fetch + 병합
        disk_df = self._load_from_disk(symbol, interval)
        all_parts = [disk_df] if disk_df is not None else []

        for gap_start, gap_end in diagnosis["gaps"]:
            gap_df = self._fetch_range(
                symbol, interval,
                from_dt=gap_start,
                to_dt=gap_end,
                max_bars=max_bars,
            )
            if gap_df is not None and not gap_df.empty:
                all_parts.append(gap_df)

        if not all_parts:
            return self._fetch_full_historical(symbol, interval, days, max_bars, to_dt)

        merged = pd.concat(all_parts)
        merged = merged[~merged.index.duplicated(keep="last")]
        merged.sort_index(inplace=True)
        self.put(symbol, interval, merged)

        logger.info(
            "증분 업데이트: %s %s — %s → %d봉",
            symbol, interval, state, len(merged),
        )
        return merged

    def _fetch_range(
        self,
        symbol: str,
        interval: str,
        from_dt: "datetime",
        to_dt: "datetime",
        max_bars: int = 10000,
    ) -> pd.DataFrame | None:
        """특정 기간의 OHLCV를 API에서 fetch."""
        import pyupbit
        from datetime import timedelta

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")
        bpd = BARS_PER_DAY.get(interval, 288)
        delta_days = max(1, (pd.Timestamp(to_dt) - pd.Timestamp(from_dt)).days + 1)
        target_bars = min(int(delta_days * bpd), max_bars)

        if target_bars <= 0:
            return None

        all_dfs: list[pd.DataFrame] = []
        collected = 0
        cursor = to_dt
        batch_size = 200

        while collected < target_bars:
            remaining = min(batch_size, target_bars - collected)

            with self._fetch_lock:
                elapsed = time.time() - self._last_fetch_time
                min_interval = 1.0 / self._rate_limit
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                self._last_fetch_time = time.time()

            try:
                df = pyupbit.get_ohlcv(
                    symbol, interval=upbit_interval,
                    count=remaining, to=cursor,
                )
                if df is None or df.empty:
                    break

                # from_dt 이전 데이터 제거
                from_naive = pd.Timestamp(from_dt)
                if df.index.tz is not None:
                    from_naive = from_naive.tz_localize(df.index.tz)
                df = df[df.index >= from_naive]

                if df.empty:
                    break

                all_dfs.append(df)
                collected += len(df)
                self._stats["fetches"] += 1

                cursor = df.index[0] - timedelta(seconds=1)

                if len(df) < remaining:
                    break
            except Exception as e:
                self._stats["errors"] += 1
                logger.warning("Range fetch error: %s %s — %s", symbol, interval, e)
                break

        if not all_dfs:
            return None

        result = pd.concat(all_dfs)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)
        return result

    def _fetch_full_historical(
        self,
        symbol: str,
        interval: str,
        days: int,
        max_bars: int,
        to_dt: "datetime",
    ) -> pd.DataFrame | None:
        """전체 과거 데이터 fetch (디스크 캐시 없을 때)."""
        import pyupbit
        from datetime import timedelta

        upbit_interval = INTERVAL_MAP.get(interval, "minute5")
        bpd = BARS_PER_DAY.get(interval, 288)
        target_bars = min(int(days * bpd), max_bars)

        all_dfs: list[pd.DataFrame] = []
        collected = 0
        cursor = to_dt
        batch_size = 200

        while collected < target_bars:
            remaining = min(batch_size, target_bars - collected)

            with self._fetch_lock:
                elapsed = time.time() - self._last_fetch_time
                min_interval = 1.0 / self._rate_limit
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                self._last_fetch_time = time.time()

            try:
                df = pyupbit.get_ohlcv(
                    symbol, interval=upbit_interval,
                    count=remaining, to=cursor,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)
                collected += len(df)
                self._stats["fetches"] += 1

                cursor = df.index[0] - timedelta(seconds=1)

                if len(df) < remaining:
                    break
            except Exception as e:
                self._stats["errors"] += 1
                logger.warning("Historical fetch error: %s %s — %s", symbol, interval, e)
                break

        if not all_dfs:
            return None

        result = pd.concat(all_dfs)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)

        # 디스크+메모리 저장
        self.put(symbol, interval, result)

        logger.info(
            "Historical fetch: %s %s — %d bars (%s ~ %s)",
            symbol, interval, len(result),
            result.index[0], result.index[-1],
        )
        return result

    def _load_to_memory(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """디스크 데이터를 메모리 캐시에 적재."""
        key = self._cache_key(symbol, interval)
        ttl = TTL_MAP.get(interval, 4 * 60)
        with self._lock:
            self._cache[key] = CacheEntry(df=df, fetched_at=time.time(), ttl=ttl)

    # ── 유틸리티 ────────────────────────────────────────────

    def prune_expired(self) -> int:
        """만료된 메모리 캐시 항목 제거."""
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.expired]
            for k in expired_keys:
                del self._cache[k]
            return len(expired_keys)

    def stats(self) -> dict[str, Any]:
        """캐시 통계 (메모리 + 디스크)."""
        with self._lock:
            total = len(self._cache)
            expired = sum(1 for v in self._cache.values() if v.expired)
            intervals: dict[str, int] = {}
            for key in self._cache:
                _, interval = key.rsplit(":", 1)
                intervals[interval] = intervals.get(interval, 0) + 1

        disk_files = list(self._disk_dir.glob("*.parquet"))
        disk_size_mb = sum(f.stat().st_size for f in disk_files) / (1024 * 1024)

        total_requests = self._stats["hits_memory"] + self._stats["hits_disk"] + self._stats["misses"]

        return {
            "memory_entries": total,
            "memory_active": total - expired,
            "memory_expired": expired,
            "memory_by_interval": intervals,
            "disk_files": len(disk_files),
            "disk_size_mb": round(disk_size_mb, 2),
            "hits_memory": self._stats["hits_memory"],
            "hits_disk": self._stats["hits_disk"],
            "misses": self._stats["misses"],
            "fetches": self._stats["fetches"],
            "errors": self._stats["errors"],
            "disk_saves": self._stats["disk_saves"],
            "hit_rate": (
                round(
                    (self._stats["hits_memory"] + self._stats["hits_disk"])
                    / max(1, total_requests) * 100, 1,
                )
            ),
        }

    def disk_inventory(self) -> list[dict[str, Any]]:
        """디스크 캐시 목록 조회."""
        inventory = []
        for path in sorted(self._disk_dir.glob("*.parquet")):
            try:
                df = pd.read_parquet(path)
                inventory.append({
                    "file": path.name,
                    "bars": len(df),
                    "start": str(df.index.min()),
                    "end": str(df.index.max()),
                    "size_kb": round(path.stat().st_size / 1024, 1),
                })
            except Exception:
                inventory.append({"file": path.name, "bars": 0, "error": True})
        return inventory

    def shutdown(self) -> None:
        """Executor 종료."""
        self._executor.shutdown(wait=False)
