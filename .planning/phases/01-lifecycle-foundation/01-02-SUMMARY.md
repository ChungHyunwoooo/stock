---
phase: 01-lifecycle-foundation
plan: 02
subsystem: discord
tags: [discord, slash-command, autocomplete, embed, ui-view, lifecycle, api]

# Dependency graph
requires:
  - phase: 01-lifecycle-foundation/01
    provides: LifecycleManager FSM (transition, register, get_strategy, list_by_status)
provides:
  - LifecycleCommandPlugin with /전략전이 slash command
  - strategy_autocomplete and target_status_autocomplete functions
  - TransitionConfirmView (confirm/cancel buttons)
  - build_transition_embed for Discord Embed output
  - API PATCH /strategies/{id}/status with LifecycleManager validation
  - lifecycle_manager field on DiscordBotContext
affects: [01-03, 02-cost-aware-backtesting]

# Tech tracking
tech-stack:
  added: []
  patterns: [module-level test override for discord.py autocomplete, discord.ui.View confirm/cancel pattern]

key-files:
  created:
    - engine/interfaces/discord/commands/lifecycle.py
    - tests/test_lifecycle_discord.py
  modified:
    - engine/interfaces/discord/autocomplete.py
    - engine/interfaces/discord/context.py
    - engine/interfaces/discord/commands/__init__.py
    - api/routers/strategies.py
    - tests/trading/test_plugin_registry.py

key-decisions:
  - "discord.py autocomplete 함수는 정확히 2-3개 파라미터만 허용 -- _manager 키워드 대신 모듈 레벨 _lifecycle_manager_override로 테스트 주입"
  - "API router에서 registry.json에 없는 전략은 기존 DB-only 로직 유지 -- 하위 호환성 보장"
  - "TransitionConfirmView timeout=60초 -- 확인/취소 없이 1분 경과 시 자동 만료"

patterns-established:
  - "Module-level override: _lifecycle_manager_override 패턴으로 discord.py 서명 제약 우회하면서 테스트 가능"
  - "Discord Confirm View: discord.ui.View + green/red Button 패턴으로 파괴적 동작 전 확인"

requirements-completed: [LIFE-01]

# Metrics
duration: 9min
completed: 2026-03-11
---

# Phase 1 Plan 2: Discord Lifecycle Command & API Integration Summary

**Discord /전략전이 슬래시 커맨드(autocomplete + 확인/취소 View + Embed 결과) 및 API PATCH 엔드포인트에 LifecycleManager FSM 검증 연동 (TDD, 9 discord tests)**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-11T03:08:04Z
- **Completed:** 2026-03-11T03:16:42Z
- **Tasks:** 2 (Task 1 TDD, Task 2 direct)
- **Files modified:** 7

## Accomplishments
- /전략전이 slash command with strategy_id + target_status autocomplete parameters
- strategy_autocomplete: 등록된 전략을 "{name} ({id})" Choice로 반환, 필터링 지원
- target_status_autocomplete: 선택된 전략의 허용 전이 대상만 반환 (ALLOWED_TRANSITIONS 기반)
- TransitionConfirmView: 확인(green) 버튼 클릭 시 전이 수행 + Embed 결과, 취소(red) 시 메시지만
- InvalidTransitionError/StrategyNotFoundError 발생 시 에러 Embed 응답
- API PATCH /strategies/{id}/status에 registry.json 전략 대상 FSM 검증 추가
- DiscordBotContext에 lifecycle_manager 필드 추가 (default_factory)
- 9개 Discord 테스트 + 기존 11개 lifecycle 테스트 전량 통과

## Task Commits

Each task was committed atomically (TDD flow for Task 1):

1. **Task 1 RED: failing tests** - `8e12d34` (test)
2. **Task 1 GREEN: Discord lifecycle command plugin** - `7c7ed31` (feat)
3. **Task 2: API router LifecycleManager integration** - `19bebd2` (feat)
4. **Fix: autocomplete signature for discord.py validation** - `9866048` (fix)

## Files Created/Modified
- `engine/interfaces/discord/commands/lifecycle.py` - LifecycleCommandPlugin, TransitionConfirmView, build_transition_embed
- `engine/interfaces/discord/autocomplete.py` - strategy_autocomplete, target_status_autocomplete 추가
- `engine/interfaces/discord/context.py` - lifecycle_manager 필드 추가
- `engine/interfaces/discord/commands/__init__.py` - LifecycleCommandPlugin 등록
- `api/routers/strategies.py` - PATCH /status에 LifecycleManager 전이 검증 추가
- `tests/test_lifecycle_discord.py` - 9개 테스트 (autocomplete, plugin, view, embed)
- `tests/trading/test_plugin_registry.py` - lifecycle 플러그인 추가 반영

## Decisions Made
- discord.py autocomplete 함수는 정확히 2-3개 파라미터만 허용 (내부 inspect 검증) -- _manager 키워드 인자 대신 모듈 레벨 _lifecycle_manager_override 변수로 테스트 주입
- API router에서 record.name으로 registry.json 조회 -- registry.json에 없으면 기존 DB-only 로직 유지 (하위 호환)
- TransitionConfirmView timeout=60초 설정

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] discord.py autocomplete 서명 검증 오류 수정**
- **Found during:** Task 1 GREEN (전체 테스트 스위트 실행 시)
- **Issue:** discord.py `app_commands.autocomplete`가 콜백 파라미터 수를 엄격히 검증 (2-3개만 허용). `_manager=None` 키워드 인자 추가 시 TypeError 발생
- **Fix:** `_manager` 키워드 제거, 모듈 레벨 `_lifecycle_manager_override` 변수로 테스트 주입 방식 변경
- **Files modified:** engine/interfaces/discord/autocomplete.py, tests/test_lifecycle_discord.py
- **Verification:** test_plugin_registry + test_lifecycle_discord 전량 통과
- **Committed in:** `9866048`

**2. [Rule 1 - Bug] test_plugin_registry 기대값 업데이트**
- **Found during:** Task 1 완료 후 전체 스위트 회귀 검사
- **Issue:** test_discord_command_registry_registers_all_groups가 정확히 5개 플러그인만 기대 -- lifecycle 추가로 6개가 됨
- **Fix:** 기대값 리스트에 "lifecycle" 추가
- **Files modified:** tests/trading/test_plugin_registry.py
- **Verification:** 전체 테스트 스위트 통과 (5 pre-existing failures only)
- **Committed in:** `9866048`

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
- mplfinance 미설치로 테스트 collection 실패 -- pip install로 해결 (기존 이슈, 01-01에서도 발생)
- discord.ui.button callback 호출 방식: `callback(interaction)` (self와 button은 자동 주입) -- 테스트에서 3번 시행착오 후 올바른 호출 패턴 확인

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Discord /전략전이 커맨드와 API 엔드포인트가 LifecycleManager를 통해 전이 검증 수행
- Plan 03 (레퍼런스 전략 등록)의 전략이 Discord에서 상태 관리 가능
- Phase 2 (Cost-Aware Backtesting)에서 전략 상태 기반 파이프라인 분기 가능

## Self-Check: PASSED

- All 7 source/test files: FOUND
- Commit 8e12d34 (RED): FOUND
- Commit 7c7ed31 (GREEN): FOUND
- Commit 19bebd2 (API router): FOUND
- Commit 9866048 (autocomplete fix): FOUND

---
*Phase: 01-lifecycle-foundation*
*Completed: 2026-03-11*
