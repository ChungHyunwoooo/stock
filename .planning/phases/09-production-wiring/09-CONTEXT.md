# Phase 9: Production Wiring — Orchestrator & Bootstrap - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

<domain>
## Phase Boundary

구현 완료된 PositionSizer, PortfolioRiskManager, PerformanceMonitor를 프로덕션 실행 경로(orchestrator + bootstrap)에 배선한다. 새 기능 구현이 아닌 gap closure — 기존 컴포넌트를 연결만 한다.

</domain>

<decisions>
## Implementation Decisions

### PositionSizer 배선
- Orchestrator 내부에서 PositionSizer.calculate() 호출 — process_signal() 내부 단일 지점에서 사이징
- PositionSizer는 **필수 강제** — 미주입(None) 시 주문 거부
- capital은 broker 잔고 조회로 실시간 반영
- OHLCV 전달 방식은 Claude 재량

### Allocation Weight 흐름
- get_allocation_weights()는 Orchestrator 내부에서 호출 — correlation gate 통과 후, PositionSizer 호출 전
- PortfolioRiskManager도 **필수 강제** — 미주입(None) 시 주문 거부
- 미등록 전략은 **진입 차단** — 모든 전략 등록 강제

### Bootstrap 의존성 조립
- TradingRuntime dataclass에 PositionSizer, PortfolioRiskManager, PerformanceMonitor **전체 노출**
- 컴포넌트 활성화 방식은 Claude 재량
- PerformanceMonitor 의존성(repos, lifecycle, session_factory) 조립 방식은 Claude 재량

### 모니터 데몬 생명주기
- bootstrap 시점에서 run_daemon() **자동 시작**
- graceful shutdown **불필요** — daemon=True 스레드, 프로세스 종료 시 자동 종료
- 실패 시 로그 후 계속 — Phase 5 원칙 유지 (모니터 다운 ≠ 트레이딩 다운)
- check_interval_seconds를 bootstrap config에서 설정 가능하게

### Config 확장성 원칙
- **모든 config 값은 외부에서 수정 가능하게** — 하드코딩 금지
- 사용자(관리자)가 config 파일/파라미터로 패치 가능한 구조
- 새 컴포넌트 추가 시 config 구조가 쉽게 확장되도록 설계

### Claude's Discretion
- OHLCV 데이터 전달 방식 (signal.metadata vs orchestrator 재조회)
- PerformanceMonitor 의존성 조립 상세 (bootstrap 내부 vs 외부 주입)
- 컴포넌트 활성화 제어 방식 (전체 필수 vs config flag)
- BrokerPort에 get_balance() 추가 방식

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PositionSizer` (engine/strategy/position_sizer.py): ATR+Kelly+factor+allocation 완전 구현, calculate() API 확정
- `PortfolioRiskManager` (engine/strategy/portfolio_risk.py): correlation gate + get_allocation_weights() 완전 구현
- `StrategyPerformanceMonitor` (engine/strategy/performance_monitor.py): daemon thread + check_all() 완전 구현
- `EventNotifier` (engine/notifications/event_notifier.py): 이미 orchestrator에 TYPE_CHECKING import
- `MTFConfirmationGate` (engine/strategy/mtf_filter.py): 이미 orchestrator에 주입 구조 존재

### Established Patterns
- Constructor injection with None default — orchestrator가 portfolio_risk, event_notifier, mtf_filter에 이미 적용
- Plugin registry — broker_plugins, notifier_plugins, runtime_store_plugins 패턴 확립
- try/except + logger.warning — DB 실패 시 비차단 패턴 (Phase 3, 5에서 확정)

### Integration Points
- `engine/interfaces/bootstrap.py:36` — TradingOrchestrator 생성 지점 (배선 추가)
- `engine/application/trading/orchestrator.py:34` — process_signal() (PositionSizer 호출 추가)
- `engine/application/trading/orchestrator.py:96` — _build_order() 전 quantity 계산 지점
- `engine/application/trading/signal_scanner.py:398,452` — process_signal(quantity=config.quantity) 호출 지점

</code_context>

<specifics>
## Specific Ideas

- "관리자로서 편하게 패치하고 싶다" — 모든 config/임계치를 config 파일에서 수정 가능하게
- PositionSizer + PortfolioRiskManager 모두 필수 강제 — 프로덕션 안전성 최우선
- Phase 5 원칙 유지: 모니터 다운 ≠ 트레이딩 다운

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-production-wiring*
*Context gathered: 2026-03-12*
