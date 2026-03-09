"""Upbit KRW 마켓 거래대금 순위 조회.

24시간 거래대금 기준 상위 N개 심볼을 반환.
USDT, 스테이블코인 등 분석 부적합 종목 자동 제외.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Upbit API 기본 URL (환경변수 UPBIT_API_URL로 오버라이드 가능)
import os as _os
UPBIT_API_URL = _os.environ.get("UPBIT_API_URL", "https://api.upbit.com/v1")

# 분석 부적합 종목 (스테이블, 래핑 토큰 등)
_EXCLUDE = {"KRW-USDT", "KRW-USDC", "KRW-DAI", "KRW-TUSD", "KRW-WBTC", "KRW-WETH"}

# 캐시 (TTL 5분)
_cache: dict[str, Any] = {"data": [], "ts": 0.0}
_CACHE_TTL = int(_os.environ.get("UPBIT_RANKING_CACHE_TTL", "300"))


def fetch_top_krw(count: int = 20, min_volume_krw: float = 5e8) -> list[dict]:
    """Upbit KRW 마켓 거래대금 상위 N개 조회.

    Args:
        count: 반환할 종목 수
        min_volume_krw: 최소 거래대금 (원) — 기본 5억원

    Returns:
        [{"market": "KRW-BTC", "symbol": "BTC/KRW", "price": 150000000,
          "volume_krw": 50000000000, "change_rate": 0.02}, ...]
    """
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"][:count]

    try:
        # 1. KRW 마켓 목록
        r = requests.get(
            f"{UPBIT_API_URL}/market/all",
            params={"isDetails": "true"},
            timeout=10,
        )
        r.raise_for_status()
        krw_markets = [m["market"] for m in r.json() if m["market"].startswith("KRW-")]

        # 2. 거래대금 조회 (50개씩 배치)
        all_tickers = []
        for i in range(0, len(krw_markets), 50):
            batch = krw_markets[i:i + 50]
            tr = requests.get(
                f"{UPBIT_API_URL}/ticker",
                params={"markets": ",".join(batch)},
                timeout=10,
            )
            tr.raise_for_status()
            all_tickers.extend(tr.json())
            if i + 50 < len(krw_markets):
                time.sleep(0.2)  # rate limit

        # 3. 필터 + 정렬
        filtered = [
            t for t in all_tickers
            if t["market"] not in _EXCLUDE
            and t.get("acc_trade_price_24h", 0) >= min_volume_krw
        ]
        sorted_tickers = sorted(
            filtered,
            key=lambda x: x.get("acc_trade_price_24h", 0),
            reverse=True,
        )

        results = []
        for t in sorted_tickers[:count]:
            market = t["market"]  # "KRW-BTC"
            base = market.split("-", 1)[1]
            results.append({
                "market": market,
                "symbol": f"{base}/KRW",
                "price": t.get("trade_price", 0),
                "volume_krw": t.get("acc_trade_price_24h", 0),
                "change_rate": t.get("signed_change_rate", 0),
            })

        _cache["data"] = results
        _cache["ts"] = now
        logger.info("Upbit 거래대금 상위 %d개 조회 완료", len(results))
        return results[:count]

    except Exception as e:
        logger.error("Upbit 순위 조회 실패: %s", e)
        if _cache["data"]:
            return _cache["data"][:count]
        return []


def get_top_symbols(count: int = 20) -> list[str]:
    """상위 N개 심볼명만 반환. (e.g. ["BTC/KRW", "ETH/KRW", ...])"""
    return [r["symbol"] for r in fetch_top_krw(count)]


def get_top_markets(count: int = 20) -> list[str]:
    """상위 N개 Upbit 마켓코드 반환. (e.g. ["KRW-BTC", "KRW-ETH", ...])"""
    return [r["market"] for r in fetch_top_krw(count)]


def format_ranking_table(count: int = 20) -> str:
    """디스코드용 순위 테이블 문자열."""
    items = fetch_top_krw(count)
    if not items:
        return "거래대금 순위 조회 실패"

    lines = ["**Upbit KRW 거래대금 상위 {}개**".format(len(items)), "```"]
    lines.append(f"{'#':>2} {'종목':<8} {'현재가':>12} {'거래대금':>10} {'등락':>7}")
    lines.append("-" * 50)

    for i, item in enumerate(items, 1):
        base = item["market"].split("-")[1]
        price = item["price"]
        vol = item["volume_krw"] / 1e8  # 억원
        chg = item["change_rate"] * 100
        sign = "+" if chg >= 0 else ""
        lines.append(f"{i:>2} {base:<8} {price:>12,.0f} {vol:>8,.0f}억 {sign}{chg:>5.1f}%")

    lines.append("```")
    return "\n".join(lines)
