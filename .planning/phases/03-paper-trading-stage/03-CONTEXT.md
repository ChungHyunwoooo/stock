# Phase 3: Paper Trading Stage - Context

**Gathered:** 2026-03-11
**Status:** Ready for planning

<domain>
## Phase Boundary

백테스트를 통과한 전략이 실자본 투입 전 실시간 시장에서 최소 기간 검증을 받고, 정량 기준 충족 시에만 실매매로 승격된다. PaperBroker 상태 영속화(포지션/잔고/PnL/미체결주문/세션 메타), 성과 조회(CLI/API/Discord), Paper→Live 승격 게이트(자동 기준 검증 + Discord 알림 + 수동 승격)를 포함한다.

</domain>

<decisions>
## Implementation Decisions

### 글로벌 원칙: 하드코딩 금지
- 모든 수치/임계치는 config 파일 기반 + 전략별 오버라이드 가능
- 이 원칙은 Phase 3뿐 아니라 이후 전 Phase에 적용

### PaperBroker 영속화
- **저장 범위: 전체** — 포지션 + 잔고 + 일별 PnL 스냅샷 + 미체결 주문 + 전략별 세션 메타데이터
- **저장소: 기존 SQLite DB 확장** — `paper_positions`, `paper_balances`, `paper_pnl_snapshots` 등 테이블 추가. 기존 `engine/core/database.py` + Repository 패턴 재사용
- **PnL 스냅샷: 이중 기록** — 거래 발생 시마다 누적 PnL 기록 + 일별 1회 스냅샷. 거래별 수익 곡선 + 일간 성과 분석 둘 다 지원
- **재시작 시 미체결 주문: 전부 취소** — 포지션/잔고만 복원, 미체결 주문은 자동 취소. Paper 특성상 즉시 체결이므로 미체결이 거의 없음

### 승격 기준 수치 (기본값, config + 전략별 오버라이드)
- **최소 페이퍼 기간: 7일 (1주)**
- **최소 거래 건수: 타임프레임 매핑 + 수동 오버라이드**
  - `1m~15m` (스캘핑) → 20건
  - `1h~4h` (데이트레이딩) → 10건
  - `1d~1w` (스윙) → 5건
  - StrategyDefinition의 timeframes[0] 기준 자동 적용
  - 전략별 `min_paper_trades` 오버라이드 가능
- **Sharpe ≥ 0.3** — 최소한의 위험 대비 수익
- **승률 ≥ 30%** — 트렌드 추종 전략 대응
- **최대DD ≤ -20%** — 자본 보존 최소 기준
- **누적 PnL > 0** — 페이퍼 기간 중 순수익 양수 필수
- 모든 기준은 글로벌 config + StrategyDefinition `promotion_gates` 필드로 전략별 오버라이드 가능
- **미충족 시 피드백: 상세 리포트** — 미충족 항목별 현재값/기준값 비교 + 일별 PnL 추이 + equity curve 차트를 Discord Embed로 전송. Phase 2 report.py 재사용

### Paper 성과 조회
- **채널: CLI + API + Discord 전부** — Phase 2 백테스트 이력과 동일하게 세 채널 제공
- **조회 단위: 전략별 + 전체 요약 + 심볼별** — 개별 전략 성과, 모든 paper 전략 비교, 전략 내 심볼별 분해
- **계산 방식: 혼합** — 일별 집계 캐시 + 당일분만 실시간 계산하여 합산. 빠르면서 최신
- **승격 가능 표시: 진행률 + 예상 승격 시점** — 항목별 충족 여부(`Sharpe ✓ | 승률 ✗ | DD ✓ | 기간 ✓ | 거래수 ✗`) + "거래 3건 부족, 약 2일 예상" 추정

