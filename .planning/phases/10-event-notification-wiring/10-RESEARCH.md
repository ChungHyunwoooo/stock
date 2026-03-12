# Phase 10: Event & Notification Wiring - Research

**Researched:** 2026-03-12
**Domain:** Event notification wiring, Discord command plugin registration
**Confidence:** HIGH

## Summary

Phase 10 is a wiring/integration phase -- all components already exist, they just need to be connected. EventNotifier has 4 methods (`notify_execution`, `notify_lifecycle_transition`, `notify_system_error`, `notify_backtest_complete`) but only `notify_execution` is wired in TradingOrchestrator. The remaining 3 need production call sites. BacktestHistoryPlugin is already registered in DEFAULT_COMMAND_PLUGINS (success criteria #4 is already satisfied).

The core work is: (1) wire EventNotifier into `build_trading_runtime()` and connect it to LifecycleManager via the existing `add_transition_listener()` callback, (2) inject EventNotifier into BacktestRunner so `run()` fires `notify_backtest_complete`, (3) wire IndicatorSweeper to use EventNotifier for backtest completion events (alongside its existing Discord webhook notification for sweep summary).

**Primary recommendation:** Pure wiring changes in bootstrap.py + optional EventNotifier injection into BacktestRunner and IndicatorSweeper. No new classes or protocols needed.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MON-01 | 매매 체결/전략 상태 변화/시스템 이상/백테스트 결과를 실시간 Discord 알림으로 받을 수 있다 | EventNotifier 4개 메서드가 모두 프로덕션 호출 경로에 연결되면 충족. notify_execution은 이미 wired (orchestrator L168-169). notify_lifecycle_transition은 LifecycleManager.add_transition_listener()로 연결. notify_backtest_complete는 BacktestRunner.run() + IndicatorSweeper.run()에서 호출. notify_system_error는 기존 try/except 블록에서 호출 가능. |
| DISC-01 | indicator 조합을 자동 sweep하고 optuna 기반 Bayesian 파라미터 최적화로 후보 전략을 발굴할 수 있다 | IndicatorSweeper는 이미 완전 구현됨 (Phase 7). 이 phase에서는 sweep 완료 시 notify_backtest_complete를 호출하도록 wiring 추가. IndicatorSweeper._notify_results()가 이미 Discord webhook을 직접 사용하므로, EventNotifier를 통한 개별 후보 결과 통보를 추가하면 DISC-01의 알림 측면이 완성됨. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| EventNotifier | existing | 4개 이벤트 타입 포맷팅 + NotificationPort dispatch | Phase 6에서 구현, 프로덕션 wiring만 남음 |
| LifecycleManager | existing | FSM + add_transition_listener() callback | 이미 observer 패턴 내장 |
| BacktestRunner | existing | 백테스트 실행 + 결과 반환 | event_notifier optional injection 추가 필요 |
| IndicatorSweeper | existing | Optuna sweep + 후보 등록 | event_notifier optional injection 추가 필요 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| DiscordWebhookNotifier | existing | NotificationPort 구현체 | EventNotifier의 하위 전송 레이어 |
| MemoryNotifier | existing | 테스트용 인메모리 NotificationPort | 테스트에서 메시지 캡처 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Callback injection | Event bus (pubsub) | 과잉 -- 4개 이벤트에 pubsub 불필요 |
| Optional param injection | Global singleton | 테스트 불가, 프로젝트 규칙 위반 |

## Architecture Patterns

### Current Wiring State (AS-IS)

```
TradingOrchestrator
  ├── notifier: NotificationPort (send_execution, send_signal, send_text)
  └── event_notifier: EventNotifier | None  ← Phase 6에서 추가, bootstrap에서 미주입

LifecycleManager
  └── _on_transition_callbacks: list[Callable]  ← add_transition_listener() 있지만 미연결

BacktestRunner
  └── (EventNotifier 접점 없음)

IndicatorSweeper
  └── _notify_results() → DiscordWebhookNotifier() 직접 생성 (EventNotifier 미사용)

BacktestHistoryPlugin
  └── DEFAULT_COMMAND_PLUGINS에 이미 등록됨 ✓
```

### Target Wiring (TO-BE)

```
build_trading_runtime():
  1. EventNotifier(notifier) 생성
  2. orchestrator에 event_notifier 주입  ← notify_execution (이미 코드 있음)
  3. lifecycle.add_transition_listener(event_notifier.notify_lifecycle_transition)

BacktestRunner:
  4. event_notifier: EventNotifier | None 파라미터 추가
  5. run() 완료 후 event_notifier.notify_backtest_complete() 호출

IndicatorSweeper:
  6. event_notifier: EventNotifier | None 파라미터 추가
  7. _register_candidates() 또는 run() 완료 시 각 후보별 notify_backtest_complete() 호출
```

### Pattern: Optional Dependency Injection (프로젝트 기존 패턴)

```python
# BacktestRunner -- Phase 6 결정 [Phase 06-01] 패턴 준수
class BacktestRunner:
    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        fee_rate: float = 0.0,
        auto_save: bool = True,
        strategy_id: int | None = None,
        event_notifier: EventNotifier | None = None,  # NEW
    ) -> None:
        ...
        self._event_notifier = event_notifier
```

이 패턴은 프로젝트 전체에서 일관됨:
- `TradingOrchestrator(event_notifier=None)` -- Phase 6
- `PortfolioRiskManager(notifier=None)` -- Phase 4
- `BacktestRunner(slippage_model=None)` -- Phase 2

### Pattern: LifecycleManager Callback Wiring

```python
# bootstrap.py에서 연결
event_notifier = EventNotifier(notifier)
lifecycle.add_transition_listener(
    lambda sid, fr, to: event_notifier.notify_lifecycle_transition(sid, fr, to)
)
```

LifecycleManager callback signature: `(strategy_id: str, from_status: str, to_status: str) -> None`
EventNotifier.notify_lifecycle_transition signature: `(strategy_id, from_status, to_status, reason="") -> bool`

Callback에서 reason은 전달 불가 (LifecycleManager callback이 3-arg만 전달). 이는 Phase 6 설계 결정이며, 기본 reason="" 으로 충분함.

### Anti-Patterns to Avoid
- **IndicatorSweeper에서 DiscordWebhookNotifier 직접 생성 유지하면서 EventNotifier도 추가:** sweep 요약 알림(`_notify_results`)은 기존 유지, 개별 후보 결과 알림만 EventNotifier로 추가. 중복 알림 방지 필요.
- **BacktestRunner에 NotificationPort 직접 주입:** EventNotifier가 포맷팅 책임을 가지므로, NotificationPort가 아닌 EventNotifier를 주입해야 함.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 이벤트 디스패치 | Custom event bus/pubsub | LifecycleManager.add_transition_listener() + 직접 호출 | 4개 이벤트에 pubsub 프레임워크는 과잉 |
| Discord 메시지 포맷 | 각 호출부에서 문자열 조합 | EventNotifier의 기존 포맷 메서드 | 포맷 일관성, 단일 변경점 |
| Discord 전송 | requests/aiohttp 직접 호출 | NotificationPort (DiscordWebhookNotifier) | 이미 구현됨, retry/error 처리 내장 |

## Common Pitfalls

### Pitfall 1: BacktestRunner strategy_id 타입 불일치
**What goes wrong:** BacktestRunner의 strategy_id는 `int | None` (DB PK), EventNotifier.notify_backtest_complete의 strategy_id는 `str`. 타입 변환 필요.
**Why it happens:** BacktestRunner는 DB 저장용 int ID를, EventNotifier는 registry의 string ID를 사용.
**How to avoid:** BacktestRunner에 string strategy_name 파라미터를 추가하거나, 호출부에서 str()로 변환. IndicatorSweeper에서는 이미 string ID 사용하므로 문제 없음.
**Warning signs:** TypeError: expected str, got int

### Pitfall 2: IndicatorSweeper 중복 알림
**What goes wrong:** IndicatorSweeper._notify_results()가 이미 전체 sweep 결과를 Discord에 보내는데, 각 후보마다 notify_backtest_complete도 보내면 알림 폭주.
**Why it happens:** 두 경로가 동일 채널에 메시지를 보냄.
**How to avoid:** EventNotifier.notify_backtest_complete는 개별 후보 결과 알림용, _notify_results는 요약 알림용으로 역할 분리. 또는 sweep 완료 시 최종 결과 1건만 notify_backtest_complete 호출.

### Pitfall 3: Backward Compatibility
**What goes wrong:** BacktestRunner()를 인자 없이 호출하는 기존 코드가 깨짐.
**Why it happens:** event_notifier 파라미터 추가 시 default=None 누락.
**How to avoid:** `event_notifier: EventNotifier | None = None` -- 항상 Optional with None default. 프로젝트 결정 [Phase 02]: "BacktestRunner backward compatible: no-arg constructor defaults".

### Pitfall 4: Callback 에러가 전이를 차단
**What goes wrong:** EventNotifier가 Discord 전송 실패하면 LifecycleManager 전이가 실패.
**Why it happens:** callback에서 예외 발생.
**How to avoid:** 이미 해결됨 -- LifecycleManager.transition() L139-143에서 callback을 try/except로 감싸고 logger.warning만 출력. 프로젝트 결정 [Phase 06-01]: "LifecycleManager callbacks use try/except -- callback failure never blocks transition".

## Code Examples

### 1. Bootstrap에서 EventNotifier 생성 + LifecycleManager 연결

```python
# engine/interfaces/bootstrap.py -- build_trading_runtime() 내부
from engine.notifications.event_notifier import EventNotifier

event_notifier = EventNotifier(notifier)

# LifecycleManager callback 연결
lifecycle.add_transition_listener(
    lambda sid, fr, to: event_notifier.notify_lifecycle_transition(sid, fr, to)
)

# Orchestrator에 주입
orchestrator = TradingOrchestrator(
    store, notifier, broker,
    position_sizer=position_sizer,
    portfolio_risk=portfolio_risk,
    event_notifier=event_notifier,
)
```

### 2. BacktestRunner에 event_notifier 주입

```python
# engine/backtest/runner.py
class BacktestRunner:
    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        fee_rate: float = 0.0,
        auto_save: bool = True,
        strategy_id: int | None = None,
        event_notifier: EventNotifier | None = None,
    ) -> None:
        ...
        self._event_notifier = event_notifier

    def run(self, strategy, symbol, start, end, ...) -> BacktestResult:
        ...  # 기존 로직
        result = BacktestResult(...)

        if self._auto_save and self._strategy_id is not None:
            self._save_to_db(result)

        # 이벤트 알림
        if self._event_notifier is not None:
            try:
                self._event_notifier.notify_backtest_complete(
                    strategy_id=strategy.name,
                    symbol=result.symbol,
                    sharpe=result.sharpe_ratio,
                    total_return=result.total_return,
                    max_dd=result.max_drawdown,
                )
            except Exception:
                logger.warning("backtest completion notification failed")

        return result
```

### 3. IndicatorSweeper에 event_notifier 주입

```python
# engine/strategy/indicator_sweeper.py
class IndicatorSweeper:
    def __init__(
        self,
        config: SweepConfig,
        registry_path: str = "strategies/registry.json",
        event_notifier: EventNotifier | None = None,
    ) -> None:
        self._config = config
        self._registry_path = registry_path
        self._event_notifier = event_notifier

    def _register_candidates(self, study) -> list[dict]:
        ...  # 기존 등록 로직
        for trial in study.trials:
            if ...:
                ...  # 기존 등록
                # 개별 후보 알림
                if self._event_notifier is not None:
                    try:
                        self._event_notifier.notify_backtest_complete(
                            strategy_id=strategy_id,
                            symbol=self._config.symbols[0],
                            sharpe=trial.value,
                            total_return=0.0,  # sweep에서는 sharpe만 추적
                            max_dd=None,
                        )
                    except Exception:
                        logger.warning("sweep candidate notification failed")
        return candidates
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| EventNotifier 정의만 존재 | 4개 이벤트 모두 프로덕션 연결 | Phase 10 (현재) | MON-01 완성 |
| notify_execution만 wired | 모든 notify_* 메서드 활성 | Phase 10 (현재) | 실시간 Discord 알림 완전 커버 |
| IndicatorSweeper 직접 Discord 호출 | EventNotifier 경유 + 기존 요약 유지 | Phase 10 (현재) | 알림 채널 일원화 |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | existing project setup |
| Quick run command | `.venv/bin/python -m pytest tests/test_event_notifier.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MON-01a | LifecycleManager 전이 시 notify_lifecycle_transition 호출 | unit | `.venv/bin/python -m pytest tests/test_event_notifier.py::TestLifecycleCallbackIntegration -x` | YES (기존) |
| MON-01b | BacktestRunner.run() 완료 시 notify_backtest_complete 호출 | unit | `.venv/bin/python -m pytest tests/test_event_notifier.py::TestBacktestRunnerNotification -x` | NO -- Wave 0 |
| MON-01c | IndicatorSweeper sweep 완료 시 notify_backtest_complete 호출 | unit | `.venv/bin/python -m pytest tests/test_indicator_sweeper.py -x` | YES (확장 필요) |
| MON-01d | BacktestHistoryPlugin이 DEFAULT_COMMAND_PLUGINS에 등록됨 | unit | `.venv/bin/python -m pytest tests/test_event_notifier.py::TestBacktestHistoryRegistered -x` | NO -- Wave 0 |
| DISC-01 | IndicatorSweeper 후보 등록 시 EventNotifier 알림 | unit | `.venv/bin/python -m pytest tests/test_indicator_sweeper.py -x` | YES (확장 필요) |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_event_notifier.py tests/test_indicator_sweeper.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_event_notifier.py::TestBacktestRunnerNotification` -- BacktestRunner + EventNotifier 통합 테스트
- [ ] `tests/test_event_notifier.py::TestBacktestHistoryRegistered` -- DEFAULT_COMMAND_PLUGINS 등록 확인
- [ ] `tests/test_event_notifier.py::TestBootstrapWiring` -- build_trading_runtime()에서 EventNotifier 연결 확인 (optional)

*(기존 test_event_notifier.py에 TestLifecycleCallbackIntegration이 이미 존재하여 lifecycle wiring 패턴 검증됨)*

## Open Questions

1. **BacktestRunner의 strategy_id (int) vs EventNotifier의 strategy_id (str)**
   - What we know: BacktestRunner는 DB int PK, EventNotifier는 registry string ID 사용
   - What's unclear: run()에서 strategy.name을 사용할지, str(self._strategy_id)를 사용할지
   - Recommendation: strategy.name 사용 (StrategyDefinition.name은 string이며 의미 있는 이름)

2. **IndicatorSweeper sweep 결과 알림 중복 가능성**
   - What we know: _notify_results()가 요약 알림, notify_backtest_complete가 개별 알림
   - What's unclear: 사용자가 두 알림 모두 원하는지
   - Recommendation: 요약 알림(_notify_results)은 유지, 개별 후보 알림은 EventNotifier로 추가. 후보가 0건이면 알림 없음.

## Sources

### Primary (HIGH confidence)
- `engine/notifications/event_notifier.py` -- EventNotifier 4개 메서드 구현 확인
- `engine/strategy/lifecycle_manager.py` -- add_transition_listener() callback 패턴 확인
- `engine/interfaces/bootstrap.py` -- 현재 wiring 상태 (EventNotifier 미주입) 확인
- `engine/application/trading/orchestrator.py` -- event_notifier 파라미터 + notify_execution 호출 확인
- `engine/backtest/runner.py` -- EventNotifier 접점 없음 확인
- `engine/strategy/indicator_sweeper.py` -- DiscordWebhookNotifier 직접 사용 확인
- `engine/interfaces/discord/commands/__init__.py` -- BacktestHistoryPlugin 이미 DEFAULT_COMMAND_PLUGINS에 등록 확인
- `tests/test_event_notifier.py` -- 기존 테스트 커버리지 확인

### Secondary (MEDIUM confidence)
- `.planning/phases/06-alert-mtf-enrichment/06-RESEARCH.md` -- Phase 6 설계 결정 참조
- `.planning/STATE.md` -- 프로젝트 결정 이력 참조

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 모든 컴포넌트가 이미 존재, 소스 코드 직접 확인
- Architecture: HIGH - wiring 패턴이 프로젝트 전체에서 일관됨 (optional injection + try/except)
- Pitfalls: HIGH - 타입 불일치와 중복 알림은 코드에서 직접 확인

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (안정적 내부 wiring, 외부 의존성 없음)
