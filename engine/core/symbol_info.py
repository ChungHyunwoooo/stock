"""심볼 정보 캐시 — 바이낸스 거래소 정밀도, 제한값 관리.

모든 봇/대시보드가 이 모듈을 통해 심볼 정밀도에 접근.
"1000SATS 금액 변경" → 이 모듈이 자동 처리.

사용:
    from engine.core.symbol_info import get_symbol_info, round_price, round_quantity

    info = get_symbol_info("BTC/USDT")
    price = round_price("BTC/USDT", 71509.537)  # → 71509.5
    qty = round_quantity("BTC/USDT", 0.12345)    # → 0.123
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)

CACHE_PATH = Path("config/symbol_precision_cache.json")
CACHE_TTL_SEC = 3600 * 12  # 12시간


@dataclass(slots=True, frozen=True)
class SymbolInfo:
    """심볼 거래 정보."""
    symbol: str
    price_precision: float    # 가격 최소 단위 (tick size)
    amount_precision: float   # 수량 최소 단위 (step size)
    min_notional: float       # 최소 주문 금액 (USDT)
    min_amount: float         # 최소 수량


class SymbolInfoCache:
    """바이낸스 심볼 정보 캐시 (싱글톤)."""

    _instance: ClassVar[SymbolInfoCache | None] = None
    _cache: dict[str, SymbolInfo]
    _loaded_at: float

    def __init__(self) -> None:
        self._cache = {}
        self._loaded_at = 0.0

    @classmethod
    def get_instance(cls) -> SymbolInfoCache:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_stale(self) -> bool:
        return time.time() - self._loaded_at > CACHE_TTL_SEC

    def _load_from_file(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        try:
            data = json.loads(CACHE_PATH.read_text())
            ts = data.get("cached_at", 0)
            if time.time() - ts > CACHE_TTL_SEC:
                return False
            for sym, info in data.get("symbols", {}).items():
                self._cache[sym] = SymbolInfo(
                    symbol=sym,
                    price_precision=info["price_precision"],
                    amount_precision=info["amount_precision"],
                    min_notional=info.get("min_notional", 5.0),
                    min_amount=info.get("min_amount", 0.001),
                )
            self._loaded_at = ts
            logger.debug("심볼 캐시 파일 로드: %d개", len(self._cache))
            return True
        except Exception as e:
            logger.warning("심볼 캐시 파일 로드 실패: %s", e)
            return False

    def _save_to_file(self) -> None:
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "cached_at": time.time(),
                "symbols": {
                    sym: {
                        "price_precision": info.price_precision,
                        "amount_precision": info.amount_precision,
                        "min_notional": info.min_notional,
                        "min_amount": info.min_amount,
                    }
                    for sym, info in self._cache.items()
                },
            }
            CACHE_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("심볼 캐시 저장 실패: %s", e)

    def _fetch_from_exchange(self) -> None:
        """바이낸스에서 전체 심볼 정보 로드."""
        try:
            from engine.data.provider_crypto import _build_futures_exchange
            ex = _build_futures_exchange("binance")
            markets = ex.load_markets()

            for sym, m in markets.items():
                if not m.get("swap") or m.get("quote") != "USDT":
                    continue
                prec = m.get("precision", {})
                limits = m.get("limits", {})

                price_prec = prec.get("price", 0.01)
                amount_prec = prec.get("amount", 0.001)
                min_notional = limits.get("cost", {}).get("min", 5.0) or 5.0
                min_amount = limits.get("amount", {}).get("min", 0.001) or 0.001

                # spot 심볼도 동일 정밀도 적용
                base_sym = sym.replace(":USDT", "")
                self._cache[sym] = SymbolInfo(
                    symbol=sym,
                    price_precision=float(price_prec),
                    amount_precision=float(amount_prec),
                    min_notional=float(min_notional),
                    min_amount=float(min_amount),
                )
                self._cache[base_sym] = self._cache[sym]

            self._loaded_at = time.time()
            self._save_to_file()
            logger.info("심볼 정보 갱신: %d개", len(self._cache))
        except Exception as e:
            logger.error("심볼 정보 조회 실패: %s", e)

    def ensure_loaded(self) -> None:
        """필요 시 캐시 로드/갱신."""
        if self._cache and not self._is_stale():
            return
        if not self._load_from_file():
            self._fetch_from_exchange()

    def get(self, symbol: str) -> SymbolInfo | None:
        """심볼 정보 조회."""
        self.ensure_loaded()
        return self._cache.get(symbol)


# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------

def get_symbol_info(symbol: str) -> SymbolInfo | None:
    """심볼 정보 조회."""
    return SymbolInfoCache.get_instance().get(symbol)


def _precision_decimals(precision: float) -> int:
    """정밀도 → 소수점 자릿수 변환. 0.001 → 3, 0.01 → 2, 1e-07 → 7."""
    if precision <= 0 or precision >= 1:
        return 0
    return max(0, -int(math.floor(math.log10(precision))))


def round_price(symbol: str, price: float) -> float:
    """심볼의 가격 정밀도에 맞게 반올림."""
    info = get_symbol_info(symbol)
    if info is None:
        return price  # 정보 없으면 원본 반환
    decimals = _precision_decimals(info.price_precision)
    return round(price, decimals)


def round_quantity(symbol: str, quantity: float) -> float:
    """심볼의 수량 정밀도에 맞게 버림 (올림하면 잔고 초과 가능)."""
    info = get_symbol_info(symbol)
    if info is None:
        return quantity
    if info.amount_precision >= 1:
        return math.floor(quantity)
    decimals = _precision_decimals(info.amount_precision)
    factor = 10 ** decimals
    return math.floor(quantity * factor) / factor


def format_price(symbol: str, price: float) -> str:
    """심볼의 가격을 표시용 문자열로 포맷."""
    info = get_symbol_info(symbol)
    if info is None:
        return f"{price}"
    decimals = _precision_decimals(info.price_precision)
    return f"{price:.{decimals}f}"
