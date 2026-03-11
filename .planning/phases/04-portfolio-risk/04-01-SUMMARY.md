---
phase: 04-portfolio-risk
plan: 01
subsystem: strategy
tags: [position-sizing, kelly-criterion, atr, risk-parity, inverse-variance]

# Dependency graph
requires:
  - phase: 03-paper-trading
    provides: PaperBroker + PromotionGate (전략 생명주기 paper->active 승격)
provides:
  - PositionSizer 통합 오케스트레이터 (ATR+Kelly x position_size_factor x allocation_weight)
  - ScalpRiskConfig.for_timeframe() 타임프레임별 프리셋
  - calculate_risk_parity_weights() Risk Parity 자본 배분
affects: [04-02-portfolio-risk, 05-performance-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns: [inverse-variance-weighting, 2-pass-cap-algorithm, fractional-kelly]

key-files:
  created:
    - engine/strategy/position_sizer.py
    - engine/strategy/risk_parity.py
    - tests/test_position_sizer.py
    - tests/test_risk_parity.py
  modified:
    - engine/strategy/scalping_risk.py

key-decisions:
  - "Kelly cap 제거 -- RiskManager.position_size_factor()가 드로다운 시 축소하므로 별도 cap 불필요"
  - "Risk Parity numpy 직접 구현 -- riskfolio-lib 미사용, 역분산 가중 10줄 핵심"
  - "2-pass cap 알고리즘 -- max cap과 min floor를 분리 처리하여 재정규화 시 cap 위반 방지"
  - "n*max_cap < 1.0이면 cap 비적용 -- 수학적 불가능 제약 자동 우회"

patterns-established:
  - "PositionSizer 곱산 합산: ATR+Kelly qty x position_size_factor x allocation_weight"
  - "ScalpRiskConfig.for_timeframe() classmethod 프리셋 패턴"

requirements-completed: [RISK-02]

# Metrics
duration: 6min
completed: 2026-03-11
---

# Phase 4 Plan 01: Position Sizing + Risk Parity Summary

**ATR+Kelly 동적 포지션 사이징 + 역분산 가중 Risk Parity 자본 배분으로 고정 2% 사이징 완전 대체**

## Performance

- **Duration:** 6min
- **Started:** 2026-03-11T18:57:51Z
- **Completed:** 2026-03-11T19:04:09Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- PositionSizer가 ATR+Kelly x position_size_factor x allocation_weight 곱산으로 동적 수량 반환
- 거래 이력 20건 기준 Kelly 적용/미적용 자동 분기
- Risk Parity가 변동성에 반비례하는 배분 반환 (역분산 가중)
- ScalpRiskConfig.for_timeframe()으로 스캘핑/데이트레이딩/스윙 3단계 프리셋 자동 선택

## Task Commits

Each task was committed atomically:

1. **Task 1: scalping_risk.py 타임프레임 프리셋 + PositionSizer 통합 모듈**
   - `2e6f987` (test: failing tests for PositionSizer)
   - `0597380` (feat: implement PositionSizer + for_timeframe)
2. **Task 2: Risk Parity 자본 배분 모듈**
   - `61f8ef6` (test: failing tests for Risk Parity)
   - `c97cbd9` (feat: implement Risk Parity with inverse-variance weighting)

## Files Created/Modified
- `engine/strategy/position_sizer.py` - 통합 포지션 사이징 오케스트레이터 (PositionSizer, PositionSizeResult)
- `engine/strategy/risk_parity.py` - Risk Parity 자본 배분 (calculate_risk_parity_weights, RiskParityConfig)
- `engine/strategy/scalping_risk.py` - ScalpRiskConfig.for_timeframe() classmethod + Kelly cap 제거
- `tests/test_position_sizer.py` - PositionSizer 7개 테스트
- `tests/test_risk_parity.py` - Risk Parity 6개 테스트

## Decisions Made
- Kelly cap 제거: `effective_risk_pct = kelly_pct` (기존: `min(kelly_pct, risk_per_trade_pct)`) -- RiskManager.position_size_factor()가 드로다운 축소 담당
- Risk Parity numpy 직접 구현: 역공분산 행 합 기반, 음수 가중치 시 역분산 fallback
- 2-pass cap 알고리즘: max cap pass -> min floor pass 분리로 재정규화 시 cap 위반 방지
- `n * max_cap < 1.0`이면 cap 미적용 (수학적 불가능 제약)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _apply_caps 재정규화 시 max cap 위반**
- **Found during:** Task 2 (Risk Parity)
- **Issue:** 단순 cap + 재정규화 방식에서 재정규화가 cap을 초과시킴
- **Fix:** 2-pass 잠금 알고리즘으로 교체 (max cap pass -> min floor pass 분리, 잠긴 전략 제외 잔여분 재배분)
- **Files modified:** engine/strategy/risk_parity.py
- **Verification:** test_max_allocation_cap 통과
- **Committed in:** c97cbd9

**2. [Rule 1 - Bug] 테스트 수학적 불가능 조건**
- **Found during:** Task 2 (Risk Parity)
- **Issue:** 2개 전략 + max_cap=0.4로는 sum=1.0 불가능 (2*0.4=0.8)
- **Fix:** 테스트를 3개 전략으로 수정, 구현에 feasibility guard 추가
- **Files modified:** tests/test_risk_parity.py, engine/strategy/risk_parity.py
- **Verification:** 전체 6개 테스트 통과
- **Committed in:** c97cbd9

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** cap 알고리즘 정확성 보장. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PositionSizer와 Risk Parity가 04-02 PortfolioRiskManager에서 사용 가능
- PortfolioRiskManager가 allocation_weight를 calculate_risk_parity_weights()에서 받아 PositionSizer.calculate()에 전달하는 구조 준비 완료

---
*Phase: 04-portfolio-risk*
*Completed: 2026-03-11*
