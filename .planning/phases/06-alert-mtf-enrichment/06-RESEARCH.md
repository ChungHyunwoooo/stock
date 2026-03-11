# Phase 6 Research: Alert & MTF Enrichment

## 1. Existing Discord Notification System

### engine/notifications/discord_webhook.py (NotificationPort 구현)
- `DiscordWebhookNotifier(NotificationPort)` — TradingOrchestrator가 사용하는 구조화된 알림기
- `send_signal()`, `send_pending()`, `send_execution()`, `send_text()` 메서드
- webhook URL: `config/discord.json`의 `webhook_url` 또는 `webhooks.tf_{timeframe}` 키로 분기
- 차트 이미지 첨부 지원 (multipart/form-data)
- `MemoryNotifier` — 테스트용 인메모리 구현

### engine/notifications/alert_discord.py (레거시 함수형)
- `send_signal(Signal)`, `send_position_alert(alert)`, `send_text(message)` — 함수형 API
- `Signal` dataclass (strategy, symbol, side, entry, stop_loss, take_profits 등)
- 채널별 webhook URL 지원: `load_webhook_url_for(channel)`
- embed 포맷: 전략색상, 진입가/손절가/목표가/신뢰도 필드

### engine/core/ports.py — NotificationPort Protocol
```python
class NotificationPort(Protocol):
    send_signal(signal: TradingSignal, mode_label: str) -> bool
    send_pending(pending: PendingOrder) -> bool
    send_execution(execution: ExecutionRecord) -> bool
    send_text(message: str) -> bool
```

**현황:** send_execution()은 이미 있지만 간단한 텍스트. 전략 상태 변화, 시스템 이상, 백테스트 완료 이벤트는 미구현.

## 2. Discord Bot Implementation

### engine/interfaces/discord/control_bot.py
- `discord.py` 기반 봇, `discord.app_commands.CommandTree` 사용
- guild-specific sync 지원 (config/discord.json의 guild_id)
- `DiscordBotContext(control, preferences, lifecycle_manager)` 컨텍스트 객체

### engine/interfaces/discord/commands/ (Plugin 패턴)
- `DiscordCommandPlugin` Protocol: `name: str`, `register(tree, context)`
- `DEFAULT_COMMAND_PLUGINS`: Runtime, Order, Analysis, Pattern, Scanner, Lifecycle, BacktestHistory, PaperTrading
- `RuntimeCommandPlugin` — 기존 /status: `format_runtime_state()` (mode, paused, pending count, positions count만 표시)

### engine/interfaces/discord/formatting.py
- `format_runtime_state()` — 현재 상태 텍스트 포맷 (매우 기본적)
- `format_pending_list()` — pending orders 리스트

**현황:** /status는 존재하지만 포지션 상세, 일일 PnL, 전략별 상태 없음. 확장 필요.

## 3. Event/Signal Flow in Strategy Layer

### engine/application/trading/orchestrator.py — TradingOrchestrator
- `process_signal(signal, quantity)` — 핵심 흐름:
  1. paused/alert_only/semi_auto 모드 분기
  2. PortfolioRiskManager 상관관계 게이트 (full_auto)
  3. 주문 실행 → `notifier.send_execution(execution)`
- 이미 `notifier: NotificationPort`를 주입받아 사용

### engine/application/trading/trading_control.py — TradingControlService
- mode 변경, pause/resume 시 `notifier.send_text()` 호출
- 봇 컨텍스트에서 사용

### engine/strategy/lifecycle_manager.py — LifecycleManager
- 전략 상태 전이 (draft->testing->paper->active->archived)
- **알림 미연동** — 순수 도메인 서비스, 외부 호출 없음
- 전이 이벤트를 NotificationPort로 발송하는 래퍼/옵저버 필요

## 4. Data Provider for Multi-Timeframe

### engine/data/provider_base.py — DataProvider ABC
- `fetch_ohlcv(symbol, start, end, timeframe="1d")` → pd.DataFrame

### engine/data/provider_crypto.py — CryptoProvider (ccxt)
- Binance 등 거래소에서 OHLCV 조회
- timeframe 파라미터로 멀티 타임프레임 데이터 조회 가능

### engine/execution/binance_broker.py
- `fetch_ohlcv(symbol, timeframe="1m", limit=50)` — 실시간 봉 조회

### engine/strategy/pattern_alert.py
- 이미 멀티 타임프레임 스캔: `timeframes: ["5m", "15m", "30m", "1h", "4h"]`
- 각 타임프레임별 독립 분석

## 5. Indicator Infrastructure

### engine/indicators/
- `base.py` — SingleResult, BandResult, DualResult, TripleResult
- `compute.py` — `compute_indicator(df, IndicatorDef)`, `compute_all_indicators()`
- `registry.py` — ta-lib 함수 레지스트리
- subdirs: `price/`, `momentum/`, `volume/`, `custom/`
- EMA, RSI 등 기본 인디케이터 모두 구현됨

**MTF 방향 판단:** EMA 방향(상승/하락)이나 RSI 과매수/과매도로 상위 TF 방향 결정 가능. 별도 MTF 전용 모듈은 없음.

## 6. Config System

### engine/config_path.py
- `config_file(name)` → `{project_root}/config/{name}`
- `state_file(name)` → `{project_root}/state/{name}`

### engine/notifications/alert_bot_config.py — BotConfig
- JSON 기반 설정 (config/bot_config.json)
- 전략별 enable/disable 토글 패턴 존재

**MTF 필터 설정:** config/trading.json 또는 StrategyDefinition에 mtf_filter 필드 추가 필요.

## 7. Key Design Decisions for Phase 6

1. **NotificationPort 확장 vs 새 메서드:** 기존 `send_text()`로 충분 — 포맷만 구조화하면 됨. NotificationPort에 새 메서드 추가하면 모든 구현체 수정 필요 → `send_text()`에 구조화된 embed 지원하는 래퍼 함수 방식이 낫다.
2. **이벤트 발행 패턴:** LifecycleManager에 옵저버 패턴(콜백) 추가하여 전이 시 알림 발송. Orchestrator는 이미 notifier 사용 중.
3. **MTF 게이트 위치:** TradingOrchestrator.process_signal()에서 PortfolioRiskManager 게이트와 동일한 패턴으로 삽입.
4. **/status 확장:** format_runtime_state()를 embed 기반으로 교체하고, BrokerPort.fetch_open_positions() + PaperBroker PnL 조회 추가.
