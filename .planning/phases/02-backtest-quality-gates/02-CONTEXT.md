# Phase 2: Backtest Quality Gates - Context

**Gathered:** 2026-03-11
**Status:** Ready for planning

<domain>
## Phase Boundary

백테스트 결과가 실매매 비용과 과적합 위험을 반영하여 신뢰할 수 있는 전략 선별 기준이 된다. SlippageModel 인터페이스 + VolumeAdjustedSlippage 구현, Walk-forward OOS 검증기, CPCV 대체 모드, 멀티심볼 병렬 백테스트 + 안정성 검증, 백테스트 결과 DB 저장 + 이력 비교 조회를 포함한다.

</domain>

<decisions>
## Implementation Decisions

### Slippage/Fee 모델 설계
- VolumeAdjustedSlippage: Orderbook depth 기반 슬리피지 계산
- 거래소별 수수료: JSON 설정 파일로 관리 (maker/taker 수수료율)
- Orderbook depth 데이터: 실시간 WebSocket 수집 + Parquet 캐시
  - 수집 대상: 24h 거래량 Top 50 심볼, 일단위 갱신
  - 수집 간격: 1분 스냅샷, Parquet 저장 (기존 OHLCV 캐시와 동일 포맷)
  - 백테스트 시: 캐시된 depth 통계치(평균 스프레드, depth 분포) 사용
- BacktestRunner 통합: SlippageModel 프로토콜 주입 방식
  - 기본값 = NoSlippage(0), VolumeAdjustedSlippage는 선택적 적용
  - 동일 전략에 슬리피지 적용 전/후 비교 가능

### Walk-forward 검증 규칙
- IS/OOS 분할: 70% / 30%, 5개 롤링 윈도우
- 성과 갭 임계치: OOS Sharpe >= IS Sharpe x 0.5 (50% 유지)
- CPCV: Walk-forward의 대체 모드 — 같은 인터페이스로 모드만 전환, 병행 실행 아님
- 결과 출력: 상세 리포트 + 차트 (quantstats 연동)
  - 윈도우별 IS/OOS Sharpe, 성과 갭, 판정(PASS/FAIL)
  - equity curve 시각화, IS/OOS 분할 시각화, 통계 테이블
  - 최종 통합 판정 포함

### 멀티심볼 안정성 기준
- 심볼 선택: 상관계수 기반 자동 선택
  - 90일 일간 수익률 기준 Pearson 상관계수
  - |상관계수| < 0.5인 심볼만 선택
- 통과 기준: 전체 심볼 Sharpe의 중앙값(median) >= 0.5
- 실행 방식: ProcessPoolExecutor 병렬 (기존 ParallelOptimizer 패턴 활용)

### 결과 저장 및 비교
- BacktestRecord 스키마 확장: slippage_model, fee_rate, wf_result(PASS/FAIL), cpcv_mode, multi_symbol_result 칼럼 추가
- 자동 저장: BacktestRunner.run() 완료 시 항상 자동 DB 저장 (저장 실패는 warning, backtest 자체는 실패 아님)
- 이력 비교: 전략 내 시간순 이력 + 전략 간 횡단 비교 둘 다 지원 (쿼리 파라미터로 모드 선택)
- 인터페이스: CLI(rich table) + API(/backtests/{strategy_id}/history) + Discord 커맨드 모두 제공
- DB 관리: 삭제/수정/초기화 기능 모두 구현 — CLI + API + Discord 모두 제공

### Claude's Discretion
- SlippageModel 프로토콜 상세 설계 (메서드 시그니처, 파라미터)
- Orderbook depth 수집 WebSocket 구현 상세 (기존 binance_ws.py 확장 vs 별도 모듈)
- CPCV 알고리즘 구현 세부 (조합 수, purging window)
- 상관계수 기반 심볼 선택 시 Top 50에서 최적 조합 선택 알고리즘
- quantstats 리포트 레이아웃 상세
- Discord 커맨드 UX 상세 (슬래시 커맨드명, Embed 레이아웃)

</decisions>

<specifics>
## Specific Ideas

- Orderbook depth는 욕심은 전체이나 잡코인 제외 — 24h 거래량 Top 50으로 자동 싱크
- 슬리피지 적용 전/후 수익률 비교가 핵심 검증 포인트 (BT-01 success criteria)
- CPCV는 walk-forward와 배타적 — 동일 인터페이스로 모드만 전환
- DB 관리(삭제/수정/초기화)를 CLI, API, Discord 어디서든 동일하게 가능해야 함

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BacktestRunner` (`engine/backtest/runner.py`): 핵심 시뮬레이션 엔진 — SlippageModel 주입 포인트 추가 필요
- `BacktestResult` dataclass: 기본 메트릭 포함, 확장 가능
- `metrics.py`: compute_sharpe_ratio, compute_max_drawdown 등 — walk-forward 윈도우별 재사용
- `ParallelOptimizer` (`engine/backtest/parallel_optimizer.py`): ProcessPoolExecutor 병렬 패턴 — 멀티심볼 병렬에 패턴 재사용
- `GridOptimizer` (`engine/backtest/optimizer.py`): 파라미터 그리드 서치 — _set_nested 유틸리티 재사용
- `BacktestRecord` (`engine/core/db_models.py`): 기존 DB 모델 — 칼럼 확장 필요
- `binance_ws.py` (`engine/data/binance_ws.py`): WebSocket 인프라 — depth 수집에 확장 가능
- `ohlcv_cache.py` (`engine/data/ohlcv_cache.py`): Parquet 캐시 패턴 — depth 캐시에 동일 패턴 적용

### Established Patterns
- Port/Adapter: SlippageModel을 프로토콜로 정의하여 주입 (기존 BrokerPort 패턴)
- JSON 설정: config/ 디렉토리에 거래소별 수수료 설정 추가 (기존 broker.json 패턴)
- Parquet 캐시: pyarrow 기반 OHLCV 캐시와 동일 저장 방식
- Repository 패턴: BacktestRepository로 DB CRUD 제공 (기존 repository.py 패턴)

### Integration Points
- `BacktestRunner.run()`: SlippageModel 파라미터 추가, 자동 DB 저장 로직 삽입
- `BacktestRunner._simulate()`: 슬리피지/수수료 적용 로직 삽입 (entry/exit 가격 조정)
- `api/routers/backtests.py`: 이력 비교 엔드포인트 추가
- Discord bot: 백테스트 이력 조회/관리 커맨드 추가

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-backtest-quality-gates*
*Context gathered: 2026-03-11*
