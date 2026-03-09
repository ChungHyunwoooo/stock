"""벤치마크 구간 정의 — 레짐별 복수 구간, 거래소별 심볼 매핑.

BTC 기준 실제 시장 구간 (2017-08 ~ 2025-03).
구간은 최대한 길게 잡되, 레짐 방향성이 명확한 구간만 포함.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkPeriod:
    name: str
    regime: str  # "BULL" | "BEAR" | "RANGE"
    start: str
    end: str
    description: str


# ---------------------------------------------------------------------------
# 벤치마크 구간 (최대한 길게)
# ---------------------------------------------------------------------------

BENCHMARK_PERIODS: list[BenchmarkPeriod] = [
    # === BULL (상승장) ===
    BenchmarkPeriod("BULL_2017", "BULL",
                    "2017-10-01", "2018-01-10",
                    "ICO 버블 랠리, BTC 4K→17K (+325%), 3.3개월"),
    BenchmarkPeriod("BULL_2019", "BULL",
                    "2019-02-01", "2019-06-30",
                    "크립토 겨울→회복, BTC 3.4K→13.8K (+306%), 5개월"),
    BenchmarkPeriod("BULL_2020_2021", "BULL",
                    "2020-07-01", "2021-04-15",
                    "DeFi+기관+코인베이스, BTC 9K→64K (+611%), 9.5개월"),
    BenchmarkPeriod("BULL_2021_Q4", "BULL",
                    "2021-07-20", "2021-11-10",
                    "엘살바도르+NFT, BTC 29K→69K (+138%), 3.7개월"),
    BenchmarkPeriod("BULL_2023", "BULL",
                    "2023-01-01", "2023-04-15",
                    "FTX 후 회복, BTC 16K→31K (+94%), 3.5개월"),
    BenchmarkPeriod("BULL_2023_2024", "BULL",
                    "2023-10-01", "2024-03-31",
                    "ETF 기대→승인→신고가, BTC 26K→71K (+173%), 6개월"),
    BenchmarkPeriod("BULL_2024_Q4", "BULL",
                    "2024-10-01", "2025-01-15",
                    "미 대선 후 랠리, BTC 60K→106K (+77%), 3.5개월"),

    # === BEAR (하락장) ===
    BenchmarkPeriod("BEAR_2018", "BEAR",
                    "2018-01-15", "2018-12-15",
                    "ICO 버블 붕괴, BTC 14K→3.2K (-77%), 11개월"),
    BenchmarkPeriod("BEAR_2019_2020", "BEAR",
                    "2019-07-01", "2020-03-15",
                    "되돌림+코로나, BTC 13K→5K (-62%), 8.5개월"),
    BenchmarkPeriod("BEAR_2021_MAY", "BEAR",
                    "2021-04-15", "2021-07-20",
                    "중국 금지+머스크, BTC 64K→29K (-55%), 3개월"),
    BenchmarkPeriod("BEAR_2022", "BEAR",
                    "2022-01-01", "2022-12-31",
                    "LUNA+3AC+FTX+금리, BTC 47K→16K (-66%), 12개월"),
    BenchmarkPeriod("BEAR_2024_SUMMER", "BEAR",
                    "2024-06-01", "2024-09-15",
                    "ETF 매도+여름 조정, BTC 72K→53K (-26%), 3.5개월"),

    # === RANGE (횡보장) ===
    BenchmarkPeriod("RANGE_2019_Q4", "RANGE",
                    "2019-10-01", "2020-02-01",
                    "하락 후 바닥 횡보, BTC 7.5K~10.5K, 4개월"),
    BenchmarkPeriod("RANGE_2020_SPRING", "RANGE",
                    "2020-03-15", "2020-07-01",
                    "코로나 후 회복 횡보, BTC 5K~9.5K, 3.5개월"),
    BenchmarkPeriod("RANGE_2022_SUMMER", "RANGE",
                    "2022-07-01", "2022-10-01",
                    "LUNA 후 바닥 횡보, BTC 19K~24K, 3개월"),
    BenchmarkPeriod("RANGE_2023_SUMMER", "RANGE",
                    "2023-05-01", "2023-09-30",
                    "봄 랠리 후 횡보, BTC 25K~31K, 5개월"),
    BenchmarkPeriod("RANGE_2024_SPRING", "RANGE",
                    "2024-04-01", "2024-06-01",
                    "ETF 후 조정 횡보, BTC 59K~72K, 2개월"),
    BenchmarkPeriod("RANGE_2025_Q1", "RANGE",
                    "2025-01-15", "2025-03-01",
                    "신고가 후 횡보, BTC 92K~106K, 1.5개월"),
]


# ---------------------------------------------------------------------------
# 거래소별 심볼 매핑
# ---------------------------------------------------------------------------

EXCHANGE_SYMBOLS: dict[str, list[str]] = {
    "binance": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT",
    ],
    "okx": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT",
    ],
    "bybit": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT",
    ],
    "upbit": [
        "BTC/KRW", "ETH/KRW", "SOL/KRW", "DOGE/KRW", "XRP/KRW",
    ],
}

# 거래소별 데이터 시작일 (실측 기반)
EXCHANGE_DATA_START: dict[str, str] = {
    "binance": "2017-08-17",
    "okx": "2020-01-01",
    "bybit": "2021-07-05",
    "upbit": "2023-06-01",  # ccxt 페이징 미지원, pyupbit 필요
}


def get_periods_by_regime(regime: str) -> list[BenchmarkPeriod]:
    return [p for p in BENCHMARK_PERIODS if p.regime == regime]


def get_all_periods() -> list[BenchmarkPeriod]:
    return BENCHMARK_PERIODS


def get_periods_for_exchange(exchange: str) -> list[BenchmarkPeriod]:
    """거래소 데이터 시작일 이후 구간만 반환."""
    data_start = EXCHANGE_DATA_START.get(exchange, "2017-08-01")
    return [p for p in BENCHMARK_PERIODS if p.start >= data_start]


def get_symbols_for_exchange(exchange: str) -> list[str]:
    return EXCHANGE_SYMBOLS.get(exchange, EXCHANGE_SYMBOLS["binance"])
