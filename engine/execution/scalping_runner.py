"""스캘핑 실시간 러너 — Binance Futures Testnet.

1분봉 기반 EMA Crossover 스캘핑 전략을 실시간 실행.
- 30초 간격으로 1분봉 체크
- 신호 감지 시 자동 주문
- SL/TP 자동 모니터링
- 실행 로그 + 성과 요약

사용법:
    python -m engine.execution.scalping_runner --duration 60
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import ccxt
import pandas as pd

import numpy as np

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


class ScalpingRunner:
    """스캘핑 실시간 러너."""

    def __init__(
        self,
        api_key: str,
        secret: str,
        symbol: str = "BTC/USDT:USDT",
        leverage: int = 5,
        stake_usdt: float = 50.0,
        cooldown_sec: int = 300,
        check_interval: int = 30,
        testnet: bool = True,
        risk_config: ScalpRiskConfig | None = None,
    ) -> None:
        self._symbol = symbol
        self._leverage = leverage
        self._stake_usdt = stake_usdt
        self._cooldown_sec = cooldown_sec
        self._check_interval = check_interval
        self._running = False
        self._risk_config = risk_config or ScalpRiskConfig()
        self._capital: float = 0.0  # setup()에서 잔고 조회 후 설정

        # ccxt Binance futures (USDM)
        self._exchange = ccxt.binanceusdm({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        })
        if testnet:
            self._exchange.enable_demo_trading(True)

        # 상태
        self._position: dict[str, Any] | None = None  # 현재 포지션
        self._last_signal_time: float = 0.0
        self._trades: list[dict[str, Any]] = []  # 완료된 거래
        self._trade_count = 0

    def setup(self) -> None:
        """초기 설정: 레버리지, 마진 모드."""
        try:
            self._exchange.set_leverage(self._leverage, self._symbol)
            logger.info("레버리지 설정: %s → %dx", self._symbol, self._leverage)
        except ccxt.BaseError as e:
            logger.warning("레버리지 설정 실패 (이미 설정됨?): %s", e)

        try:
            self._exchange.set_margin_mode("isolated", self._symbol)
            logger.info("마진 모드: isolated")
        except ccxt.BaseError as e:
            logger.warning("마진 모드 설정 실패: %s", e)

        # 잔고 확인
        balance = self._exchange.fetch_balance()
        usdt_free = float(balance.get("free", {}).get("USDT", 0))
        self._capital = usdt_free
        logger.info("USDT 잔고: %.2f (가용)", usdt_free)

        if usdt_free < self._stake_usdt:
            logger.warning(
                "잔고 부족! 필요: %.2f, 가용: %.2f",
                self._stake_usdt, usdt_free,
            )

    def fetch_ohlcv(self, limit: int = 50) -> pd.DataFrame:
        """1분봉 OHLCV 조회."""
        bars = self._exchange.fetch_ohlcv(self._symbol, "1m", limit=limit)
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df

    def _detect_pullback(self, df: pd.DataFrame) -> ScalpResult | None:
        """눌림목 패턴 감지 → ScalpResult 변환."""
        close = df["close"].values.astype(float)
        opn = df["open"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)

        # EMA 계산
        ema21 = pd.Series(close).ewm(span=21, adjust=False).mean().values
        ema55 = pd.Series(close).ewm(span=55, adjust=False).mean().values

        # 지지/저항 (local extrema)
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

        # 동적 리스크 적용
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

    def _in_cooldown(self) -> bool:
        return time.time() - self._last_signal_time < self._cooldown_sec

    def _has_position(self) -> bool:
        return self._position is not None

    def _check_position_exit(self, current_price: float) -> None:
        """SL/TP 도달 확인 → 자동 청산."""
        if not self._position:
            return

        pos = self._position
        side = pos["side"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]

        hit_sl = (side == "long" and current_price <= sl) or (side == "short" and current_price >= sl)
        hit_tp = (side == "long" and current_price >= tp) or (side == "short" and current_price <= tp)

        if hit_sl or hit_tp:
            exit_reason = "SL" if hit_sl else "TP"
            self._close_position(current_price, exit_reason)

    def _open_position(self, result: ScalpResult) -> None:
        """포지션 진입."""
        side = "buy" if result.signal == ScalpSignal.LONG else "sell"

        # 동적 리스크: risk 결과가 있으면 사용, 없으면 기존 방식
        if result.risk is not None:
            quantity = result.risk.quantity
            leverage = result.risk.leverage
            # 동적 레버리지 적용
            if leverage != self._leverage:
                try:
                    self._exchange.set_leverage(leverage, self._symbol)
                    logger.info("레버리지 변경: %dx → %dx", self._leverage, leverage)
                except Exception as e:
                    logger.warning("레버리지 변경 실패: %s (기존 %dx 유지)", e, self._leverage)
                    leverage = self._leverage
        else:
            quantity = round(self._stake_usdt * self._leverage / result.entry_price, 4)
            leverage = self._leverage

        try:
            order = self._exchange.create_order(
                symbol=self._symbol,
                type="market",
                side=side,
                amount=quantity,
            )

            self._trade_count += 1
            self._position = {
                "trade_no": self._trade_count,
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
            self._last_signal_time = time.time()

            logger.info(
                "═══ #%d %s 진입 ═══ 가격=%g 수량=%.4f %dx SL=%g TP=%g | %s",
                self._trade_count, result.signal.value.upper(),
                result.entry_price, quantity, leverage,
                result.stop_loss, result.take_profit,
                result.reason,
            )
        except ccxt.BaseError as e:
            logger.error("주문 실패: %s", e)

    def _close_position(self, exit_price: float, reason: str) -> None:
        """포지션 청산."""
        if not self._position:
            return

        pos = self._position
        close_side = "sell" if pos["side"] == "long" else "buy"

        try:
            self._exchange.create_order(
                symbol=self._symbol,
                type="market",
                side=close_side,
                amount=pos["quantity"],
            )

            # 손익 계산
            if pos["side"] == "long":
                pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
            else:
                pnl = (pos["entry_price"] - exit_price) * pos["quantity"]

            pnl_pct = pnl / (pos["entry_price"] * pos["quantity"]) * 100

            trade_record = {
                **pos,
                "exit_price": exit_price,
                "exit_at": datetime.now(timezone.utc).isoformat(),
                "exit_reason": reason,
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 2),
            }
            self._trades.append(trade_record)

            emoji = "+" if pnl > 0 else ""
            logger.info(
                "═══ #%d %s 청산 (%s) ═══ 진입=%g → 청산=%g | PnL=%s%.4f USDT (%s%.2f%%)",
                pos["trade_no"], pos["side"].upper(), reason,
                pos["entry_price"], exit_price,
                emoji, pnl, emoji, pnl_pct,
            )

            self._position = None

        except ccxt.BaseError as e:
            logger.error("청산 실패: %s", e)

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
            emoji = "+" if t["pnl"] > 0 else ""
            logger.info(
                "#%d %s %s→%.2f | %s | PnL=%s%.4f (%s%.2f%%)",
                t["trade_no"], t["side"].upper(),
                t.get("entry_price", 0), t.get("exit_price", 0),
                t.get("exit_reason", ""),
                emoji, t["pnl"], emoji, t["pnl_pct"],
            )

    def run(self, duration_minutes: int = 60) -> None:
        """메인 루프."""
        self._running = True
        end_time = time.time() + duration_minutes * 60

        # Ctrl+C 핸들링
        def _signal_handler(sig, frame):
            logger.info("중단 요청 — 포지션 청산 중...")
            self._running = False

        signal.signal(signal.SIGINT, _signal_handler)

        logger.info("=" * 60)
        logger.info(
            "스캘핑 시작: %s | %dx 레버리지 | %.2f USDT/거래 | %d분",
            self._symbol, self._leverage, self._stake_usdt, duration_minutes,
        )
        logger.info("=" * 60)

        self.setup()

        while self._running and time.time() < end_time:
            try:
                df = self.fetch_ohlcv(limit=50)
                current_price = float(df["close"].iloc[-1])

                # 포지션 있으면 SL/TP 체크
                if self._has_position():
                    self._check_position_exit(current_price)
                else:
                    # 쿨다운 아니면 신호 체크
                    if not self._in_cooldown():
                        result = detect_scalp_signal(
                            df,
                            capital=self._capital,
                            risk_config=self._risk_config,
                        )
                        # EMA cross 없으면 눌림목 체크
                        if result.signal == ScalpSignal.NONE:
                            pb = self._detect_pullback(df)
                            if pb is not None:
                                result = pb
                        if result.signal != ScalpSignal.NONE:
                            self._open_position(result)

                remaining = int((end_time - time.time()) / 60)
                if int(time.time()) % 300 < self._check_interval:  # 5분마다 상태 로그
                    if self._position:
                        pos = self._position
                        # 미실현 PnL 계산
                        if pos["side"] == "long":
                            unrealized = (current_price - pos["entry_price"]) * pos["quantity"]
                        else:
                            unrealized = (pos["entry_price"] - current_price) * pos["quantity"]
                        unrealized_pct = unrealized / (pos["entry_price"] * pos["quantity"]) * 100
                        sign = "+" if unrealized > 0 else ""
                        pos_str = (
                            f"{pos['side'].upper()} {pos.get('leverage', self._leverage)}x "
                            f"PnL={sign}{unrealized:.4f}({sign}{unrealized_pct:.2f}%)"
                        )
                    else:
                        pos_str = "대기 중"

                    # 누적 PnL
                    realized = sum(t["pnl"] for t in self._trades)
                    realized_str = f"실현={realized:+.4f}" if self._trades else ""

                    logger.info(
                        "[상태] 가격=%.2f | %s | %s | 거래=%d | 남은=%d분",
                        current_price, pos_str, realized_str,
                        len(self._trades), remaining,
                    )

                time.sleep(self._check_interval)

            except ccxt.NetworkError as e:
                logger.warning("네트워크 오류 — 재시도: %s", e)
                time.sleep(5)
            except Exception as e:
                logger.error("예상치 못한 오류: %s", e)
                time.sleep(10)

        # 종료: 열린 포지션 청산
        if self._position:
            try:
                df = self.fetch_ohlcv(limit=5)
                current_price = float(df["close"].iloc[-1])
                self._close_position(current_price, "종료")
            except Exception as e:
                logger.error("종료 청산 실패: %s", e)

        self.print_summary()


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description="EMA Crossover 스캘핑 러너")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="거래 심볼")
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

    # 환경변수 우선, 없으면 config/broker.json에서 로드
    api_key = os.environ.get("BINANCE_API_KEY", "")
    secret = os.environ.get("BINANCE_SECRET_KEY", "")

    if not api_key or not secret:
        try:
            from engine.execution.broker_factory import load_broker_config, _resolve_env
            config = load_broker_config()
            binance_cfg = config.get("exchanges", {}).get("binance", {})
            api_key = _resolve_env(binance_cfg.get("api_key", ""))
            secret = _resolve_env(binance_cfg.get("secret", ""))
        except Exception:
            pass

    if not api_key or not secret:
        logger.error(
            "API 키 미설정. 환경변수 또는 config/broker.json을 확인하세요.\n"
            "  export BINANCE_API_KEY=your_key\n"
            "  export BINANCE_SECRET_KEY=your_secret\n"
            "\n"
            "Binance Demo Trading 키 발급: https://testnet.binancefuture.com"
        )
        sys.exit(1)

    risk_cfg = ScalpRiskConfig(
        risk_per_trade_pct=args.risk_pct / 100,
        leverage_min=args.lev_min,
        leverage_max=args.lev_max,
    )

    runner = ScalpingRunner(
        api_key=api_key,
        secret=secret,
        symbol=args.symbol,
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
