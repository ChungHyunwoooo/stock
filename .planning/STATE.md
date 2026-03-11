# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-11)

**Core value:** 수익을 주는 자동화 봇 — 전략 발굴부터 실매매까지 사람 개입 없이 돌아가되, 성과 저하 시 즉시 알림으로 제어권 유지
**Current focus:** Phase 1 — Lifecycle Foundation

## Current Position

Phase: 1 of 8 (Lifecycle Foundation)
Plan: 0 of 3 in current phase
Status: Ready to plan
Last activity: 2026-03-11 — Roadmap created

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: 의존성 체인 강제 — 비용 모델 → 워크포워드 → 페이퍼 → 포트폴리오 리스크 → 모니터링 → 탐색 순서 변경 불가
- [Init]: 성과 저하 시 알림 후 수동 교체 — 자동 교체 미구현 (73% 봇 실패 근거)
- [Init]: vectorbt(sweep 속도) + 기존 bt(단일 전략 리포팅) 병용 — 기존 bt 교체 불필요

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: vectorbt 0.28.4 next_open fill price 지원 여부 — 플래닝 전 API 검증 필요
- [Phase 4]: riskfolio-lib 7.x HRP API — 6.x 예제와 차이 있을 수 있음, 플래닝 전 버전 확인 필요
- [Phase 7]: Optuna + ProcessPoolExecutor SQLite 잠금 충돌 — JournalFileStorage 필요 여부 확인

## Session Continuity

Last session: 2026-03-11
Stopped at: Roadmap created, STATE.md initialized
Resume file: None
