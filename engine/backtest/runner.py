
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from engine.backtest.metrics import compute_max_drawdown, compute_sharpe_ratio, compute_total_return
from engine.data.provider_base import get_provider
from engine.schema import StrategyDefinition
from engine.strategy.strategy_evaluator import StrategyEngine

@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float

@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: float | None
    max_drawdown: float | None
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_result_json(self) -> str:
        trades_data = [
            {
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
            }
            for t in self.trades
        ]
        return json.dumps(
            {
                "initial_capital": self.initial_capital,
                "final_capital": self.final_capital,
                "total_return": self.total_return,
                "sharpe_ratio": self.sharpe_ratio,
                "max_drawdown": self.max_drawdown,
                "num_trades": len(self.trades),
                "trades": trades_data,
            }
        )

class BacktestRunner:
    """Runs a strategy definition against historical OHLCV data."""

    def __init__(self) -> None:
        self._strategy_engine = StrategyEngine()

    @staticmethod
    def _infer_market(symbol: str, strategy: StrategyDefinition) -> str:
        """Infer market type from symbol format, falling back to strategy.markets[0]."""
        if "/" in symbol:
            return "crypto_spot"
        return strategy.markets[0].value if hasattr(strategy.markets[0], "value") else strategy.markets[0]

    def run(
        self,
        strategy: StrategyDefinition,
        symbol: str,
        start: str,
        end: str,
        timeframe: str = "1d",
        initial_capital: float = 10_000.0,
        market: str | None = None,
        regime_enabled: bool = False,
    ) -> BacktestResult:
        """Fetch data, generate signals, simulate trades, compute metrics.

        Args:
            strategy: Full strategy definition.
            symbol: Ticker symbol (e.g. "005930" for Samsung, "BTC/USDT").
            start: Start date "YYYY-MM-DD".
            end: End date "YYYY-MM-DD".
            timeframe: Bar size (e.g. "1d", "1h").
            initial_capital: Starting portfolio value.
            market: Explicit market type override. Auto-detected if None.
            regime_enabled: When True, apply crypto regime exposure overlay.

        Returns:
            BacktestResult with trades and performance metrics.
        """
        market_type = market or self._infer_market(symbol, strategy)
        provider = get_provider(market_type)
        df = provider.fetch_ohlcv(symbol, start, end, timeframe)

        # Regime exposure overlay
        exposure_series = None
        if regime_enabled and market_type in ("crypto_spot", "crypto_futures"):
            from engine.analysis.crypto_regime import CryptoRegimeEngine
            regime_engine = CryptoRegimeEngine()
            regime_df = regime_engine.evaluate_series(start, end, timeframe)
            if not regime_df.empty:
                exposure_series = regime_df["exposure"]

        df = self._strategy_engine.generate_signals(strategy, df)

        equity_curve, trades = self._simulate(df, initial_capital, exposure_series)

        total_return = compute_total_return(equity_curve)
        sharpe = compute_sharpe_ratio(equity_curve)
        max_dd = compute_max_drawdown(equity_curve)

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start,
            end_date=end,
            initial_capital=initial_capital,
            final_capital=float(equity_curve.iloc[-1]) if len(equity_curve) else initial_capital,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            trades=trades,
            equity_curve=equity_curve,
        )

    def _simulate(
        self,
        df: pd.DataFrame,
        initial_capital: float,
        exposure_series: pd.Series | None = None,
    ) -> tuple[pd.Series, list[TradeRecord]]:
        """Simple long-only simulation using close prices at signal bars.

        Position is 100% of capital on each trade (no partial sizing here),
        optionally scaled by a regime exposure fraction.
        """
        capital = initial_capital
        equity_values: list[float] = []
        trades: list[TradeRecord] = []

        in_position = False
        entry_price = 0.0
        entry_date = ""
        position_exposure = 1.0

        for ts, row in df.iterrows():
            signal = int(row.get("signal", 0))
            close = float(row["close"])
            date_str = str(ts)[:10]

            if not in_position and signal == 1:
                in_position = True
                entry_price = close
                entry_date = date_str
                # Apply exposure scaling
                if exposure_series is not None:
                    try:
                        position_exposure = float(exposure_series.asof(ts))
                    except Exception:
                        position_exposure = 1.0
                    if pd.isna(position_exposure):
                        position_exposure = 1.0
                else:
                    position_exposure = 1.0

            elif in_position and signal == -1:
                pnl_pct = (close - entry_price) / entry_price if entry_price != 0 else 0.0
                capital = capital * (1 + pnl_pct * position_exposure)
                trades.append(
                    TradeRecord(
                        entry_date=entry_date,
                        exit_date=date_str,
                        entry_price=entry_price,
                        exit_price=close,
                        pnl_pct=pnl_pct,
                    )
                )
                in_position = False

            # Mark-to-market equity
            if in_position:
                unrealized = (close / entry_price - 1.0) * position_exposure if entry_price != 0 else 0.0
                equity_values.append(capital * (1 + unrealized))
            else:
                equity_values.append(capital)

        # Close open position at last price
        if in_position and len(df) > 0:
            last_close = float(df["close"].iloc[-1])
            last_date = str(df.index[-1])[:10]
            pnl_pct = (last_close - entry_price) / entry_price if entry_price != 0 else 0.0
            capital = capital * (1 + pnl_pct * position_exposure)
            trades.append(
                TradeRecord(
                    entry_date=entry_date,
                    exit_date=last_date,
                    entry_price=entry_price,
                    exit_price=last_close,
                    pnl_pct=pnl_pct,
                )
            )
            if equity_values:
                equity_values[-1] = capital

        equity_curve = pd.Series(equity_values, index=df.index, dtype=float)
        return equity_curve, trades
