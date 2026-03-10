"""OHLCVCacheManager 2계층 캐시 (메모리 + Parquet 디스크) 테스트.

State 정의:
  EMPTY         — 파일 없음
  FULL          — 요청 범위 완전 커버
  STALE         — 앞쪽만 있음 (뒤 부족, = PARTIAL_HEAD)
  PARTIAL_TAIL  — 뒤쪽만 있음 (앞 부족)
  PARTIAL_BOTH  — 앞뒤 모두 부족
  GAP           — 중간 구멍
  CORRUPTED     — 파일 깨짐
"""

import pandas as pd
import pytest

from engine.data.upbit_cache import OHLCVCacheManager


def _make_ohlcv(n: int = 10, start: str = "2026-01-01", freq: str = "h") -> pd.DataFrame:
    """테스트용 OHLCV DataFrame 생성."""
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame(
        {
            "open": range(100, 100 + n),
            "high": range(110, 110 + n),
            "low": range(90, 90 + n),
            "close": range(105, 105 + n),
            "volume": range(1000, 1000 + n),
        },
        index=idx,
    )


@pytest.fixture
def cache(tmp_path):
    return OHLCVCacheManager(cache_dir=tmp_path / "ohlcv")


# ── 메모리 캐시 ─────────────────────────────────────────────


class TestMemoryCache:
    def test_put_and_get(self, cache):
        df = _make_ohlcv()
        cache.put("KRW-BTC", "1h", df)
        result = cache.get("KRW-BTC", "1h")
        assert result is not None
        assert len(result) == 10

    def test_get_returns_copy(self, cache):
        df = _make_ohlcv()
        cache.put("KRW-BTC", "1h", df)
        r1 = cache.get("KRW-BTC", "1h")
        r2 = cache.get("KRW-BTC", "1h")
        assert r1 is not r2

    def test_miss_returns_none(self, cache):
        assert cache.get("KRW-BTC", "1h") is None

    def test_invalidate_single(self, cache):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        cache.put("KRW-BTC", "5m", _make_ohlcv())
        cache.invalidate("KRW-BTC", "1h")
        assert "KRW-BTC:1h" not in cache._cache
        assert "KRW-BTC:5m" in cache._cache

    def test_invalidate_all_intervals(self, cache):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        cache.put("KRW-BTC", "5m", _make_ohlcv())
        cache.put("KRW-ETH", "1h", _make_ohlcv())
        cache.invalidate("KRW-BTC")
        assert "KRW-BTC:1h" not in cache._cache
        assert "KRW-BTC:5m" not in cache._cache
        assert "KRW-ETH:1h" in cache._cache


# ── 디스크 캐시 ─────────────────────────────────────────────


class TestDiskCache:
    def test_put_creates_parquet(self, cache, tmp_path):
        df = _make_ohlcv()
        cache.put("KRW-BTC", "1h", df)
        parquet_path = tmp_path / "ohlcv" / "KRW_BTC_1h.parquet"
        assert parquet_path.exists()

    def test_disk_fallback_on_memory_miss(self, cache):
        df = _make_ohlcv()
        cache.put("KRW-BTC", "1h", df)
        cache._cache.clear()
        result = cache.get("KRW-BTC", "1h")
        assert result is not None
        assert len(result) == 10

    def test_disk_merge_dedup(self, cache):
        df1 = _make_ohlcv(5, "2026-01-01")
        df2 = _make_ohlcv(5, "2026-01-01 03:00")
        cache.put("KRW-BTC", "1h", df1)
        cache.put("KRW-BTC", "1h", df2)
        cache._cache.clear()
        result = cache.get("KRW-BTC", "1h")
        assert result is not None
        assert len(result) == 8  # 00:00~07:00 = 8봉

    def test_purge_disk(self, cache, tmp_path):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        cache.put("KRW-BTC", "5m", _make_ohlcv())
        deleted = cache.purge_disk("KRW-BTC", "1h")
        assert deleted == 1
        assert not (tmp_path / "ohlcv" / "KRW_BTC_1h.parquet").exists()
        assert (tmp_path / "ohlcv" / "KRW_BTC_5m.parquet").exists()

    def test_purge_disk_all(self, cache, tmp_path):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        cache.put("KRW-ETH", "1h", _make_ohlcv())
        deleted = cache.purge_disk()
        assert deleted == 2


