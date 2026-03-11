---
phase: 07-auto-discovery
plan: "07-01"
subsystem: strategy-discovery
tags: [optuna, tpe, sweep, auto-discovery, walk-forward, multi-symbol]
dependency_graph:
  requires: [backtest-runner, walk-forward-validator, multi-symbol-validator, lifecycle-manager, discord-webhook]
  provides: [indicator-sweeper, sweep-config]
  affects: [strategy-registry]
tech_stack:
  added: [optuna-4.7.0]
  patterns: [bayesian-optimization, tpe-sampler, journal-file-storage]
key_files:
  created:
    - engine/strategy/sweep_config.py
    - engine/strategy/indicator_sweeper.py
    - tests/test_indicator_sweeper.py
  modified: []
decisions:
  - "JournalFileStorage for Optuna storage -- SQLite lock avoidance (STATE.md blocker resolved)"
  - "output_template placeholder substitution for dynamic indicator alias naming"
  - "Minimum 1 condition fallback in _build_strategy when templates are empty"
metrics:
  duration: 2min
  completed: "2026-03-11T20:15:16Z"
---

# Phase 7 Plan 1: IndicatorSweeper -- Optuna TPE 기반 자동 전략 탐색 Summary

Optuna TPE sampler 기반 자동 전략 탐색기 -- SweepConfig로 indicator 파라미터 범위 정의, walk-forward OOS + multi-symbol 이중 검증 후 draft 등록, Discord 통보

## What Was Built

### SweepConfig (engine/strategy/sweep_config.py)
- `IndicatorSearchSpace` dataclass: indicator별 파라미터 탐색 범위 (min, max, step)
- `SweepConfig` dataclass: 전체 sweep 설정 (indicators, n_trials, symbols, thresholds)
- `from_dict()` classmethod로 dict 파싱

### IndicatorSweeper (engine/strategy/indicator_sweeper.py)
- `run()`: Optuna study 생성 (TPE sampler, JournalFileStorage), n_trials 실행, 후보 등록, Discord 통보
- `_objective()`: trial 파라미터 샘플링 -> BacktestRunner -> WalkForwardValidator -> MultiSymbolValidator -> median_sharpe 반환
- `_build_strategy()`: trial 파라미터로 IndicatorDef + ConditionGroup -> StrategyDefinition 생성
- `_register_candidates()`: sharpe_threshold 이상 trial을 definition.json 저장 + LifecycleManager.register() draft 등록
- `_notify_results()`: DiscordWebhookNotifier.send_text()로 후보 목록 + Sharpe 통보

## Task Completion

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests | 1cb2bd6 | tests/test_indicator_sweeper.py |
| 1 (GREEN) | Implementation | a3d9072 | engine/strategy/sweep_config.py, engine/strategy/indicator_sweeper.py |

## Verification

- 7/7 unit tests passed (pytest -x -v)
- Import verification OK
- SweepConfig.from_dict() parses indicator search space
- _build_strategy() generates valid StrategyDefinition from Optuna trial
- _objective() returns median_sharpe on success, -inf on WF/MS failure
- _register_candidates() calls LifecycleManager.register()
- _notify_results() calls DiscordWebhookNotifier.send_text()

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed optuna 4.7.0 dependency**
- **Found during:** Pre-task setup
- **Issue:** optuna not installed in .venv
- **Fix:** pip install optuna
- **Commit:** N/A (runtime dependency)

## Decisions Made

1. JournalFileStorage for Optuna storage -- SQLite lock avoidance (resolves STATE.md Phase 7 blocker)
2. output_template uses `{param_name}` placeholder substitution for dynamic indicator alias naming
3. Minimum 1 condition fallback in _build_strategy when entry/exit templates are empty

## Self-Check: PASSED

- All 3 created files exist on disk
- Both commit hashes (1cb2bd6, a3d9072) found in git log
