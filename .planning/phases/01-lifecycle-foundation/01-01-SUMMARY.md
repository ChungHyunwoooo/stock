---
phase: 01-lifecycle-foundation
plan: 01
subsystem: strategy
tags: [fsm, enum, json, atomic-write, lifecycle]

# Dependency graph
requires: []
provides:
  - LifecycleManager FSM (transition, register, get_strategy, list_by_status)
  - StrategyStatus enum with paper member (5 states)
  - InvalidTransitionError / StrategyNotFoundError exceptions
  - ALLOWED_TRANSITIONS dict (4 forward + 3 reverse)
affects: [01-02, 01-03, 02-cost-aware-backtesting]

# Tech tracking
tech-stack:
  added: []
  patterns: [tempfile-rename atomic write, dict-based FSM transition map]

key-files:
  created:
    - engine/strategy/lifecycle_manager.py
    - tests/test_lifecycle.py
  modified:
    - engine/schema.py
    - tests/test_schema.py

key-decisions:
  - "dict[StrategyStatus, set[StrategyStatus]]로 전이 맵 구현 -- 상태 5개, 전이 7개로 극소 FSM이므로 라이브러리 불필요"
  - "deprecated 상태는 ALLOWED_TRANSITIONS에 미포함 -- 기존 deprecated 전략 전이 차단 (의도된 동작)"
  - "datetime.now(timezone.utc).isoformat()로 UTC 기준 전이 이력 기록"

patterns-established:
  - "Atomic JSON write: tempfile.mkstemp + Path.replace 패턴으로 registry.json 안전 쓰기"
  - "FSM transition map: ALLOWED_TRANSITIONS dict으로 전이 규칙 정의"

requirements-completed: [LIFE-01]

# Metrics
duration: 4min
completed: 2026-03-11
---

# Phase 1 Plan 1: LifecycleManager FSM Summary

**StrategyStatus enum에 paper 추가하고 dict 기반 FSM으로 7개 전이 규칙을 강제하는 LifecycleManager 구현 (TDD, 11 tests)**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-11T02:59:49Z
- **Completed:** 2026-03-11T03:04:47Z
- **Tasks:** 1 (TDD: RED -> GREEN -> REFACTOR)
- **Files modified:** 4

## Accomplishments
- StrategyStatus enum에 paper 멤버 추가 (5개 상태: draft/testing/paper/active/archived)
- LifecycleManager 순수 도메인 서비스 구현: transition, register, get_strategy, list_by_status
- 7개 허용 전이(정방향 4 + 역방향 3) 강제, 불허 전이 시 InvalidTransitionError 발생
- status_history 배열에 {from, to, date, reason} 전이 이력 누적 기록
- registry.json 원자적 쓰기 (tempfile + rename 패턴)
- 기존 deprecated 전략 전이 차단 (ALLOWED_TRANSITIONS에 키 없음)
- 11개 단위 테스트 전량 통과

## Task Commits

Each task was committed atomically (TDD flow):

1. **Task 1 RED: failing tests** - `9fee6f1` (test)
2. **Task 1 GREEN: LifecycleManager implementation** - `8f19589` (feat)
3. **Task 1 REFACTOR:** skipped (code already clean, no duplication)

## Files Created/Modified
- `engine/schema.py` - StrategyStatus enum에 paper 멤버 추가
- `engine/strategy/lifecycle_manager.py` - LifecycleManager FSM + 예외 클래스 + ALLOWED_TRANSITIONS
- `tests/test_lifecycle.py` - 11개 테스트 (전이, 이력, 원자적 쓰기, 등록/조회)
- `tests/test_schema.py` - test_strategy_status_enum 수정 (paper 추가, len==5)

## Decisions Made
- dict[StrategyStatus, set[StrategyStatus]]로 전이 맵 구현 -- python-statemachine 라이브러리는 과잉
- deprecated 상태는 ALLOWED_TRANSITIONS에 미포함 -- 기존 deprecated 전략은 관리 대상 외
- datetime.now(timezone.utc).isoformat()로 UTC 기준 전이 이력 기록

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- .venv가 존재하지 않아 생성 필요 (venv 생성 + pip install로 해결, 1분 소요)
- tests/trading/ 하위 8개 테스트 collection error (mplfinance 미설치) -- 기존 이슈, 본 작업과 무관
- tests/test_broker.py 5개 실패 (upbit_broker 모듈 참조 오류) -- 기존 이슈, 본 작업과 무관

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- LifecycleManager가 Plan 02 (Discord /전략전이 커맨드)와 Plan 03 (레퍼런스 전략 등록)의 기반 제공
- registry.json 원자적 쓰기 패턴 확립, 이후 모든 registry 변경에 재사용
- 전이 이력 기록 구조 확립, Discord Embed 표시에 활용 가능

## Self-Check: PASSED

- All 4 source/test files: FOUND
- Commit 9fee6f1 (RED): FOUND
- Commit 8f19589 (GREEN): FOUND

---
*Phase: 01-lifecycle-foundation*
*Completed: 2026-03-11*