# ── State 진단 ──────────────────────────────────────────────


class TestDiagnoseState:
    """diagnose_state() 7가지 상태 테스트."""

    def test_empty_no_file(self, cache):
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "EMPTY"
        assert len(d["gaps"]) == 1

    def test_full(self, cache):
        # 1/1 ~ 1/10 (240봉) 저장, 1/1~1/10 요청
        df = _make_ohlcv(240, "2026-01-01")
        cache.put("KRW-BTC", "1h", df)
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "FULL"
        assert len(d["gaps"]) == 0

    def test_stale(self, cache):
        # 1/1~1/5 저장, 1/1~1/10 요청 → 뒤쪽 부족
        df = _make_ohlcv(120, "2026-01-01")  # 5일치
        cache.put("KRW-BTC", "1h", df)
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "STALE"
        assert len(d["gaps"]) == 1

    def test_partial_tail(self, cache):
        # 1/5~1/10 저장, 1/1~1/10 요청 → 앞쪽 부족
        df = _make_ohlcv(144, "2026-01-05")  # 6일치 = 1/5~1/11 커버
        cache.put("KRW-BTC", "1h", df)
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "PARTIAL_TAIL"
        assert len(d["gaps"]) == 1

    def test_partial_both(self, cache):
        # 1/3~1/7 저장, 1/1~1/10 요청 → 앞뒤 모두 부족
        df = _make_ohlcv(96, "2026-01-03")  # 4일치
        cache.put("KRW-BTC", "1h", df)
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "PARTIAL_BOTH"
        assert len(d["gaps"]) == 2  # 앞 + 뒤

    def test_gap(self, cache):
        # 1/1~1/3 + 1/7~1/10 저장 (중간 4일 빠짐), 1/1~1/10 요청
        df1 = _make_ohlcv(72, "2026-01-01")   # 1/1 00:00 ~ 1/3 23:00
        df2 = _make_ohlcv(72, "2026-01-07")   # 1/7 00:00 ~ 1/9 23:00
        combined = pd.concat([df1, df2])
        cache.put("KRW-BTC", "1h", combined)
        # 요청 범위를 디스크 데이터 범위 내로 맞춤 → 순수 GAP만 테스트
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-09 23:00"),
        )
        assert d["state"] == "GAP"
        assert len(d["gaps"]) >= 1

    def test_corrupted(self, cache, tmp_path):
        # 깨진 parquet 파일
        path = tmp_path / "ohlcv" / "KRW_BTC_1h.parquet"
        path.write_text("not a parquet file")
        d = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d["state"] == "CORRUPTED"


# ── GAP 감지 ────────────────────────────────────────────────


class TestGapDetection:
    def test_no_gap_continuous(self, cache):
        df = _make_ohlcv(24, "2026-01-01")  # 연속 24봉
        gaps = cache._detect_gaps(
            df, "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"),
        )
        assert gaps == []

    def test_single_gap(self, cache):
        # 0~5시 + 12~17시 (6~11시 빠짐)
        df1 = _make_ohlcv(6, "2026-01-01 00:00")
        df2 = _make_ohlcv(6, "2026-01-01 12:00")
        df = pd.concat([df1, df2])
        gaps = cache._detect_gaps(
            df, "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == pd.Timestamp("2026-01-01 05:00")
        assert gaps[0][1] == pd.Timestamp("2026-01-01 12:00")

    def test_multiple_gaps(self, cache):
        # 0~2시 + 6~8시 + 14~16시
        df1 = _make_ohlcv(3, "2026-01-01 00:00")
        df2 = _make_ohlcv(3, "2026-01-01 06:00")
        df3 = _make_ohlcv(3, "2026-01-01 14:00")
        df = pd.concat([df1, df2, df3])
        gaps = cache._detect_gaps(
            df, "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02"),
        )
        assert len(gaps) == 2

    def test_gap_5m_interval(self, cache):
        # 5분봉: 00:00~00:25 + 01:00~01:25 (30분 GAP)
        df1 = _make_ohlcv(6, "2026-01-01 00:00", freq="5min")
        df2 = _make_ohlcv(6, "2026-01-01 01:00", freq="5min")
        df = pd.concat([df1, df2])
        gaps = cache._detect_gaps(
            df, "5m",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01 02:00"),
        )
        assert len(gaps) == 1


