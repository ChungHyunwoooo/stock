---
phase: 02-backtest-quality-gates
plan: 02
subsystem: backtest
tags: [walk-forward, oos, sharpe, validation, overfitting]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    plan: 01
    provides: ValidationResult, WindowResult, compute_sharpe_ratio
produces:
  - WalkForwardValidator (engine/backtest/walk_forward.py)
consumed_by:
  - plan: 03 (CPCV -- 동일 인터페이스)
---

## What was built

WalkForwardValidator -- equity curve를 n개 윈도우(default 5)로 분할하여 IS(70%)/OOS(30%) Sharpe 갭을 판정하는 과적합 검증기.

## Key decisions

1. **Equity curve 직접 분할** -- OHLCV split 대신 equity curve를 직접 분할. 단독 테스트 가능하고 plan 독립성 유지.
2. **compute_sharpe_ratio 재사용** -- metrics.py에서 import하여 코드 중복 제거.
3. **Negative gap_ratio clamping** -- IS/OOS 부호가 반대인 경우 gap_ratio를 0으로 클램핑.

## Key files

### key-files.created
- `engine/backtest/walk_forward.py` -- WalkForwardValidator 클래스
- `tests/test_walk_forward.py` -- 8개 테스트

### key-files.modified
(none)

## Test results

- 8 tests passing (test_walk_forward.py)
- Monotonic equity → all PASS, random walk → some FAIL, too short → ValueError

## Deviations

None -- plan 그대로 구현.

## Self-Check: PASSED