### 승격 워크플로우
- **자동 체크: 주기적** — config 설정 주기로 모든 paper 전략의 기준 충족 여부 자동 체크 (주기는 Claude 재량, config로 관리)
- **알림: 1회 + 대시보드 뱃지** — 기준 최초 충족 시 Discord 알림 1회 발송. 이후 전체 요약 조회 시 "승격 대기" 상태 표시
- **승격 실행: 확인 버튼** — `/전략승격 [strategy_id]` → 기준 충족 상세 + 리포트를 Embed로 표시 → 확인/취소 버튼 → 확인 시 paper→active 전이
- **승격 후처리: 상태 전이 + Discord 알림 + 페이퍼 성과 아카이빙**
  - registry.json paper→active 전이
  - Discord Embed: 전략명, 기준 통과 결과, 페이퍼 성과 요약
  - 승격 시점 페이퍼 성과 스냅샷을 DB에 별도 기록 (나중에 승격 당시 vs 실매매 성과 비교)

### Claude's Discretion
- PaperBroker DB 스키마 상세 (테이블 구조, 칼럼, 인덱스)
- 자동 체크 주기 기본값
- PnL 스냅샷 집계 + 당일분 실시간 합산 구현 상세
- 예상 승격 시점 추정 알고리즘
- Discord Embed 레이아웃 상세
- CLI rich table 레이아웃 상세
- API 엔드포인트 경로/응답 스키마

</decisions>

<specifics>
## Specific Ideas

- 기존 OrderRecord(broker="paper")로 거래 이력은 이미 DB에 쌓을 수 있는 구조
- Phase 2 report.py의 quantstats/chart 생성 함수를 승격 판정 리포트에 재사용
- LifecycleManager.transition()에 gate 검증 로직을 삽입하여 paper→active 전이 시 자동 차단
- Phase 1의 `/전략전이` 확인 버튼 패턴을 `/전략승격`에 재사용

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PaperBroker` (`engine/execution/paper_broker.py`): 현재 in-memory — DB 영속화 확장 대상
- `BaseBroker` (`engine/execution/broker_base.py`): PaperBroker 부모 클래스, _place_order/_fetch_raw_balance 인터페이스
- `LifecycleManager` (`engine/strategy/lifecycle_manager.py`): ALLOWED_TRANSITIONS에 paper→active 존재, gate 로직 삽입 포인트
- `BacktestRepository` (`engine/core/repository.py`): get_history, compare_strategies, delete — Paper 성과 조회에 동일 패턴 적용
- `report.py` (`engine/backtest/report.py`): generate_quantstats_report, generate_validation_chart, generate_full_report — 승격 판정 리포트에 재사용
- `history_cli.py` (`engine/backtest/history_cli.py`): Rich table CLI 패턴 — Paper 성과 CLI에 동일 패턴
- `BacktestHistoryPlugin` (`engine/interfaces/discord/commands/backtest_history.py`): Discord slash command 패턴 — Paper 관련 커맨드에 재사용
- `OrderRecord` (`engine/core/db_models.py`): broker="paper" 칼럼 존재 — paper 거래 이력 이미 DB 저장 가능
- `StrategyDefinition` (`engine/schema.py`): timeframes 필드로 전략 타입 유추, promotion_gates 필드 추가 대상

### Established Patterns
- Repository 패턴: DB CRUD는 `engine/core/repository.py`에 집중
- DB 확장: Phase 2에서 BacktestRecord 칼럼 추가 + idempotent migration 패턴 확립
- 3채널 인터페이스: CLI(rich table) + API(FastAPI) + Discord(slash command) — Phase 2에서 확립
- Discord 확인 버튼: Phase 1 `/전략전이`에서 확인/취소 버튼 UX 구현 완료
- Config 관리: `config/` 디렉토리에 JSON 설정 파일 패턴

### Integration Points
- `PaperBroker.__init__()`: DB 세션 주입 + 상태 복원 로직 추가
- `PaperBroker._place_order()`: 체결 후 PnL 기록 + DB 저장 트리거
- `LifecycleManager.transition()`: paper→active 전이 시 gate 검증 로직 삽입
- `engine/core/database.py`: paper 관련 테이블 migration 추가
- `api/routers/`: paper 성과 조회 엔드포인트 추가
- Discord bot: `/페이퍼현황`, `/전략승격` 커맨드 추가

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-paper-trading-stage*
*Context gathered: 2026-03-11*