# ── 크로스 타임프레임 ───────────────────────────────────────


class TestCrossTimeframe:
    def test_tf_independent_storage(self, cache):
        """각 TF는 독립 파일로 저장."""
        cache.put("KRW-BTC", "1h", _make_ohlcv(24, "2026-01-01"))
        cache.put("KRW-BTC", "5m", _make_ohlcv(100, "2026-01-01", freq="5min"))
        inv = cache.disk_inventory()
        assert len(inv) == 2
        names = {item["file"] for item in inv}
        assert "KRW_BTC_1h.parquet" in names
        assert "KRW_BTC_5m.parquet" in names

    def test_tf_range_mismatch(self, cache):
        """TF별 다른 범위 → 각각 독립 진단."""
        cache.put("KRW-BTC", "1h", _make_ohlcv(240, "2026-01-01"))  # 10일
        cache.put("KRW-BTC", "5m", _make_ohlcv(864, "2026-01-08", freq="5min"))  # 8일부터 3일치

        d_1h = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        d_5m = cache.diagnose_state(
            "KRW-BTC", "5m",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-10"),
        )
        assert d_1h["state"] == "FULL"
        assert d_5m["state"] == "PARTIAL_TAIL"  # 1~7일 부족

    def test_tf_one_exists_other_empty(self, cache):
        """1h 있고 5m 없음."""
        cache.put("KRW-BTC", "1h", _make_ohlcv(24))
        d_1h = cache.diagnose_state(
            "KRW-BTC", "1h",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01 23:00"),
        )
        d_5m = cache.diagnose_state(
            "KRW-BTC", "5m",
            pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01 23:00"),
        )
        assert d_1h["state"] == "FULL"
        assert d_5m["state"] == "EMPTY"


# ── 통계 ────────────────────────────────────────────────────


class TestStats:
    def test_stats_include_disk(self, cache):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        s = cache.stats()
        assert s["memory_entries"] == 1
        assert s["disk_files"] == 1
        assert s["disk_size_mb"] >= 0
        assert s["disk_saves"] == 1

    def test_hit_rate(self, cache):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        cache.get("KRW-BTC", "1h")   # memory hit
        cache._cache.clear()
        cache.get("KRW-BTC", "1h")   # disk hit
        cache.get("KRW-ETH", "1h")   # miss
        s = cache.stats()
        assert s["hits_memory"] == 1
        assert s["hits_disk"] == 1
        assert s["misses"] == 1

    def test_disk_inventory(self, cache):
        cache.put("KRW-BTC", "1h", _make_ohlcv())
        inv = cache.disk_inventory()
        assert len(inv) == 1
        assert inv[0]["bars"] == 10
        assert "start" in inv[0]
        assert "end" in inv[0]


# ── 유틸리티 ────────────────────────────────────────────────


class TestUtility:
    def test_interval_to_timedelta(self, cache):
        assert cache._interval_to_timedelta("1h") == pd.Timedelta(hours=1)
        assert cache._interval_to_timedelta("5m") == pd.Timedelta(minutes=5)
        assert cache._interval_to_timedelta("1d") == pd.Timedelta(days=1)

    def test_to_naive_with_tz(self, cache):
        ts = pd.Timestamp("2026-01-01", tz="Asia/Seoul")
        result = cache._to_naive(ts)
        assert result.tz is None

    def test_to_naive_without_tz(self, cache):
        ts = pd.Timestamp("2026-01-01")
        result = cache._to_naive(ts)
        assert result.tz is None
        assert result == ts
