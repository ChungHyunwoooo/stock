---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 11-01-PLAN.md
last_updated: "2026-03-12T06:23:54.908Z"
last_activity: 2026-03-12 — Plan 10-01 complete (EventNotifier wired into bootstrap/BacktestRunner/IndicatorSweeper)
progress:
  total_phases: 11
  completed_phases: 11
  total_plans: 27
  completed_plans: 27
  percent: 96
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-11)

**Core value:** 수익을 주는 자동화 봇 — 전략 발굴부터 실매매까지 사람 개입 없이 돌아가되, 성과 저하 시 즉시 알림으로 제어권 유지
**Current focus:** Phase 10 — Event Notification Wiring

## Current Position

Phase: 10 of 11 (Event Notification Wiring)
Plan: 1 of 1 in current phase
Status: In Progress
Last activity: 2026-03-12 — Plan 10-01 complete (EventNotifier wired into bootstrap/BacktestRunner/IndicatorSweeper)

Progress: [██████████] 96%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 4min
- Total execution time: 0.12 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-lifecycle-foundation | 2/3 | 7min | 4min |

**Recent Trend:**
- Last 5 plans: 01-01 (4min), 01-03 (3min)
- Trend: -

*Updated after each plan completion*
| Phase 01 P02 | 9min | 2 tasks | 7 files |
| Phase 02 P01 | 5min | 2 tasks | 9 files |
| Phase 02 P04 | 3min | 2 tasks | 2 files |
| Phase 02 P05 | 4min | 2 tasks | 5 files |
| Phase 03 P01 | 7min | 2 tasks | 6 files |
| Phase 03 P02 | 8min | 2 tasks | 10 files |
| Phase 04 P01 | 6min | 2 tasks | 5 files |
| Phase 04 P02 | 4min | 2 tasks | 3 files |
| Phase 05 P01 | 2min | 1 tasks | 5 files |
| Phase 05 P02 | 2min | 1 tasks | 4 files |
| Phase 06 P01 | 2min | 2 tasks | 4 files |
| Phase 07 P01 | 2min | 1 tasks | 3 files |
| Phase 08 P01 | 3min | 2 tasks | 11 files |
| Phase 08 P02 | 3min | 2 tasks | 6 files |
| Phase 09 P02 | 3min | 2 tasks | 2 files |
| Phase 09 P01 | 12min | 2 tasks | 9 files |
| Phase 10 P01 | 4min | 2 tasks | 4 files |
| Phase 11 P01 | 6min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: 의존성 체인 강제 — 비용 모델 → 워크포워드 → 페이퍼 → 포트폴리오 리스크 → 모니터링 → 탐색 순서 변경 불가
- [Init]: 성과 저하 시 알림 후 수동 교체 — 자동 교체 미구현 (73% 봇 실패 근거)
- [Init]: vectorbt(sweep 속도) + 기존 bt(단일 전략 리포팅) 병용 — 기존 bt 교체 불필요
- [01-01]: dict[StrategyStatus, set[StrategyStatus]]로 FSM 전이 맵 구현 — 라이브러리 불필요
- [01-01]: deprecated 상태는 ALLOWED_TRANSITIONS에 미포함 — 기존 deprecated 전략 전이 차단
- [01-01]: UTC 기준 ISO format으로 전이 이력 기록
- [01-03]: LifecycleManager.register()로 registry.json에 원자적 등록 -- status_history 자동 초기화
- [01-03]: entry/exit 조건은 simplified 표현 -- divergence 정밀 조건은 Phase 2 condition_evaluator 확장 후
- [Phase 01-02]: discord.py autocomplete 함수 2-3 파라미터 제한 -- 모듈 레벨 override로 테스트 주입
- [Phase 01-02]: API router registry.json 미등록 전략은 기존 DB-only 로직 유지 -- 하위 호환
- [Phase 02]: SlippageModel Protocol with calculate_slippage(symbol, side, order_size_usd, price) -> float
- [Phase 02]: BacktestRunner backward compatible: no-arg constructor defaults to NoSlippage + fee_rate=0.0
- [02-04]: Greedy correlation selection: first symbol always included, add if |corr| < max_corr with all selected
- [02-04]: _validate_sequential for mock-friendly testing without ProcessPoolExecutor pickle issues
- [02-04]: Failed symbol backtests skipped with warning, not fatal -- partial results accepted
- [02-05]: Auto-save uses try/except with logger.warning -- DB failure never blocks backtest result
- [02-05]: Migration uses PRAGMA table_info + ALTER TABLE ADD COLUMN -- no Alembic dependency
- [02-05]: slippage_model stored as class name (type().__name__) in BacktestRecord
- [03-01]: strategy_id defaults to "default" for backward compatibility with existing PaperBroker() callers
- [03-01]: DB failure in save_balance_snapshot never blocks trade execution (try/except + logger.warning)
- [03-01]: PaperPnlSnapshot upsert via ORM query-then-update for SQLAlchemy session consistency
- [03-01]: TradeRepository.list_open extended with strategy_name + broker filters (backward compatible)
- [03-02]: LifecycleManager.transition() paper->active requires gate/gate_config/session -- other transitions unaffected
- [03-02]: Sharpe skip when < 2 daily data points (passed=True) -- insufficient data should not block
- [03-02]: Max DD comparison: actual >= threshold (both negative) -- -0.10 >= -0.20 means OK
- [03-02]: PromotionConfirmView timeout 120s -- longer than TransitionConfirmView for higher-stakes decision
- [Phase 04]: Kelly cap 제거 -- RiskManager.position_size_factor()가 드로다운 축소 담당
- [Phase 04]: Risk Parity numpy 직접 구현 -- riskfolio-lib 미사용, 역분산 가중
- [04-02]: PortfolioRiskManager injected via constructor (None default) for backward compatibility
- [04-02]: Data < 10 points treated as corr=0 (allow entry) to avoid false blocks on new strategies
- [04-02]: Strategy override threshold checked per strategy_id in gate
- [05-01]: Pure Python Sharpe (mean/std) -- no numpy dependency for monitor
- [05-01]: set->sorted list->set for paused_strategies JSON serialization
- [05-01]: Daemon thread with per-strategy try/except -- one failure never blocks others
- [05-02]: getattr for snapshot fields in Discord notifier -- avoids circular import of PerformanceSnapshot
- [05-02]: send_performance_alert replaces send_text in handlers -- richer embed vs plain text
- [Phase 06-01]: EventNotifier wraps NotificationPort.send_text() -- no port interface changes
- [Phase 06-01]: LifecycleManager callbacks use try/except -- callback failure never blocks transition
- [Phase 06-01]: TradingOrchestrator event_notifier defaults to None for backward compatibility
- [Phase 07]: JournalFileStorage for Optuna storage -- SQLite lock avoidance
- [Phase 08]: DashboardDataService wraps repos directly -- no FastAPI layer (anti-pattern compliance)
- [Phase 08]: 10s auto-refresh for sweep (faster than 30s health -- sweep changes rapidly)
- [Phase 09]: position_sizer exposed on TradingRuntime (not injected into orchestrator -- orchestrator has no position_sizer param)
- [Phase 09]: Transient metadata pattern: ohlcv_df/returns stripped before JSON persistence, restored after processing
- [Phase 10]: Bootstrap try/except wraps post-event_notifier init only -- creation failure falls through
- [Phase 10]: IndicatorSweeper _notify_results (summary) preserved alongside EventNotifier (per-candidate) -- role separation
- [Phase 11]: backtest_repo optional param (None default) -- zero impact on existing callers
- [Phase 11]: CPCV ValueError returns -inf -- short equity curves silently pruned, same as WF failure

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: vectorbt 0.28.4 next_open fill price 지원 여부 — 플래닝 전 API 검증 필요
- [Phase 4]: riskfolio-lib 7.x HRP API — 6.x 예제와 차이 있을 수 있음, 플래닝 전 버전 확인 필요
- [Phase 7]: Optuna + ProcessPoolExecutor SQLite 잠금 충돌 — JournalFileStorage 필요 여부 확인

## Session Continuity

Last session: 2026-03-12T06:23:54.905Z
Stopped at: Completed 11-01-PLAN.md
Resume file: None
