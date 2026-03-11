---
phase: 02-backtest-quality-gates
verified: 2026-03-11T00:00:00Z
status: gaps_found
score: 12/15 must-haves verified
gaps:
  - truth: "Discord 슬래시 커맨드로 백테스트 이력을 조회할 수 있다"
    status: partial
    reason: "BacktestHistoryPlugin이 DEFAULT_COMMAND_PLUGINS에 등록되지 않아 런타임에서 커맨드가 사용 불가"
    artifacts:
      - path: "engine/interfaces/discord/commands/__init__.py"
        issue: "BacktestHistoryPlugin import 및 DEFAULT_COMMAND_PLUGINS 등록 누락"
      - path: "engine/interfaces/discord/commands/backtest_history.py"
        issue: "/백테스트삭제 커맨드 미구현 (plan 07 요구사항)"
    missing:
      - "engine/interfaces/discord/commands/__init__.py 에 BacktestHistoryPlugin import 및 DEFAULT_COMMAND_PLUGINS 추가"
      - "backtest_history.py 에 /백테스트삭제 슬래시 커맨드 구현 (BacktestRepository.delete 호출)"
  - truth: "세 인터페이스 모두 BacktestRepository의 동일한 메서드를 사용한다"
    status: partial
    reason: "Discord 인터페이스가 등록되지 않아 세 인터페이스(API+CLI+Discord) 중 Discord가 미연결"
    artifacts:
      - path: "engine/interfaces/discord/commands/__init__.py"
        issue: "BacktestHistoryPlugin 미등록으로 Discord 인터페이스 비활성화"
    missing:
      - "BacktestHistoryPlugin을 DEFAULT_COMMAND_PLUGINS에 등록"
  - truth: "REQUIREMENTS.md BT-02, BT-05 상태가 구현 완료를 반영한다"
    status: failed
    reason: "walk_forward.py, cpcv.py 모두 구현 완료되어 테스트도 통과하지만 REQUIREMENTS.md는 여전히 [ ] Pending으로 표시"
    artifacts:
      - path: ".planning/REQUIREMENTS.md"
        issue: "BT-02: [ ] Pending, BT-05: [ ] Pending — 실제로는 구현 완료"
    missing:
      - "REQUIREMENTS.md BT-02 체크박스 [x] 로 변경 및 status Complete 로 업데이트"
      - "REQUIREMENTS.md BT-05 체크박스 [x] 로 변경 및 status Complete 로 업데이트"
---

# Phase 02: Backtest Quality Gates Verification Report

**Phase Goal:** 슬리피지 모델 + 워크포워드 OOS + 멀티심볼 검증으로 신뢰 가능한 백테스트 구축
**Verified:** 2026-03-11
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | VolumeAdjustedSlippage 적용 시 수익률이 NoSlippage 대비 낮아진다 | VERIFIED | runner.py _simulate()에 슬리피지 entry/exit 가격 반영, test_backtest_costs.py 통과 |
| 2  | 거래소별 maker/taker 수수료가 JSON 설정에서 로드되어 백테스트에 적용된다 | VERIFIED | exchange_fees.json + FeeModel.get_fee_rate() + runner._fee_rate 연결 |
| 3  | SlippageModel을 교체해도 BacktestRunner의 나머지 로직은 변경 없이 동작한다 | VERIFIED | Protocol 주입, NoSlippage 기본값으로 하위 호환 |
| 4  | DepthCache가 Parquet에서 심볼별 depth 통계를 읽어 VolumeAdjustedSlippage에 공급한다 | VERIFIED | depth_cache.py get_stats() → slippage.py _depth_cache.get_stats() 연결 |
| 5  | WalkForwardValidator가 equity curve를 IS/OOS 윈도우로 분할하고 각 윈도우별 Sharpe 갭을 판정한다 | VERIFIED | walk_forward.py 구현 완료, n_windows=5/train_pct=0.7/gap_threshold=0.5 |
| 6  | OOS Sharpe >= IS Sharpe x 0.5 이면 PASS | VERIFIED | gap_ratio >= 0.5 판정 로직 구현 |
| 7  | 결과가 ValidationResult 형태로 반환되어 CPCV와 동일 인터페이스 | VERIFIED | mode="walk_forward", WindowResult 리스트 반환 |
| 8  | CPCVValidator가 ValidationResult 인터페이스를 반환한다 | VERIFIED | cpcv.py, skfolio CombinatorialPurgedCV 사용, mode="cpcv" |
| 9  | 상관계수 \|r\| < 0.5 인 비상관 심볼을 자동 선택할 수 있다 | VERIFIED | select_uncorrelated_symbols() greedy 구현, max_corr=0.5 |
| 10 | 병렬 백테스트를 실행하고 심볼별 Sharpe를 얻는다 | VERIFIED | ProcessPoolExecutor + _run_symbol_backtest top-level worker |
| 11 | 중앙값 Sharpe >= 0.5 이면 통과 | VERIFIED | MultiSymbolResult.passed = median_sharpe >= threshold |
| 12 | BacktestRunner.run() 완료 시 결과가 자동으로 DB에 저장된다 | VERIFIED | _save_to_db() auto_save=True 기본값 |
| 13 | 전략별 시간순 이력 조회 + 전략 간 횡단 비교 조회 가능 | VERIFIED | get_history()/compare_strategies() API/CLI 모두 구현 |
| 14 | Discord 슬래시 커맨드로 백테스트 이력을 조회할 수 있다 | PARTIAL | 플러그인 파일 존재하나 DEFAULT_COMMAND_PLUGINS 미등록 + /백테스트삭제 미구현 |
| 15 | 세 인터페이스(API+CLI+Discord) 모두 BacktestRepository 동일 메서드 사용 | PARTIAL | API/CLI는 완전 연결, Discord는 미등록 |

