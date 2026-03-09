"""Upbit WebSocket Manager — 실시간 ticker + 5분봉 마감 감지.

pyupbit WebSocket을 래핑하여:
- 실시간 가격 수신
- 5분 캔들 경계 감지 (서버 타임스탬프 기반)
- 마감 시 콜백으로 스캔 트리거

별도 daemon thread에서 WebSocket 메시지를 소비하고,
asyncio 이벤트로 메인 루프에 알림.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


class CandleBoundaryDetector:
    """5분 캔들 경계 감지기.

    서버 타임스탬프 기반으로 5분 경계(00, 05, 10, ..., 55분)를
    넘어가는 순간을 감지한다.
    """

    def __init__(self, interval_minutes: int = 5) -> None:
        self._interval = interval_minutes * 60  # seconds
        self._last_boundary: int = 0  # last boundary epoch (floored)

    def _floor_to_boundary(self, epoch: float) -> int:
        """Epoch를 가장 가까운 과거 경계로 내림."""
        return int(epoch // self._interval) * self._interval

    def check(self, server_timestamp_ms: int | float) -> bool:
        """새로운 캔들 경계를 넘었는지 확인.

        Returns True if we crossed into a new candle boundary.
        """
        epoch = server_timestamp_ms / 1000.0 if server_timestamp_ms > 1e12 else server_timestamp_ms
        current_boundary = self._floor_to_boundary(epoch)

        if self._last_boundary == 0:
            # First tick — initialize, don't trigger
            self._last_boundary = current_boundary
            return False

        if current_boundary > self._last_boundary:
            self._last_boundary = current_boundary
            return True

        return False

    @property
    def last_boundary(self) -> int:
        return self._last_boundary


class UpbitWebSocketManager:
    """Upbit WebSocket 매니저.

    실시간 ticker 데이터를 수신하고, 5분봉 마감 시 콜백을 호출한다.
    pyupbit.WebSocketManager를 래핑하며 별도 daemon thread에서 동작.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        on_candle_close: Callable[[], None] | None = None,
        candle_interval_minutes: int = 5,
    ) -> None:
        self._symbols = symbols or []
        self._on_candle_close = on_candle_close
        self._detector = CandleBoundaryDetector(candle_interval_minutes)
        self._prices: dict[str, float] = {}  # symbol -> latest price
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._last_tick_time: float = 0.0
        self._tick_count: int = 0
        self._reconnect_count: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    def get_latest_price(self, symbol: str) -> float | None:
        """실시간 최신가 조회."""
        return self._prices.get(symbol)

    def get_all_prices(self) -> dict[str, float]:
        """모든 심볼의 최신가 조회."""
        return dict(self._prices)

    def update_symbols(self, symbols: list[str]) -> None:
        """구독 심볼 업데이트. 재연결 필요."""
        self._symbols = symbols
        if self._running:
            self._restart_ws()

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """WebSocket 수신 시작 (daemon thread)."""
        if self._running:
            return

        self._loop = loop
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="upbit-ws")
        self._thread.start()
        logger.info("Upbit WebSocket manager started (%d symbols)", len(self._symbols))

    def stop(self) -> None:
        """WebSocket 수신 정지."""
        self._running = False
        self._connected = False
        if self._ws is not None:
            try:
                self._ws.terminate()
            except Exception:
                pass
            self._ws = None
        logger.info("Upbit WebSocket manager stopped")

    def _restart_ws(self) -> None:
        """WebSocket 재연결."""
        if self._ws is not None:
            try:
                self._ws.terminate()
            except Exception:
                pass
            self._ws = None
        self._connected = False

    def _run(self) -> None:
        """WebSocket 수신 메인 루프 (thread)."""
        import pyupbit

        while self._running:
            try:
                if not self._symbols:
                    time.sleep(1)
                    continue

                # pyupbit WebSocketManager: type="ticker" for realtime prices
                self._ws = pyupbit.WebSocketManager(
                    type="ticker",
                    codes=self._symbols,
                )
                self._connected = True
                logger.info("WebSocket connected (%d symbols)", len(self._symbols))

                while self._running:
                    data = self._ws.get()
                    if data is None:
                        time.sleep(0.01)
                        continue

                    if isinstance(data, bytes):
                        data = json.loads(data.decode("utf-8"))

                    if not isinstance(data, dict):
                        continue

                    self._process_tick(data)

            except Exception as e:
                self._connected = False
                if self._running:
                    self._reconnect_count += 1
                    logger.warning(
                        "WebSocket error (reconnect #%d): %s",
                        self._reconnect_count, e,
                    )
                    time.sleep(min(5 * self._reconnect_count, 30))  # Exponential backoff capped at 30s

        self._connected = False

    def _process_tick(self, data: dict) -> None:
        """단일 ticker 메시지 처리."""
        code = data.get("code") or data.get("cd")
        trade_price = data.get("trade_price") or data.get("tp")
        timestamp = data.get("trade_timestamp") or data.get("ttms") or data.get("tms")

        if not code or trade_price is None:
            return

        self._prices[code] = float(trade_price)
        self._tick_count += 1
        self._last_tick_time = time.time()

        # Check 5-minute candle boundary
        if timestamp and self._detector.check(timestamp):
            logger.info("5-min candle boundary detected at %s", timestamp)
            self._fire_candle_close()

    def _fire_candle_close(self) -> None:
        """5분봉 마감 이벤트 발생."""
        if self._on_candle_close is None:
            return

        if self._loop is not None and self._loop.is_running():
            # Schedule callback on the asyncio event loop
            self._loop.call_soon_threadsafe(self._on_candle_close)
        else:
            # Direct call (fallback)
            try:
                self._on_candle_close()
            except Exception as e:
                logger.error("Candle close callback error: %s", e)

    def status(self) -> dict:
        """WebSocket 상태 정보."""
        return {
            "connected": self._connected,
            "symbols_count": len(self._symbols),
            "tick_count": self._tick_count,
            "reconnect_count": self._reconnect_count,
            "last_tick_age_sec": round(time.time() - self._last_tick_time, 1) if self._last_tick_time else None,
            "prices_cached": len(self._prices),
        }
