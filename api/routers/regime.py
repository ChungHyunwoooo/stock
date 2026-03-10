"""Regime API — crypto macro regime status and sector rankings."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/regime", tags=["regime"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class BtcScoreDetailResponse(BaseModel):
    ema50_above: bool
    ema200_above: bool
    golden_cross: bool
    rsi_bullish: bool
    macd_bullish: bool
    score: int

class RegimeResponse(BaseModel):
    regime: str
    btc_trend: str
    dominance_dir: str
    exposure: float
    btc_score: int
    btc_score_detail: BtcScoreDetailResponse
    btc_price: float
    btc_return_20d: float
    alt_basket_return_20d: float
    date: str

class RegimeHistoryItem(BaseModel):
    date: str
    regime: str
    exposure: float
    btc_trend: str
    dominance_dir: str
    btc_score: int

class RegimeHistoryResponse(BaseModel):
    items: list[RegimeHistoryItem]
    total: int

class SymbolStrengthResponse(BaseModel):
    symbol: str
    return_pct: float
    sector: str

class SectorRankResponse(BaseModel):
    sector: str
    avg_return_pct: float
    rank: int
    symbols: list[SymbolStrengthResponse]

class SectorsResponse(BaseModel):
    rankings: list[SectorRankResponse]
    top_symbols: list[SymbolStrengthResponse]

class OHLCVBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

class CustomIndicatorBar(BaseModel):
    time: str
    watermelon_shell: float
    watermelon_melon: float
    staircase: float
    proximity1: bool
    proximity2: bool

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/crypto", response_model=RegimeResponse)
def get_current_regime(
    date: str | None = Query(None, description="Evaluation date YYYY-MM-DD (default: today)"),
) -> RegimeResponse:
    """Get the current crypto macro regime state."""
    from engine.analysis.crypto_regime import CryptoRegimeEngine

    engine = CryptoRegimeEngine()
    state = engine.evaluate(date)

    return RegimeResponse(
        regime=state.regime.value,
        btc_trend=state.btc_trend.value,
        dominance_dir=state.dominance_dir.value,
        exposure=state.exposure,
        btc_score=state.btc_score,
        btc_score_detail=BtcScoreDetailResponse(
            ema50_above=state.btc_score_detail.ema50_above,
            ema200_above=state.btc_score_detail.ema200_above,
            golden_cross=state.btc_score_detail.golden_cross,
            rsi_bullish=state.btc_score_detail.rsi_bullish,
            macd_bullish=state.btc_score_detail.macd_bullish,
            score=state.btc_score_detail.score,
        ),
        btc_price=state.btc_price,
        btc_return_20d=state.btc_return_20d,
        alt_basket_return_20d=state.alt_basket_return_20d,
        date=state.date,
    )

@router.get("/crypto/history", response_model=RegimeHistoryResponse)
def get_regime_history(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> RegimeHistoryResponse:
    """Get regime history for a date range (for charting)."""
    from engine.analysis.crypto_regime import CryptoRegimeEngine

    engine = CryptoRegimeEngine()
    df = engine.evaluate_series(start, end)

    items = [
        RegimeHistoryItem(
            date=row["date"],
            regime=row["regime"],
            exposure=row["exposure"],
            btc_trend=row["btc_trend"],
            dominance_dir=row["dominance_dir"],
            btc_score=row["btc_score"],
        )
        for _, row in df.iterrows()
    ]

    return RegimeHistoryResponse(items=items, total=len(items))

@router.get("/sectors", response_model=SectorsResponse)
def get_sector_rankings(
    date: str | None = Query(None, description="Evaluation date YYYY-MM-DD (default: today)"),
    period: int = Query(20, ge=5, le=60, description="Lookback period in days"),
    top_n_sectors: int = Query(2, ge=1, le=6),
    top_n_per_sector: int = Query(3, ge=1, le=10),
) -> SectorsResponse:
    """Get sector rankings and top symbols by relative strength."""
    from engine.analysis.sector_regime import CryptoSectorRanker

    ranker = CryptoSectorRanker()
    rankings = ranker.rank_sectors(date, period)
    top_symbols = ranker.get_top_symbols(date, period, top_n_sectors, top_n_per_sector)

    return SectorsResponse(
        rankings=[
            SectorRankResponse(
                sector=r.sector,
                avg_return_pct=r.avg_return_pct,
                rank=r.rank,
                symbols=[
                    SymbolStrengthResponse(
                        symbol=s.symbol,
                        return_pct=s.return_pct,
                        sector=s.sector,
                    )
                    for s in r.symbols
                ],
            )
            for r in rankings
        ],
        top_symbols=[
            SymbolStrengthResponse(
                symbol=s.symbol,
                return_pct=s.return_pct,
                sector=s.sector,
            )
            for s in top_symbols
        ],
    )

@router.get("/chart", response_model=list[OHLCVBar])
def get_symbol_chart(
    symbol: str = Query(..., description="Symbol e.g. ETH/USDT"),
    days: int = Query(90, ge=1, le=730, description="Lookback days"),
    timeframe: str = Query("1d", description="Candle timeframe: 1m,5m,15m,30m,1h,4h,1d,1w"),
) -> list[OHLCVBar]:
    """Get OHLCV candlestick data for a crypto symbol."""
    import pandas as pd
    from engine.data.provider_crypto import CryptoProvider

    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    start = (pd.Timestamp(end) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    provider = CryptoProvider()
    df = provider.fetch_ohlcv(symbol, start, end, timeframe)

    is_intraday = timeframe not in ("1d", "1w")

    return [
        OHLCVBar(
            time=str(idx)[:19] if is_intraday else str(idx)[:10],
            open=round(float(row["open"]), 4),
            high=round(float(row["high"]), 4),
            low=round(float(row["low"]), 4),
            close=round(float(row["close"]), 4),
            volume=round(float(row["volume"]), 2),
        )
        for idx, row in df.iterrows()
    ]

@router.get("/indicators", response_model=list[CustomIndicatorBar])
def get_custom_indicators(
    symbol: str = Query(..., description="Symbol e.g. ETH/USDT"),
    days: int = Query(500, ge=100, le=730, description="Lookback days (needs long history for EMA448)"),
    show_days: int = Query(120, ge=30, le=365, description="Number of recent bars to return"),
) -> list[CustomIndicatorBar]:
    """Compute watermelon & staircase indicator time series."""
    import pandas as pd
    from engine.data.provider_crypto import CryptoProvider
    from engine.indicators.custom import watermelon_indicator, staircase_indicator

    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    start = (pd.Timestamp(end) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    provider = CryptoProvider()
    df = provider.fetch_ohlcv(symbol, start, end, "1d")

    if len(df) < 450:
        return []

    wm = watermelon_indicator(df)
    sc = staircase_indicator(df)

    # Return only the last show_days bars
    tail = df.iloc[-show_days:]

    return [
        CustomIndicatorBar(
            time=str(idx)[:10],
            watermelon_shell=round(float(wm["shell"].loc[idx]), 4),
            watermelon_melon=round(float(wm["melon"].loc[idx]), 4),
            staircase=round(float(sc["staircase"].loc[idx]), 4),
            proximity1=float(sc["proximity1"].loc[idx]) > 0,
            proximity2=float(sc["proximity2"].loc[idx]) > 0,
        )
        for idx in tail.index
    ]
