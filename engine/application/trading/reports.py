
from dataclasses import dataclass, field

from engine.core.models import TradingSignal

@dataclass(frozen=True, slots=True)
class AnalysisReport:
    symbol: str
    exchange: str
    timeframe: str
    scanned_at: str
    last_price: float
    price_change_pct: float
    range_pct: float
    volume_ratio: float
    trend_bias: str
    bars: int
    high: float
    low: float
    signal_count: int
    notes: list[str] = field(default_factory=list)
    signals: list[TradingSignal] = field(default_factory=list)
