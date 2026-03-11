---
phase: 02-backtest-quality-gates
plan: 06
subsystem: backtest
tags: [quantstats, report, visualization, is-oos, equity-curve, html]

# Dependency graph
requires:
  - phase: 02-backtest-quality-gates
    plan: 01
    provides: ValidationResult, WindowResult
  - phase: 02-backtest-quality-gates
    plan: 02
    provides: WalkForwardValidator (IS/OOS 분할 데이터)
produces:
  - generate_quantstats_report (engine/backtest/report.py)
  - generate_validation_chart (engine/backtest/report.py)
  - generate_full_report (engine/backtest/report.py)
consumed_by:
  - plan: 07 (CLI/API/Discord 인터페이스에서 리포트 생성 호출)
---

## What was built

Quantstats HTML tearsheet + IS/OOS 윈도우 시각화 차트 + 통합 판정 리포트 생성. 기존 report.py에 3개 함수 추가하여 백테스트 결과를 시각적으로 파악 가능.

## Key decisions

1. **기존 report.py 확장** -- 새 파일 생성 대신 기존 모듈에 함수 추가하여 코드 중복 방지.
2. **matplotlib Agg backend** -- 서버 환경에서 GUI 없이 차트 생성.
3. **backward compatibility** -- 기존 generate_summary, generate_report 함수 유지.

## Key files

### key-files.created
- `tests/test_backtest_report.py` -- 13개 테스트

### key-files.modified
- `engine/backtest/report.py` -- generate_quantstats_report, generate_validation_chart, generate_full_report 추가

## Test results

- 13 tests passing (test_backtest_report.py)
- Quantstats HTML 생성, IS/OOS 차트 PNG 생성, 통합 리포트 HTML 생성 확인

## Deviations

None -- plan 그대로 구현.

## Self-Check: PASSED
