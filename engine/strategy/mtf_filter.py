"""MTF(Multi-Timeframe) confirmation gate.

상위 타임프레임 EMA 방향과 단기 신호 방향을 비교하여
추세 반대 진입을 필터링한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from engine.config_path import config_file
from engine.core.models import TradeSide

if TYPE_CHECKING:
    from engine.data.provider_base import DataProvider

logger = logging.getLogger(__name__)

_TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "1w": 10080,
}


@dataclass
class MTFConfig:
    """MTF 필터 설정."""

    enabled: bool = False
    higher_timeframe: str = "4h"
    ema_period: int = 20
    lookback_bars: int = 50

    @classmethod
    def from_config(cls) -> MTFConfig:
        """config/trading.json의 mtf_filter 키에서 로드. 파일 없으면 기본값."""
        path = config_file("trading.json")
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            mtf = data.get("mtf_filter", {})
            valid_keys = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in mtf.items() if k in valid_keys})
        except Exception:
            logger.warning("Failed to load MTF config, using defaults", exc_info=True)
            return cls()


def _timeframe_to_minutes(tf: str) -> int:
    """타임프레임 문자열을 분 단위로 변환."""
    if tf in _TF_MINUTES:
        return _TF_MINUTES[tf]
    raise ValueError(f"Unknown timeframe: {tf}")


class MTFConfirmationGate:
    """상위 타임프레임 방향 확인 게이트."""

    def __init__(
        self,
        config: MTFConfig,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.config = config
        self.data_provider = data_provider

    def check_alignment(
        self,
        symbol: str,
        side: TradeSide,
        signal_timeframe: str,
    ) -> tuple[bool, str]:
        """신호 방향이 상위 TF 추세와 정렬되는지 확인.

        Returns:
            (aligned, reason) - aligned=True면 통과, False면 차단.
        """
        if not self.config.enabled:
            return True, "MTF filter disabled"

        if self.data_provider is None:
            return True, "No data provider"

        # 신호 TF >= 상위 TF면 MTF 불필요
        try:
            signal_min = _timeframe_to_minutes(signal_timeframe)
            higher_min = _timeframe_to_minutes(self.config.higher_timeframe)
        except ValueError:
            return True, f"Unknown timeframe, allowing signal"

        if signal_min >= higher_min:
            return True, "Signal TF >= Higher TF"

        # 상위 TF 데이터 조회
        try:
            now = datetime.now(timezone.utc)
            lookback_minutes = self.config.lookback_bars * higher_min
            start = now - timedelta(minutes=lookback_minutes)
            df = self.data_provider.fetch_ohlcv(
                symbol,
                start.strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
                self.config.higher_timeframe,
            )
        except Exception:
            logger.warning("MTF data fetch failed for %s, allowing signal", symbol, exc_info=True)
            return True, "Data fetch failed, allowing signal"

        if df is None or df.empty or len(df) < self.config.ema_period:
            return True, "Insufficient data for MTF filter"

        # EMA 계산 (pandas ewm 직접 사용 -- talib 의존 회피)
        close = df["close"]
        ema_values = close.ewm(span=self.config.ema_period, adjust=False).mean()
        current_price = float(close.iloc[-1])
        current_ema = float(ema_values.iloc[-1])

        # 방향 판단
        if current_price > current_ema:
            higher_tf_direction = TradeSide.long
        else:
            higher_tf_direction = TradeSide.short

        htf = self.config.higher_timeframe
        if side == higher_tf_direction:
            return True, f"Aligned with {htf} trend"
        return False, f"Against {htf} trend (EMA direction: {higher_tf_direction.value})"
