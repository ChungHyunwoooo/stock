---
phase: 02-backtest-quality-gates
plan: 07
subsystem: backtest
tags: [cli, api, discord, rich-table, fastapi, slash-command, history]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    plan: 05
    provides: BacktestRepository history/compare/delete methods
  - phase: 02-backtest-quality-gates
    plan: 06
    provides: report generation functions
produces:
  - API endpoints (api/routers/backtests.py)
  - CLI commands (engine/backtest/history_cli.py)
  - Discord slash commands (engine/interfaces/discord/commands/backtest_history.py)
consumed_by: []
---

## What was built

백테스트 이력 조회/관리를 3개 채널로 제공:
1. **API**: GET /backtests/{id}/history, GET /compare, DELETE endpoints (Phase 2 필드 포함)
2. **CLI**: Rich table 기반 show_history, compare_strategies, delete_history + argparse entry point
3. **Discord**: /백테스트이력 + /백테스트비교 slash commands (DiscordCommandPlugin 패턴)

## Key decisions

1. **기존 backtests.py 확장** -- 새 라우터 파일 대신 기존 API에 history/compare/delete 엔드포인트 추가.
2. **BacktestResponse.from_record** -- Phase 2 필드(slippage_model, fee_rate, wf_result, cpcv_mode) 포함.
3. **CLI show_history returns list[dict]** -- Rich table 출력 + 반환값으로 테스트 용이성 확보.

## Key files

### key-files.created
- `engine/backtest/history_cli.py` -- CLI 이력 조회/비교/삭제
- `engine/interfaces/discord/commands/backtest_history.py` -- Discord 슬래시 커맨드
- `tests/test_backtest_interfaces.py` -- 11개 테스트

### key-files.modified
- `api/routers/backtests.py` -- history, compare, delete_by_strategy 엔드포인트 추가

## Test results

- 11 tests passing (test_backtest_interfaces.py)
- API history/compare/delete + CLI show_history/compare_strategies

## Deviations

- SQLite test fixture에 `check_same_thread=False` 추가 -- FastAPI TestClient의 멀티스레드 환경 대응.

## Self-Check: PASSED
