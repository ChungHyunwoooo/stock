---
phase: 09-production-wiring
verified: 2026-03-12T05:30:00Z
status: passed
score: 11/11 must-haves verified
re_verification: false
---

# Phase 9: Production Wiring Verification Report

**Phase Goal:** 구현 완료된 PositionSizer와 PerformanceMonitor가 프로덕션 실행 경로에 실제로 배선되어 동작한다
**Verified:** 2026-03-12T05:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | orchestrator.process_signal()에서 PositionSizer.calculate()가 호출되어 quantity가 ATR/Kelly 기반으로 계산된다 | VERIFIED | orchestrator.py:139,182 — `size_result = self.position_sizer.calculate(...)` full_auto 및 _compute_quantity 경로 모두 호출 |
| 2 | PortfolioRiskManager.get_allocation_weights()가 주문 전 호출된다 | VERIFIED | orchestrator.py:120,174 — `weights = self.portfolio_risk.get_allocation_weights()` sizing 전 호출, 미등록 전략 차단 후 allocation_weight 추출 |
| 3 | application bootstrap에서 StrategyPerformanceMonitor.run_daemon()이 시작되어 데몬 스레드가 실행된다 | VERIFIED | bootstrap.py:111 — `performance_monitor.run_daemon(session_factory=get_session)` 직접 호출 |

**Score:** 3/3 truths verified

---

## Plan 01 Must-Haves (RISK-02)

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | process_signal()에서 PositionSizer.calculate()가 호출되어 ATR/Kelly 기반 quantity가 계산된다 | VERIFIED | orchestrator.py:139 — `self.position_sizer.calculate(df=ohlcv_df, entry_price=..., side=..., capital=..., timeframe=..., allocation_weight=allocation_weight)` |
| 2 | PortfolioRiskManager가 None이면 process_signal()이 ValueError를 발생시킨다 | VERIFIED | orchestrator.py:84-87 — `if self.portfolio_risk is None: raise ValueError("portfolio_risk is required for semi_auto/auto mode")` |
| 3 | PositionSizer가 None이면 process_signal()이 ValueError를 발생시킨다 | VERIFIED | orchestrator.py:80-83 — `if self.position_sizer is None: raise ValueError("position_sizer is required for semi_auto/auto mode")` |
| 4 | 미등록 전략의 진입이 차단된다 | VERIFIED | orchestrator.py:121-126 — `if signal.strategy_id not in weights:` 차단 후 notifier 발송 |
| 5 | allocation_weight가 PositionSizer.calculate()에 전달된다 | VERIFIED | orchestrator.py:129,145 — `allocation_weight = weights[signal.strategy_id]` → `allocation_weight=allocation_weight` |
| 6 | signal_scanner가 quantity 파라미터 없이 process_signal()을 호출한다 | VERIFIED | signal_scanner.py:403,457 — `self.orchestrator.process_signal(signal)` (quantity= 인자 없음) |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `engine/application/trading/orchestrator.py` | PositionSizer + PortfolioRiskManager mandatory injection + sizing flow | VERIFIED | `position_sizer.calculate` 패턴 4회 등장, ValueError 가드 구현 완료 |
| `tests/trading/test_orchestrator.py` | Updated tests for mandatory injection + sizing wiring | VERIFIED | `test_full_auto_uses_position_sizer`, `test_full_auto_missing_sizer_raises`, `test_full_auto_missing_portfolio_risk_raises`, `test_unregistered_strategy_blocked` 4개 신규 테스트 확인 |

### Key Link Verification (Plan 01)

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| orchestrator.py | position_sizer.py | `position_sizer.calculate()` in process_signal() | WIRED | 라인 139, 182 — full_auto 경로 및 _compute_quantity() 모두 호출 |
| orchestrator.py | portfolio_risk.py | `get_allocation_weights()` in process_signal() | WIRED | 라인 120, 174 — 진입 전 weight 조회 및 allocation_weight 추출 |
| signal_scanner.py | orchestrator.py | `process_signal(signal)` without quantity | WIRED | 라인 403, 457 — quantity= 인자 없이 호출 확인 |

---

