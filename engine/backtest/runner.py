
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import pandas as pd

from typing import TYPE_CHECKING

from engine.backtest.metrics import compute_max_drawdown, compute_sharpe_ratio, compute_total_return
from engine.backtest.slippage import NoSlippage, SlippageModel
from engine.data.provider_base import get_provider
from engine.schema import StrategyDefinition
from engine.strategy.strategy_evaluator import StrategyEngine

if TYPE_CHECKING:
    from engine.notifications.event_notifier import EventNotifier

logger = logging.getLogger(__name__)

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

    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        fee_rate: float = 0.0,
        auto_save: bool = True,
        strategy_id: int | None = None,
        event_notifier: EventNotifier | None = None,
    ) -> None:
        self._strategy_engine = StrategyEngine()
        self._slippage_model: SlippageModel = slippage_model or NoSlippage()
        self._fee_rate = fee_rate
        self._auto_save = auto_save
        self._strategy_id = strategy_id
        self._event_notifier = event_notifier

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

        equity_curve, trades = self._simulate(df, initial_capital, exposure_series, symbol=symbol)

        total_return = compute_total_return(equity_curve)
        sharpe = compute_sharpe_ratio(equity_curve)
        max_dd = compute_max_drawdown(equity_curve)

        result = BacktestResult(
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

        if self._auto_save and self._strategy_id is not None:
            self._save_to_db(result)

        if self._event_notifier is not None:
            try:
                self._event_notifier.notify_backtest_complete(
                    strategy_id=strategy.name,
                    symbol=result.symbol,
                    sharpe=result.sharpe_ratio,
                    total_return=result.total_return,
                    max_dd=result.max_drawdown,
                )
            except Exception as e:
                logger.warning("backtest completion notification failed: %s", e)

        return result

    def _save_to_db(self, result: BacktestResult) -> None:
        """Persist backtest result to DB. Failure is warning-only."""
        try:
            from engine.core.database import get_session
            from engine.core.db_models import BacktestRecord as DBBacktestRecord
            from engine.core.repository import BacktestRepository

            with get_session() as session:
                record = DBBacktestRecord(
                    strategy_id=self._strategy_id,
                    symbol=result.symbol,
                    timeframe=result.timeframe,
                    start_date=result.start_date,
                    end_date=result.end_date,
                    total_return=result.total_return,
                    sharpe_ratio=result.sharpe_ratio,
                    max_drawdown=result.max_drawdown,
                    result_json=result.to_result_json(),
                    slippage_model=type(self._slippage_model).__name__,
                    fee_rate=self._fee_rate,
                )
                BacktestRepository().save(session, record)
        except Exception as e:
            logger.warning("backtest result DB save failed: %s", e)

    def _simulate(
        self,
        df: pd.DataFrame,
        initial_capital: float,
        exposure_series: pd.Series | None = None,
        *,
        symbol: str = "",
    ) -> tuple[pd.Series, list[TradeRecord]]:
        """Simple long-only simulation using close prices at signal bars.

        Position is 100% of capital on each trade (no partial sizing here),
        optionally scaled by a regime exposure fraction.

        Slippage and fees are applied when ``self._slippage_model`` /
        ``self._fee_rate`` are configured (defaults preserve original
        behaviour).
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

                # --- slippage on entry ---
                slippage_pct = self._slippage_model.calculate_slippage(
                    symbol, "buy", capital, close,
                )
                entry_price = close * (1 + slippage_pct)

                # --- fee on entry ---
                entry_fee = capital * self._fee_rate
                capital -= entry_fee

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
                # --- slippage on exit ---
                slippage_pct = self._slippage_model.calculate_slippage(
                    symbol, "sell", capital, close,
                )
                exit_price = close * (1 - slippage_pct)

                pnl_pct = (exit_price - entry_price) / entry_price if entry_price != 0 else 0.0
                capital = capital * (1 + pnl_pct * position_exposure)

                # --- fee on exit ---
                exit_fee = capital * self._fee_rate
                capital -= exit_fee

                trades.append(
                    TradeRecord(
                        entry_date=entry_date,
                        exit_date=date_str,
                        entry_price=entry_price,
                        exit_price=exit_price,
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

            slippage_pct = self._slippage_model.calculate_slippage(
                symbol, "sell", capital, last_close,
            )
            exit_price = last_close * (1 - slippage_pct)

            pnl_pct = (exit_price - entry_price) / entry_price if entry_price != 0 else 0.0
            capital = capital * (1 + pnl_pct * position_exposure)

            exit_fee = capital * self._fee_rate
            capital -= exit_fee

            trades.append(
                TradeRecord(
                    entry_date=entry_date,
                    exit_date=last_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl_pct,
                )
            )
            if equity_values:
                equity_values[-1] = capital

        equity_curve = pd.Series(equity_values, index=df.index, dtype=float)
        return equity_curve, trades
