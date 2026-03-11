"""설정 기반 브로커 생성.

config/broker.json 또는 환경변수에서 설정 로드 → 적절한 브로커 인스턴스 반환.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from engine.execution.broker_base import BaseBroker

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("config/broker.json")


def _resolve_env(value: str) -> str:
    """${ENV_VAR} 형태를 환경변수 값으로 치환."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_key = value[2:-1]
        return os.environ.get(env_key, "")
    return value


def load_broker_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """broker.json 로드."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.warning("브로커 설정 파일 없음: %s — 기본값(paper) 사용", path)
        return {"default": "paper", "exchanges": {}}

    with open(path) as f:
        return json.load(f)


def create_broker(
    exchange: str | None = None,
    market_type: str | None = None,
    testnet: bool | None = None,
    config_path: str | Path | None = None,
) -> BaseBroker:
    """설정 기반 브로커 생성.

    Args:
        exchange: "paper" | "upbit" | "binance" (None이면 config default)
        market_type: "spot" | "futures" (None이면 config 값)
        testnet: True/False (None이면 config 값)
        config_path: broker.json 경로
    """
    config = load_broker_config(config_path)
    exchange = exchange or config.get("default", "paper")

    if exchange == "paper":
        from engine.execution.paper_broker import PaperBroker
        return PaperBroker()

    _SUPPORTED = {"binance", "upbit", "bybit", "okx"}
    if exchange not in _SUPPORTED:
        raise ValueError(f"지원하지 않는 거래소: {exchange}")

    exchange_config = config.get("exchanges", {}).get(exchange, {})
    api_key = _resolve_env(exchange_config.get("api_key", ""))
    secret = _resolve_env(exchange_config.get("secret", ""))

    if not api_key or not secret:
        raise ValueError(
            f"[{exchange}] API 키 미설정. "
            f"config/broker.json 또는 환경변수를 확인하세요."
        )

    if exchange == "binance":
        from engine.execution.binance_broker import BinanceBroker
        mt = market_type or exchange_config.get("market_type", "spot")
        tn = testnet if testnet is not None else exchange_config.get("testnet", True)
        broker = BinanceBroker(
            api_key=api_key,
            secret=secret,
            market_type=mt,
            testnet=tn,
        )
        # 선물 레버리지 기본값 설정
        leverage = exchange_config.get("leverage")
        if mt == "futures" and leverage and leverage > 1:
            logger.info("기본 레버리지: %dx", leverage)
        return broker

    if exchange == "upbit":
        from engine.execution.upbit_broker import UpbitBroker
        return UpbitBroker(api_key=api_key, secret=secret)

    # bybit / okx -- ccxt 범용 브로커
    from engine.execution.ccxt_broker import CcxtBroker
    mt = market_type or exchange_config.get("market_type", "spot")
    tn = testnet if testnet is not None else exchange_config.get("testnet", True)
    extra: dict[str, Any] = {}
    password = _resolve_env(exchange_config.get("password", ""))
    if password:
        extra["password"] = password
    return CcxtBroker(
        exchange=exchange,
        api_key=api_key,
        secret=secret,
        market_type=mt,
        testnet=tn,
        **extra,
    )