## Plan 02 Must-Haves (RISK-01)

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | bootstrap에서 StrategyPerformanceMonitor가 생성되고 run_daemon()이 호출되어 데몬 스레드가 시작된다 | VERIFIED | bootstrap.py:103-111 — `StrategyPerformanceMonitor(...)` 생성 후 즉시 `performance_monitor.run_daemon(session_factory=get_session)` 호출 |
| 2 | TradingRuntime dataclass에 position_sizer, portfolio_risk, performance_monitor가 노출된다 | VERIFIED | bootstrap.py:38-45 — dataclass 3개 필드 모두 존재 |
| 3 | TradingRuntimeConfig에 monitor_interval, monitor_warning_threshold, monitor_critical_sharpe가 설정 가능하다 | VERIFIED | bootstrap.py:27-29 — 3개 필드 모두 기본값과 함께 정의됨 |
| 4 | PositionSizer와 PortfolioRiskManager가 bootstrap에서 생성되어 orchestrator에 주입된다 | VERIFIED | bootstrap.py:72-91 — `PositionSizer(...)` 및 `PortfolioRiskManager(...)` 생성 후 `TradingOrchestrator(..., position_sizer=position_sizer, portfolio_risk=portfolio_risk)` 주입 |
| 5 | 모든 config 값이 외부에서 수정 가능하다 (하드코딩 없음) | VERIFIED | TradingRuntimeConfig 모든 필드가 dataclass 파라미터로 노출, 하드코딩 없음 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `engine/interfaces/bootstrap.py` | Full component assembly with PositionSizer, PortfolioRiskManager, PerformanceMonitor | VERIFIED | `run_daemon` 패턴 확인, 3개 컴포넌트 모두 생성 및 TradingRuntime에 반환 |
| `tests/trading/test_bootstrap.py` | Bootstrap assembly and monitor daemon start tests | VERIFIED | `test_runtime_config_defaults`, `test_runtime_config_custom`, `test_build_runtime_assembles_all_components`, `test_build_runtime_passes_config_to_monitor` 4개 테스트 확인 |

### Key Link Verification (Plan 02)

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| bootstrap.py | performance_monitor.py | `StrategyPerformanceMonitor` + `run_daemon()` | WIRED | 라인 103-111 — 생성 후 즉시 daemon 시작 |
| bootstrap.py | position_sizer.py | `PositionSizer` 생성 + orchestrator 주입 | WIRED | 라인 72-89 — `PositionSizer` 키워드 6회 확인 |
| bootstrap.py | portfolio_risk.py | `PortfolioRiskManager` 생성 + orchestrator 주입 | WIRED | 라인 77-91 — `PortfolioRiskManager` 키워드 6회 확인 |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-----------|-------------|--------|---------|
| RISK-01 | 09-02-PLAN.md | 실매매 전략의 20거래 롤링 윈도우 성과가 백테스트 기준 대비 저하되면 Discord 알림 발송 | SATISFIED | bootstrap.py에서 StrategyPerformanceMonitor 생성 + run_daemon() 호출로 배선 완료 |
| RISK-02 | 09-01-PLAN.md | ATR 또는 Kelly fraction 기반 변동성에 따른 가변 포지션 사이징 | SATISFIED | orchestrator.py에서 PositionSizer.calculate() 호출, allocation_weight 전달, signal_scanner OHLCV 첨부 확인 |

**REQUIREMENTS.md 트레이서빌리티 상태:** RISK-01, RISK-02 모두 Phase 9 Complete로 기록됨 — 코드와 일치.

**고아 요구사항:** 없음. Phase 9에 매핑된 요구사항은 RISK-01, RISK-02 두 개이며, 두 Plan의 `requirements` 필드가 각각 이를 정확히 선언.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (없음) | - | - | - | - |

orchestrator.py, bootstrap.py, signal_scanner.py 스캔 결과 TODO/FIXME/PLACEHOLDER/빈 구현 없음. 모든 핵심 경로가 실제 로직으로 구현됨.

**주목할 설계 결정 (안티패턴 아님):**
- orchestrator.py: `position_sizer`와 `portfolio_risk`는 constructor에서 `None` 기본값 허용 (하위 호환성), 그러나 semi_auto/auto 모드 진입 시 ValueError 발생으로 런타임 강제 — 의도된 패턴
- bootstrap.py: function-scope imports로 순환 import 회피 — 프로젝트 확립 패턴

---

## Human Verification Required

없음. 모든 핵심 배선이 정적 분석으로 확인 가능하며, 테스트 코드가 동작을 직접 검증함.

---

## Gaps Summary

갭 없음. Phase 9 목표 달성:

- **RISK-02**: `orchestrator.process_signal()`에서 `PositionSizer.calculate()`가 OHLCV, capital, allocation_weight를 인자로 호출됨. `PortfolioRiskManager.get_allocation_weights()`가 주문 전 호출됨. 미등록 전략 차단. signal_scanner가 quantity 없이 호출하며 OHLCV를 metadata에 첨부.
- **RISK-01**: `build_trading_runtime()`에서 `StrategyPerformanceMonitor`가 조립되고 `run_daemon(session_factory=get_session)`이 즉시 호출됨. `TradingRuntime` dataclass에 3개 컴포넌트 모두 노출. `TradingRuntimeConfig`의 7개 신규 필드가 모두 외부 설정 가능.

---

_Verified: 2026-03-12T05:30:00Z_
_Verifier: Claude (gsd-verifier)_