**Score:** 13/15 truths verified (2 partial = gaps)

---

## Required Artifacts

| Artifact | Plan | Status | Details |
|----------|------|--------|---------|
| `engine/backtest/slippage.py` | 02-01 | VERIFIED | SlippageModel Protocol, NoSlippage, VolumeAdjustedSlippage 구현 |
| `engine/backtest/fee_model.py` | 02-01 | VERIFIED | FeeModel + load_exchange_fees(), JSON 로드, default 0.001 |
| `engine/backtest/validation_result.py` | 02-01 | VERIFIED | WindowResult, ValidationResult dataclass(slots=True) |
| `engine/data/depth_cache.py` | 02-01 | VERIFIED | DepthCache, get_stats(), save_snapshot(), TTL 7일 |
| `engine/data/depth_collector.py` | 02-01 | VERIFIED | OrderbookDepthCollector, ccxt REST, collect_snapshot(), collect_top_symbols() |
| `config/exchange_fees.json` | 02-01 | VERIFIED | binance spot/futures, upbit spot 수수료 포함 |
| `engine/backtest/runner.py` | 02-01 | VERIFIED | slippage_model/fee_rate 파라미터, _simulate() 연동, _save_to_db() |
| `engine/backtest/walk_forward.py` | 02-02 | VERIFIED | WalkForwardValidator, n=5/0.7/0.5, metrics import 재사용 |
| `engine/backtest/cpcv.py` | 02-03 | VERIFIED | CPCVValidator, skfolio CombinatorialPurgedCV, 동일 인터페이스 |
| `engine/backtest/multi_symbol.py` | 02-04 | VERIFIED | select_uncorrelated_symbols, MultiSymbolValidator, MultiSymbolResult |
| `engine/core/db_models.py` | 02-05 | VERIFIED | slippage_model, fee_rate, wf_result, cpcv_mode, multi_symbol_result 칼럼 추가 |
| `engine/core/repository.py` | 02-05 | VERIFIED | get_history(), compare_strategies(), delete(), delete_by_strategy() |
| `engine/core/database.py` | 02-05 | VERIFIED | _migrate_backtests_phase2(), init_db() 내 호출 |
| `engine/backtest/report.py` | 02-06 | VERIFIED | generate_quantstats_report(), generate_validation_chart(), generate_full_report() |
| `api/routers/backtests.py` | 02-07 | VERIFIED | GET /{strategy_id}/history, GET /compare, DELETE /{id}, DELETE /strategy/{id} |
| `engine/backtest/history_cli.py` | 02-07 | VERIFIED | show_history(), compare_strategies(), delete_history(), argparse main |
| `engine/interfaces/discord/commands/backtest_history.py` | 02-07 | PARTIAL | BacktestHistoryPlugin 구현됨, /백테스트이력+/백테스트비교 있음, /백테스트삭제 없음 |
| `engine/interfaces/discord/commands/__init__.py` | 02-07 | MISSING_WIRING | BacktestHistoryPlugin DEFAULT_COMMAND_PLUGINS 미등록 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `runner.py` | `slippage.py` | `self._slippage_model.calculate_slippage` | WIRED | line 212, 235, 270 |
| `runner.py` | `fee_model.py` | `self._fee_rate` | WIRED | line 75, 218, 244, 278 |
| `slippage.py` | `depth_cache.py` | `self._depth_cache.get_stats` | WIRED | VolumeAdjustedSlippage.__init__, line 66 |
| `depth_collector.py` | `depth_cache.py` | `DepthCache` import + save_snapshot() | WIRED | line 11, 32, 92 |
| `walk_forward.py` | `validation_result.py` | `from engine.backtest.validation_result import` | WIRED | line 8 |
| `walk_forward.py` | `metrics.py` | `from engine.backtest.metrics import compute_sharpe_ratio` | WIRED | line 7 |
| `cpcv.py` | `validation_result.py` | `from engine.backtest.validation_result import` | WIRED | line 10 |
| `cpcv.py` | `metrics.py` | `from engine.backtest.metrics import compute_sharpe_ratio` | WIRED | line 9 |
| `multi_symbol.py` | `runner.py` | `BacktestRunner()` in worker | WIRED | _run_symbol_backtest line 103 |
| `runner.py` | `repository.py` | `BacktestRepository().save` | WIRED | _save_to_db line 158, 173 |
| `database.py` | `db_models.py` | `_migrate_backtests_phase2` in init_db() | WIRED | line 68 |
| `api/backtests.py` | `repository.py` | `_repo.get_history`, `_repo.compare_strategies` | WIRED | line 126, 164 |
| `history_cli.py` | `repository.py` | `BacktestRepository()` | WIRED | line 16 |
| `backtest_history.py` (Discord) | `history_cli.py` | `show_history`, `compare_strategies` import | WIRED | line 71, 89 (lazy import) |
| `backtest_history.py` (Discord) | `control_bot.py` | `DEFAULT_COMMAND_PLUGINS` 등록 | NOT_WIRED | `__init__.py` 에 BacktestHistoryPlugin 미등록 |

