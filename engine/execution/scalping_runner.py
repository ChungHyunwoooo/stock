"""스캘핑 실시간 러너 — Binance Futures.

1분봉 기반 EMA Crossover 스캘핑 전략을 실시간 실행.
- 30초 간격으로 1분봉 체크
- 신호 감지 시 자동 주문
- SL/TP 자동 모니터링
- 실행 로그 + 성과 요약
- 멀티심볼 병렬 체크 (ThreadPoolExecutor)

사용법:
    python -m engine.execution.scalping_runner --duration 60
    python -m engine.execution.scalping_runner --symbols BTC/USDT:USDT,ETH/USDT:USDT
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

from engine.execution.broker_factory import create_broker
from engine.execution.broker_base import BaseBroker
from engine.execution.binance_broker import BinanceBroker
from engine.strategy.risk_manager import RiskManager, RiskConfig
from engine.core.database import init_db, get_session
from engine.core.db_models import TradeRecord
from engine.core.repository import TradeRepository
from engine.strategy.pattern_detector import PatternSignal
from engine.strategy.scalping_ema_crossover import (
    ScalpResult,
    ScalpSignal,
    detect_scalp_signal,
)
from engine.strategy.scalping_risk import ScalpRiskConfig, calculate_scalp_risk
from engine.strategy.pullback_detector import detect_pullback
from engine.strategy.pattern_detector import find_local_extrema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_TAKER_FEE = 0.0004  # Binance taker fee 0.04%


def _to_pattern_signal(result: ScalpResult, bar_index: int = 0) -> PatternSignal:
    """ScalpResult → PatternSignal 변환 (RiskManager.allow_entry 호환)."""
    return PatternSignal(
        pattern="scalping_ema_crossover",
        side=result.signal.value.upper(),
        entry_price=result.entry_price,
        stop_loss=result.stop_loss,
        take_profit=result.take_profit,
        bar_index=bar_index,
        metadata={"confidence": 0.7},
    )


class ScalpingRunner:
    """스캘핑 실시간 러너 (멀티심볼 지원)."""

    def __init__(
        self,
        symbol: str = "BTC/USDT:USDT",
        symbols: list[str] | None = None,
        leverage: int = 5,
        stake_usdt: float = 50.0,
        cooldown_sec: int = 300,
        check_interval: int = 30,
        testnet: bool = True,
        risk_config: ScalpRiskConfig | None = None,
    ) -> None:
        # symbols 우선, 없으면 단일 symbol
        self._symbols: list[str] = symbols if symbols else [symbol]
        self._symbol = self._symbols[0]  # 하위호환용

        self._leverage = leverage
        self._stake_usdt = stake_usdt
        self._cooldown_sec = cooldown_sec
        self._check_interval = check_interval
        self._running = False
        self._risk_config = risk_config or ScalpRiskConfig()
        self._capital: float = 0.0  # setup()에서 잔고 조회 후 설정
        self._testnet = testnet

        # 브로커
        self._broker: BinanceBroker = create_broker(  # type: ignore[assignment]
            exchange="binance",
            market_type="futures",
            testnet=testnet,
        )

        # RiskManager
        self._risk_manager = RiskManager(RiskConfig())

        # DB
        init_db()
        self._trade_repo = TradeRepository()

        # 심볼별 독립 상태
        self._positions: dict[str, dict[str, Any] | None] = {}
        self._last_signal_time: dict[str, float] = {}
        self._current_trade_ids: dict[str, str | None] = {}

        # 거래 기록 (모든 심볼 통합)
        self._trades: list[dict[str, Any]] = []
        self._trade_count = 0

        # 주문 경합 방지 Lock
        self._order_lock = threading.Lock()

    def setup(self) -> None:
        """초기 설정: 레버리지, 마진 모드, 시장 정보, 잔고."""
        for symbol in self._symbols:
            self._broker.set_leverage(symbol, self._leverage)
            self._broker.set_margin_mode(symbol, "isolated")
            self._broker.load_market_info(symbol)
            self._positions[symbol] = None
            self._last_signal_time[symbol] = 0.0
            self._current_trade_ids[symbol] = None

        usdt_free = self._broker.fetch_available()
        self._capital = usdt_free
        logger.info("USDT 잔고: %.2f (가용)", usdt_free)

        if usdt_free < self._stake_usdt:
            logger.warning(
                "잔고 부족! 필요: %.2f, 가용: %.2f",
                self._stake_usdt, usdt_free,
            )

    def fetch_ohlcv(self, symbol: str, limit: int = 50) -> pd.DataFrame:
        """1분봉 OHLCV 조회."""
        return self._broker.fetch_ohlcv(symbol, "1m", limit)

    def _detect_pullback(self, symbol: str, df: pd.DataFrame) -> ScalpResult | None:
        """눌림목 패턴 감지 → ScalpResult 변환."""
        close = df["close"].values.astype(float)
        opn = df["open"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)

        ema21 = pd.Series(close).ewm(span=21, adjust=False).mean().values
        ema55 = pd.Series(close).ewm(span=55, adjust=False).mean().values

        low_mins, high_maxs = find_local_extrema(low, order=5)
        _, high_maxs = find_local_extrema(high, order=5)

        i = len(close) - 1
        sig = detect_pullback(
            opn, high, low, close, i,
            ema21, ema55, low_mins, high_maxs,
            require_candle=False,
        )
        if sig is None:
            return None

        side_val = "long" if sig.side == "LONG" else "short"
        price = float(close[-1])

        risk = None
        if self._capital > 0:
            risk = calculate_scalp_risk(
                df, price, side_val, self._capital, self._risk_config,
            )

        return ScalpResult(
            signal=ScalpSignal.LONG if side_val == "long" else ScalpSignal.SHORT,
            entry_price=price,
            stop_loss=risk.stop_loss if risk else sig.stop_loss,
            take_profit=risk.take_profit if risk else sig.take_profit,
            ema_fast=float(ema21[i]),
            ema_slow=float(ema55[i]),
            rsi=0,
            reason=f"눌림목 {side_val.upper()} | {risk.reason if risk else ''}",
            risk=risk,
        )

    def _in_cooldown(self, symbol: str) -> bool:
        return time.time() - self._last_signal_time.get(symbol, 0.0) < self._cooldown_sec

    def _has_position(self, symbol: str) -> bool:
        return self._positions.get(symbol) is not None

    def _check_position_exit(self, symbol: str, current_price: float) -> None:
        """SL/TP 도달 확인 → 자동 청산."""
        pos = self._positions.get(symbol)
        if not pos:
            return

        side = pos["side"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]

        hit_sl = (side == "long" and current_price <= sl) or (side == "short" and current_price >= sl)
        hit_tp = (side == "long" and current_price >= tp) or (side == "short" and current_price <= tp)

        if hit_sl or hit_tp:
            exit_reason = "SL" if hit_sl else "TP"
            self._close_position(symbol, current_price, exit_reason)

    def _open_position(self, symbol: str, result: ScalpResult) -> None:
        """포지션 진입."""
        # RiskManager 진입 허용 체크
        ps = _to_pattern_signal(result, bar_index=0)
        if not self._risk_manager.allow_entry(symbol, ps):
            logger.info("RiskManager: 진입 거부 (%s)", symbol)
            return

        side = "buy" if result.signal == ScalpSignal.LONG else "sell"

        if result.risk is not None:
            quantity = result.risk.quantity
            leverage = result.risk.leverage
            if leverage != self._leverage:
                try:
                    self._broker.set_leverage(symbol, leverage)
                    logger.info("레버리지 변경: %dx → %dx (%s)", self._leverage, leverage, symbol)
                except Exception as e:
                    logger.warning("레버리지 변경 실패: %s (기존 %dx 유지)", e, self._leverage)
                    leverage = self._leverage
        else:
            quantity = round(self._stake_usdt * self._leverage / result.entry_price, 4)
            leverage = self._leverage

        quantity = self._broker.clamp_quantity(symbol, quantity)
        if quantity <= 0:
            logger.warning("수량 0 — 주문 취소 (%s)", symbol)
            return

        with self._order_lock:
            try:
                order = self._broker._exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=quantity,
                )

                entry_fee = result.entry_price * quantity * _TAKER_FEE
                trade_id = uuid4().hex[:12]
                self._trade_count += 1
                trade_no = self._trade_count

                with get_session() as session:
                    trade = TradeRecord(
                        trade_id=trade_id,
                        strategy_name="scalping_ema_crossover",
                        symbol=symbol,
                        timeframe="1m",
                        side=result.signal.value,
                        broker="paper" if self._testnet else "live",
                        entry_price=result.entry_price,
                        entry_quantity=quantity,
                        entry_fee=entry_fee,
                        entry_tag=result.reason,
                        entry_at=datetime.now(timezone.utc),
                        stop_loss=result.stop_loss,
                        take_profit=result.take_profit,
                        stake_amount=result.entry_price * quantity,
                        status="open",
                    )
                    self._trade_repo.save(session, trade)

                self._current_trade_ids[symbol] = trade_id
                self._positions[symbol] = {
                    "trade_no": trade_no,
                    "symbol": symbol,
                    "side": result.signal.value,
                    "entry_price": result.entry_price,
                    "quantity": quantity,
                    "leverage": leverage,
                    "stop_loss": result.stop_loss,
                    "take_profit": result.take_profit,
                    "entry_at": datetime.now(timezone.utc).isoformat(),
                    "order_id": order.get("id", ""),
                    "reason": result.reason,
                }
                self._last_signal_time[symbol] = time.time()
                self._risk_manager.on_entry(symbol)

                logger.info(
                    "═══ #%d %s 진입 [%s] ═══ 가격=%g 수량=%.4f %dx SL=%g TP=%g | %s",
                    trade_no, result.signal.value.upper(), symbol,
                    result.entry_price, quantity, leverage,
                    result.stop_loss, result.take_profit,
                    result.reason,
                )
            except Exception as e:
                logger.error("주문 실패 (%s): %s", symbol, e)

    def _close_position(self, symbol: str, exit_price: float, reason: str) -> None:
        """포지션 청산."""
        pos = self._positions.get(symbol)
        if not pos:
            return

        close_side = "sell" if pos["side"] == "long" else "buy"

        with self._order_lock:
            try:
                self._broker._exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=close_side,
                    amount=pos["quantity"],
                )

                # 수수료 반영 손익 계산
                entry_fee = pos["entry_price"] * pos["quantity"] * _TAKER_FEE
                exit_fee = exit_price * pos["quantity"] * _TAKER_FEE
                profit = BaseBroker.calc_profit(
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    quantity=pos["quantity"],
                    entry_fee=entry_fee,
                    exit_fee=exit_fee,
                )
                pnl = profit["profit_abs"]
                pnl_pct = profit["profit_pct"]

                # DB 청산 기록
                current_trade_id = self._current_trade_ids.get(symbol)
                if current_trade_id:
                    with get_session() as session:
                        self._trade_repo.close_trade(
                            session,
                            current_trade_id,
                            exit_price=exit_price,
                            exit_quantity=pos["quantity"],
                            exit_fee=exit_fee,
                            exit_reason=reason,
                            exit_at=datetime.now(timezone.utc),
                        )

                trade_record = {
                    **pos,
                    "exit_price": exit_price,
                    "exit_at": datetime.now(timezone.utc).isoformat(),
                    "exit_reason": reason,
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl_pct, 2),
                }
                self._trades.append(trade_record)

                self._risk_manager.on_exit(symbol, pnl_pct, reason)

                sign = "+" if pnl > 0 else ""
                logger.info(
                    "═══ #%d %s 청산 (%s) [%s] ═══ 진입=%g → 청산=%g | PnL=%s%.4f USDT (%s%.2f%%)",
                    pos["trade_no"], pos["side"].upper(), reason, symbol,
                    pos["entry_price"], exit_price,
                    sign, pnl, sign, pnl_pct,
                )

                self._positions[symbol] = None
                self._current_trade_ids[symbol] = None

            except Exception as e:
                logger.error("청산 실패 (%s): %s", symbol, e)

    def _check_symbol(self, symbol: str) -> None:
        """단일 심볼 체크: OHLCV → SL/TP 체크 or 신호 감지 → 주문."""
        df = self._broker.fetch_ohlcv(symbol, "1m", 50)
        if df.empty:
            return
        current_price = float(df["close"].iloc[-1])

        if self._positions.get(symbol) is not None:
            self._check_position_exit(symbol, current_price)
        else:
            if not self._in_cooldown(symbol):
                result = detect_scalp_signal(df, capital=self._capital, risk_config=self._risk_config)
                if result.signal == ScalpSignal.NONE:
                    pb = self._detect_pullback(symbol, df)
                    if pb is not None:
                        result = pb
                if result.signal != ScalpSignal.NONE:
                    self._open_position(symbol, result)

    def print_summary(self) -> None:
        """실행 성과 요약."""
        logger.info("=" * 60)
        logger.info("스캘핑 성과 요약")
        logger.info("=" * 60)

        if not self._trades:
            logger.info("거래 없음")
            return

        wins = [t for t in self._trades if t["pnl"] > 0]
        losses = [t for t in self._trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in self._trades)

        logger.info("총 거래: %d (승: %d, 패: %d)", len(self._trades), len(wins), len(losses))
        logger.info("승률: %.1f%%", len(wins) / len(self._trades) * 100)
        logger.info("총 PnL: %.4f USDT", total_pnl)

        if wins:
            logger.info("평균 이익: %.4f USDT", sum(t["pnl"] for t in wins) / len(wins))
        if losses:
            logger.info("평균 손실: %.4f USDT", sum(t["pnl"] for t in losses) / len(losses))

        logger.info("-" * 60)
        for t in self._trades:
            sign = "+" if t["pnl"] > 0 else ""
            logger.info(
                "#%d %s [%s] %s→%.2f | %s | PnL=%s%.4f (%s%.2f%%)",
                t["trade_no"], t["side"].upper(),
                t.get("symbol", ""),
                t.get("entry_price", 0), t.get("exit_price", 0),
                t.get("exit_reason", ""),
                sign, t["pnl"], sign, t["pnl_pct"],
            )

    def run(self, duration_minutes: int = 60) -> None:
        """메인 루프."""
        self._running = True
        end_time = time.time() + duration_minutes * 60

        def _signal_handler(sig, frame):
            logger.info("중단 요청 — 포지션 청산 중...")
            self._running = False

        signal.signal(signal.SIGINT, _signal_handler)

        logger.info("=" * 60)
        logger.info(
            "스캘핑 시작: %s | %dx 레버리지 | %.2f USDT/거래 | %d분",
            ", ".join(self._symbols), self._leverage, self._stake_usdt, duration_minutes,
        )
        logger.info("=" * 60)

        self.setup()

        max_workers = min(len(self._symbols), 5)

        while self._running and time.time() < end_time:
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(self._check_symbol, s): s for s in self._symbols}
                    for future in as_completed(futures):
                        sym = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            logger.error("심볼 %s 체크 오류: %s", sym, e)

                # 상태 로그 (5분마다)
                remaining = int((end_time - time.time()) / 60)
                if int(time.time()) % 300 < self._check_interval:
                    realized = sum(t["pnl"] for t in self._trades)
                    realized_str = f"실현={realized:+.4f}" if self._trades else ""
                    open_symbols = [s for s in self._symbols if self._positions.get(s)]
                    pos_str = f"포지션={open_symbols}" if open_symbols else "대기 중"
                    logger.info(
                        "[상태] %s | %s | 거래=%d | 남은=%d분",
                        pos_str, realized_str, len(self._trades), remaining,
                    )

                time.sleep(self._check_interval)

            except Exception as e:
                logger.error("예상치 못한 오류: %s", e)
                time.sleep(10)

        # 종료: 모든 열린 포지션 청산
        for symbol in self._symbols:
            if self._positions.get(symbol) is not None:
                try:
                    df = self._broker.fetch_ohlcv(symbol, "1m", 5)
                    current_price = float(df["close"].iloc[-1])
                    self._close_position(symbol, current_price, "종료")
                except Exception as e:
                    logger.error("종료 청산 실패 (%s): %s", symbol, e)

        self.print_summary()


def main() -> None:
    parser = argparse.ArgumentParser(description="EMA Crossover 스캘핑 러너")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="거래 심볼")
    parser.add_argument("--symbols", default=None, help="복수 심볼 (쉼표 구분, 예: BTC/USDT:USDT,ETH/USDT:USDT)")
    parser.add_argument("--duration", type=int, default=60, help="실행 시간(분)")
    parser.add_argument("--leverage", type=int, default=5, help="레버리지")
    parser.add_argument("--stake", type=float, default=50.0, help="거래당 USDT")
    parser.add_argument("--cooldown", type=int, default=300, help="쿨다운(초)")
    parser.add_argument("--interval", type=int, default=30, help="체크 간격(초)")
    parser.add_argument("--live", action="store_true", help="실제 거래 (기본: testnet)")
    parser.add_argument("--risk-pct", type=float, default=2.0, help="거래당 리스크 (%)")
    parser.add_argument("--lev-min", type=int, default=2, help="최소 레버리지")
    parser.add_argument("--lev-max", type=int, default=20, help="최대 레버리지")
    args = parser.parse_args()

    risk_cfg = ScalpRiskConfig(
        risk_per_trade_pct=args.risk_pct / 100,
        leverage_min=args.lev_min,
        leverage_max=args.lev_max,
    )

    symbols = args.symbols.split(",") if args.symbols else None

    runner = ScalpingRunner(
        symbol=args.symbol,
        symbols=symbols,
        leverage=args.leverage,
        stake_usdt=args.stake,
        cooldown_sec=args.cooldown,
        check_interval=args.interval,
        testnet=not args.live,
        risk_config=risk_cfg,
    )
    runner.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
