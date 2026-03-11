---
phase: 05-performance-monitoring
verified: 2026-03-12T04:50:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 5: Performance Monitoring Verification Report

**Phase Goal:** 실매매 전략의 롤링 윈도우 성과를 모니터링하고, 백테스트 baseline 대비 저하 시 Discord 알림 + 자동 일시정지
**Verified:** 2026-03-12T04:50:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | active 전략의 최근 20거래 롤링 윈도우 Sharpe/승률을 계산할 수 있다 | VERIFIED | `_compute_rolling_metrics(trades, window)` 구현, 3개 테스트 통과 |
| 2 | 백테스트 기준 대비 성과 저하율을 산출할 수 있다 | VERIFIED | `_evaluate_strategy` → degradation_pct_sharpe/win_rate 계산, `_get_baseline` → BacktestRepository 연결 |
| 3 | 모니터가 별도 스레드에서 실행되어 Orchestrator와 완전히 분리된다 | VERIFIED | `run_daemon()` → `threading.Thread(daemon=True)`, try/except 격리 |
| 4 | 모니터 다운 시 실매매가 계속된다 | VERIFIED | daemon 스레드 분리 + `except Exception: logger.exception(...)` 격리, Orchestrator 무관 |
| 5 | 전략별 일시정지가 가능하다 (paused_strategies) | VERIFIED | `TradingRuntimeState.paused_strategies: set[str]`, Orchestrator `process_signal()` 체크 |
| 6 | WARNING 알림: 20거래 Sharpe/승률 baseline 대비 15% 이상 하락 시 Discord WARNING embed 발송 | VERIFIED | `_handle_warning` → `notifier.send_performance_alert(snap)`, color=0xFFA500, 테스트 통과 |
| 7 | CRITICAL 알림: 30거래 롤링 Sharpe < -0.5 시 Discord CRITICAL embed 발송 | VERIFIED | `_handle_critical` → `notifier.send_performance_alert(snap)`, color=0xFF0000, 테스트 통과 |
| 8 | CRITICAL 시 해당 전략의 신규 진입이 자동 일시정지된다 | VERIFIED | `_handle_critical` → `state.paused_strategies.add(strategy_id)` + `runtime_store.save(state)` |
| 9 | 알림에 전략명, 현재 Sharpe, baseline Sharpe, 저하율, 윈도우 크기가 포함된다 | VERIFIED | `send_performance_alert` embed fields: 현재 Sharpe, 기준 Sharpe, Sharpe 저하율, 현재 승률, 기준 승률, 승률 저하율, Alert Level |

**Score:** 9/9 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `engine/strategy/performance_monitor.py` | StrategyPerformanceMonitor + PerformanceConfig + PerformanceSnapshot | VERIFIED | 244줄, 실질 구현 — 데이터클래스 2개 + 클래스 1개, rolling metrics/baseline/alert/daemon 모두 구현 |
| `engine/notifications/discord_webhook.py` | send_performance_alert embed 메서드 | VERIFIED | `DiscordWebhookNotifier.send_performance_alert` + `MemoryNotifier.send_performance_alert` 구현 |
| `engine/core/models.py` | TradingRuntimeState.paused_strategies 필드 | VERIFIED | `paused_strategies: set[str] = field(default_factory=set)` 추가됨 |
| `engine/core/json_store.py` | paused_strategies 직렬화/역직렬화 | VERIFIED | `_state_to_dict`: `sorted(state.paused_strategies)`, `_state_from_dict`: `set(data.get("paused_strategies", []))` |
| `engine/application/trading/orchestrator.py` | per-strategy pause 체크 | VERIFIED | `if signal.strategy_id in state.paused_strategies:` 블록 구현 |
| `engine/core/ports.py` | NotificationPort.send_performance_alert 추가 | VERIFIED | `def send_performance_alert(self, snapshot: "PerformanceSnapshot") -> bool: ...` |
| `tests/test_performance_monitor.py` | 모니터 유닛 테스트 | VERIFIED | 18개 테스트, 전체 통과 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `performance_monitor.py` | `engine/core/repository.py` | `trade_repo.list_closed` + `backtest_repo.get_history` | WIRED | `_evaluate_strategy` 내 직접 호출 확인 |
| `performance_monitor.py` | `engine/strategy/lifecycle_manager.py` | `lifecycle.list_by_status("active")` | WIRED | `check_all` 내 `self.lifecycle.list_by_status("active")` 호출 확인 |
| `performance_monitor.py` | `engine/notifications/discord_webhook.py` | `notifier.send_performance_alert(snapshot)` | WIRED | `_handle_critical`, `_handle_warning` 양쪽에서 호출 |
| `performance_monitor.py` | `engine/core/json_store.py` | `runtime_store.save(state)` with `paused_strategies.add(...)` | WIRED | `_handle_critical` → `state.paused_strategies.add(strategy_id)` + `self.runtime_store.save(state)` |