---

## Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|---------|
| BT-01 | 02-01 | 거래소별 슬리피지+수수료 모델 적용 | SATISFIED | slippage.py + fee_model.py + runner.py 통합, 테스트 통과 |
| BT-02 | 02-02, 02-06 | Walk-forward OOS 검증 | SATISFIED (code) / PENDING (docs) | walk_forward.py 구현+테스트 통과, REQUIREMENTS.md 미업데이트 |
| BT-03 | 02-04 | 비상관 심볼 다중 검증 | SATISFIED | multi_symbol.py 구현+테스트 통과 |
| BT-04 | 02-05, 02-07 | DB 저장 + 이력 비교 | SATISFIED | runner 자동저장, API/CLI 이력조회 동작 |
| BT-05 | 02-03, 02-06 | CPCV 고도화 검증 | SATISFIED (code) / PENDING (docs) | cpcv.py 구현+테스트 통과, REQUIREMENTS.md 미업데이트 |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `engine/interfaces/discord/commands/__init__.py` | BacktestHistoryPlugin 미등록 | BLOCKER | Discord /백테스트이력, /백테스트비교 커맨드 런타임 사용 불가 |
| `engine/interfaces/discord/commands/backtest_history.py` | /백테스트삭제 커맨드 누락 | WARNING | plan 07 success criteria 부분 미충족 |
| `.planning/REQUIREMENTS.md` | BT-02, BT-05 [ ] Pending | INFO | 문서와 코드 상태 불일치 |

---

## Human Verification Required

### 1. VolumeAdjustedSlippage 실매매 수익률 감소 효과

**Test:** 동일 전략을 NoSlippage와 VolumeAdjustedSlippage로 각각 실행
**Expected:** VolumeAdjustedSlippage 적용 시 final_capital이 더 낮아야 함
**Why human:** 실제 depth 데이터 없이 fallback=0.001 일 때도 방향성이 맞는지 실환경 확인 필요

### 2. quantstats HTML tearsheet 렌더링

**Test:** generate_quantstats_report()로 생성된 HTML 파일을 브라우저에서 열기
**Expected:** Sharpe, Max Drawdown, 수익률 차트가 정상 표시되어야 함
**Why human:** 파일 크기 > 0 확인만으로 HTML 내용 정합성 검증 불가

### 3. Discord 슬래시 커맨드 런타임 동작 (등록 후)

**Test:** BacktestHistoryPlugin 등록 후 Discord 서버에서 /백테스트이력 실행
**Expected:** rich embed에 이력 표시
**Why human:** 봇 런타임 + Discord API 연결 필요

---

## Gaps Summary

**2개 구조적 갭** 및 **1개 문서 갭**이 phase 목표 완전 달성을 막고 있습니다.

**핵심 갭:** `BacktestHistoryPlugin`이 구현되었으나 `engine/interfaces/discord/commands/__init__.py`의 `DEFAULT_COMMAND_PLUGINS`에 등록되지 않아 Discord 인터페이스 전체가 런타임에서 비활성화 상태입니다. 이는 plan 07의 "세 인터페이스 모두 BacktestRepository 동일 메서드 사용" truth를 깨뜨립니다.

**부가 갭:** `/백테스트삭제` 커맨드가 plan 07 success criteria에 명시되었으나 `backtest_history.py`에 구현되지 않았습니다.

**문서 갭:** `walk_forward.py`와 `cpcv.py` 모두 구현 완료되어 16개 테스트가 통과하지만, REQUIREMENTS.md의 BT-02, BT-05가 여전히 `[ ] Pending`으로 표시됩니다.

두 구조적 갭은 동일 파일(`__init__.py`) 수정으로 해결 가능하며, 함께 처리해야 합니다.

---

## Test Evidence

```
tests/test_slippage.py       286줄  — BT-01 슬리피지+depth cache
tests/test_backtest_costs.py 165줄  — BT-01 runner 통합
tests/test_walk_forward.py   101줄  — BT-02 walk-forward (16 passed)
tests/test_cpcv.py            97줄  — BT-05 CPCV (16 passed)
tests/test_multi_symbol.py   271줄  — BT-03 멀티심볼
tests/test_backtest_history.py 448줄 — BT-04 DB 저장+이력
tests/test_backtest_report.py 211줄  — BT-02/05 리포트
tests/test_backtest_interfaces.py 224줄 — BT-04 API+CLI
```

---

_Verified: 2026-03-11_
_Verifier: Claude (gsd-verifier)_
