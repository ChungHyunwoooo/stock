---
phase: 02-backtest-quality-gates
plan: 03
subsystem: backtest
tags: [cpcv, cross-validation, purging, combinatorial, overfitting]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    plan: 01
    provides: ValidationResult, WindowResult, compute_sharpe_ratio
  - phase: 02-backtest-quality-gates
    plan: 02
    provides: WalkForwardValidator (동일 인터페이스 참조)
produces:
  - CPCVValidator (engine/backtest/cpcv.py)
consumed_by:
  - plan: 05 (backtest history DB -- ValidationResult 저장)
---

## What was built

CPCVValidator -- equity curve를 n_groups(default 5)로 분할 후 조합적 IS/OOS 경로를 생성하여 Sharpe 갭 pass_rate로 과적합 판정. WalkForwardValidator와 동일 ValidationResult 인터페이스.

## Key decisions

1. **Purge gap 적용** -- IS/OOS 경계에 purge_pct(default 1%) 버퍼로 정보 누수 차단.
2. **Pass rate 기반 판정** -- 개별 경로가 아닌 전체 경로 중 pass 비율(min_pass_rate=0.6)로 overall 판정.
3. **동일 인터페이스** -- mode="cpcv"만 다르고 ValidationResult/WindowResult 그대로 반환.

## Key files

### key-files.created
- `engine/backtest/cpcv.py` -- CPCVValidator 클래스
- `tests/test_cpcv.py` -- 8개 테스트

### key-files.modified
(none)

## Test results

- 8 tests passing (test_cpcv.py)
- Monotonic equity → high pass rate, interface compatibility with WalkForward confirmed

## Deviations

None -- plan 그대로 구현.

## Self-Check: PASSED