---

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RISK-01 | 05-01, 05-02 | 실매매 전략의 20거래 롤링 윈도우 성과가 백테스트 기준 대비 저하되면 Discord 알림을 발송한다 | SATISFIED | rolling window 계산, baseline 비교, WARNING/CRITICAL Discord embed, 자동 일시정지 전체 체인 구현 및 18개 테스트 통과 |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None found |

Phase 5 변경 파일(performance_monitor.py, discord_webhook.py, models.py, json_store.py, orchestrator.py, ports.py) 전체에 TODO/FIXME/placeholder/stub 패턴 없음.

---

## Test Results

### Phase 5 직접 테스트

```
tests/test_performance_monitor.py — 18 passed in 1.42s
```

모든 18개 테스트 통과:
- TestComputeRollingMetrics: 3/3
- TestEvaluateStrategy: 4/4
- TestPausedStrategiesSerialization: 2/2
- TestOrchestratorSkipsPausedStrategy: 2/2
- TestWarningAlert: 1/1
- TestCriticalAlert: 2/2
- TestDiscordEmbed: 3/3
- TestMultipleStrategiesIndependent: 1/1

### 회귀 테스트 (tests/trading/)

```
tests/trading/ — 19 passed, 1 failed
FAILED tests/trading/test_plugin_registry.py::test_discord_command_registry_registers_all_groups
```

`test_plugin_registry` 실패는 Phase 5 변경과 무관한 기존 실패 (05-02-SUMMARY.md에 명시됨). Phase 5 커밋(cf67dc5, db03fab)의 변경 파일에 plugin_registry 포함 없음. 19개 나머지 테스트 정상.

---

## Human Verification Required

### 1. Discord Webhook 실제 발송 확인

**Test:** config/discord.json 또는 DISCORD_WEBHOOK_URL 설정 후 WARNING/CRITICAL snapshot으로 `send_performance_alert` 호출
**Expected:** Discord 채널에 색상(주황/빨강) embed 수신, 필드(Sharpe, 승률, 저하율, 윈도우) 포함
**Why human:** 외부 Discord API 연동 — 자동 검증 불가

### 2. Daemon Thread 실제 주기 동작 확인

**Test:** `run_daemon(session_factory)` 호출 후 900초 이내 check_all 실행 로그 확인
**Expected:** "Performance monitor daemon started (interval=900s)" 로그 + 주기적 `Error evaluating strategy` 없이 정상 순환
**Why human:** 실제 런타임 스레드 동작 — 정적 분석 불가

---

## Summary

Phase 5 목표 **전체 달성**. RISK-01 요구사항 체인 완성:

- **감지**: 20거래 rolling Sharpe/win_rate 계산 + BacktestRepository baseline 비교
- **알림**: WARNING(주황 embed) / CRITICAL(빨강 embed) Discord 발송
- **방어**: CRITICAL 시 `paused_strategies.add` + `runtime_store.save` → Orchestrator 신호 차단
- **분리**: daemon thread + per-strategy try/except → 모니터 장애가 실매매에 영향 없음

18개 테스트 전체 통과. 기존 테스트 회귀 없음 (test_plugin_registry 실패는 Phase 5 이전부터 존재하는 기존 결함).

---

_Verified: 2026-03-12T04:50:00Z_
_Verifier: Claude (gsd-verifier)_
