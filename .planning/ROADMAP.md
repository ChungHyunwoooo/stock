# Roadmap: AutoTrader — Automated Trading Pipeline

## Overview

기존 3계층 파이프라인(OHLCV → indicators → patterns → analysis → signal → alert)을 전략 생명주기 파이프라인으로 확장한다. 전략 발굴부터 백테스트 검증, 페이퍼 트레이딩, 실매매 투입, 성과 모니터링까지 사람 개입 없이 돌아가는 자동화 봇을 목표로 한다. 의존성 체인이 강제하는 순서(비용 모델 → 워크포워드 → 페이퍼 → 포트폴리오 리스크 → 모니터링 → 탐색)를 엄격히 따른다.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: Lifecycle Foundation** - 전략 상태머신 + LifecycleManager로 모든 상태 전이를 코드로 강제
- [ ] **Phase 2: Backtest Quality Gates** - 슬리피지 모델 + 워크포워드 OOS + 멀티심볼 검증으로 신뢰 가능한 백테스트 구축
- [ ] **Phase 3: Paper Trading Stage** - PaperBroker 영속화 + Paper→Live 승격 게이트 자동 검증
- [x] **Phase 4: Portfolio Risk** - 상관관계 필터 + 변동성 기반 포지션 사이징으로 다전략 동시 운용 안전화 (completed 2026-03-11)
- [x] **Phase 5: Performance Monitoring** - 롤링 20거래 윈도우 성과 감시 + Discord 알림으로 실매매 성과 저하 즉시 감지 (completed 2026-03-11)
- [ ] **Phase 6: Alert & MTF Enrichment** - Discord 알림 통합 고도화 + 멀티 타임프레임 진입 필터 활성화
- [ ] **Phase 7: Auto-Discovery** - Optuna 기반 Bayesian 파라미터 탐색 + ccxt 멀티거래소 확장
- [ ] **Phase 8: Monitoring Dashboard** - Streamlit 대시보드로 전략 파이프라인 전체 가시화
- [ ] **Phase 9: Production Wiring** - PositionSizer + PerformanceMonitor 프로덕션 배선 (gap closure)
- [ ] **Phase 10: Event & Notification Wiring** - EventNotifier 4개 이벤트 + BacktestHistoryPlugin 활성화 (gap closure)
- [ ] **Phase 11: Cross-Phase Data Contracts** - PromotionGate 백테스트 비교 + CPCV sweep 통합 (gap closure)

## Phase Details

### Phase 1: Lifecycle Foundation
**Goal**: 전략 상태가 코드로 강제되어 draft 전략이 실매매에 진입하는 사고를 차단할 수 있다
**Depends on**: Nothing (first phase)
**Requirements**: LIFE-01, LIFE-04
**Success Criteria** (what must be TRUE):
  1. draft/testing/paper/active/archived 외의 전이를 시도하면 LifecycleManager가 예외를 발생시킨다
  2. Discord /전략전이 커맨드로 전략 상태를 변경할 수 있고, 규칙 위반 시 커맨드가 거부된다
  3. 논문/커뮤니티 전략을 JSON StrategyDefinition으로 변환하는 워크플로우가 문서화되고 하나 이상의 레퍼런스 전략이 draft 상태로 등록된다
  4. registry.json에 모든 전략의 현재 상태가 기록되어 있고, LifecycleManager 외에는 이를 직접 수정할 수 없다
**Plans**: 3 plans

Plans:
- [ ] 01-01-PLAN.md — StrategyStatus enum paper 추가 + LifecycleManager TDD 구현 (FSM 전이 규칙 강제)
- [ ] 01-02-PLAN.md — Discord /전략전이 커맨드 + API 라우터 LifecycleManager 연동
- [ ] 01-03-PLAN.md — RSI Divergence 레퍼런스 전략 생성 + draft 등록 (워크플로우 증명)

### Phase 2: Backtest Quality Gates
**Goal**: 백테스트 결과가 실매매 비용과 과적합 위험을 반영하여 신뢰할 수 있는 전략 선별 기준이 된다
**Depends on**: Phase 1
**Requirements**: BT-01, BT-02, BT-03, BT-04, BT-05
**Success Criteria** (what must be TRUE):
  1. BacktestRunner가 거래소별 슬리피지+수수료를 적용하고, 동일 전략에 VolumeAdjustedSlippage를 적용하면 수익률이 낮아진다
  2. 워크포워드 검증 실행 시 IS/OOS 분할 결과와 성과 갭 판정(통과/실패)이 자동 출력된다
  3. 2-3개 비상관 심볼에 동시 백테스트를 실행하면 심볼별 Sharpe와 중앙값 기준 통과 여부가 자동 판정된다
  4. 백테스트 실행마다 결과가 DB에 저장되고, 전략별 이력 비교를 CLI/API/Discord로 조회할 수 있다
  5. CPCV 모드를 선택하면 기본 워크포워드 대신 조합형 퍼지 교차검증이 실행된다
**Plans**: 7 plans

Plans:
- [ ] 02-01-PLAN.md — SlippageModel + DepthCache/DepthCollector + FeeModel + BacktestRunner 통합 (BT-01)
- [ ] 02-02-PLAN.md — WalkForwardValidator 구현 (IS/OOS 분할, 성과 갭 임계치 판정) (BT-02)
- [ ] 02-03-PLAN.md — CPCVValidator 구현 (조합형 퍼지 교차검증 모드) (BT-05)
- [ ] 02-04-PLAN.md — MultiSymbolValidator 구현 (상관계수 심볼 선택 + 병렬 백테스트 + 중앙 Sharpe 게이트) (BT-03)
- [ ] 02-05-PLAN.md — BacktestRecord 스키마 확장 + 자동 DB 저장 + 이력 비교 조회 (BT-04)
- [ ] 02-06-PLAN.md — quantstats 리포트 + IS/OOS 시각화 + 통합 판정 리포트 (BT-02, BT-05)
- [ ] 02-07-PLAN.md — CLI(rich table) + API + Discord 인터페이스 (이력 조회/비교/삭제) (BT-04)

### Phase 3: Paper Trading Stage
**Goal**: 백테스트를 통과한 전략이 실자본 투입 전 실시간 시장에서 최소 기간 검증을 받고, 정량 기준 충족 시에만 실매매로 승격된다
**Depends on**: Phase 2
**Requirements**: LIFE-02, LIFE-03
**Success Criteria** (what must be TRUE):
  1. PaperBroker 상태(포지션, PnL, 거래 이력)가 프로세스 재시작 후에도 보존된다
  2. 페이퍼 트레이딩 중인 전략의 누적 PnL과 거래 건수를 실시간으로 조회할 수 있다
  3. Paper→Live 승격 시 Sharpe/승률/기간/최대DD 기준이 자동 검증되고, 미충족 시 승격 커맨드가 거부된다
  4. 기준 통과 시 Discord로 "승격 가능" 알림이 발송되고, 사람이 /전략승격을 실행해야 실매매가 시작된다
**Plans**: 2 plans

Plans:
- [ ] 03-01-PLAN.md — PaperBroker DB 영속화 (SQLite 테이블 + PaperRepository + PnL 이중 기록)
- [ ] 03-02-PLAN.md — PromotionGate + LifecycleManager 통합 + 3채널 인터페이스 (CLI/API/Discord)

### Phase 4: Portfolio Risk
**Goal**: 여러 전략이 동시에 실행될 때 상관 진입이 차단되고 변동성 기반 포지션 사이징이 적용되어 포트폴리오 전체 리스크가 관리된다
**Depends on**: Phase 3
**Requirements**: RISK-02, RISK-03
**Success Criteria** (what must be TRUE):
  1. 신규 진입 신호 발생 시 기존 활성 전략과의 신호 상관관계가 자동 계산되고, 0.7 초과이면 진입이 차단된다
  2. ATR 또는 Kelly fraction 기반으로 계산된 포지션 크기가 고정 2% 방식과 다른 값을 반환한다
  3. PortfolioRiskManager를 비활성화하면 상관관계 차단 없이 진입이 허용되어 게이트가 분리되어 있음을 확인할 수 있다
**Plans**: 2 plans

Plans:
- [ ] 04-01-PLAN.md — 변동성 기반 포지션 사이징 (ATR+Kelly + Risk Parity 자본 배분 + RiskManager 곱산 통합)
- [ ] 04-02-PLAN.md — PortfolioRiskManager 구현 (상관관계 게이트 + TradingOrchestrator 연동)

### Phase 5: Performance Monitoring
**Goal**: 실매매 중인 전략의 성과 저하가 자동으로 감지되고 Discord 알림으로 즉시 통보된다
**Depends on**: Phase 4
**Requirements**: RISK-01
**Success Criteria** (what must be TRUE):
  1. 실매매 전략의 최근 20거래 윈도우 Sharpe/승률이 백테스트 기준 대비 15% 이상 하락하면 Discord WARNING 알림이 발송된다
  2. 롤링 30거래 Sharpe가 -0.5 미만이면 Discord CRITICAL 알림이 발송되고 해당 전략의 신규 진입이 자동 일시정지된다
  3. 성과 모니터는 실행 경로(TradingOrchestrator)에서 완전히 분리되어, 모니터 다운 시에도 실매매가 계속된다
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — StrategyPerformanceMonitor 구현 (데몬 스레드 15분 주기, 롤링 윈도우 계산 + per-strategy pause)
- [ ] 05-02-PLAN.md — Discord 성과 저하 알림 (WARNING/CRITICAL embed + 자동 일시정지 연동)

### Phase 6: Alert & MTF Enrichment
**Goal**: 매매 이벤트와 시스템 상태가 Discord로 실시간 통보되고, 단기 타임프레임 신호가 상위 타임프레임 방향으로 필터링된다
**Depends on**: Phase 5
**Requirements**: MON-01, MON-02, MON-04
**Success Criteria** (what must be TRUE):
  1. 매매 체결, 전략 상태 변화, 시스템 이상, 백테스트 완료가 각각 구분된 Discord 메시지로 즉시 도착한다
  2. Discord /status 커맨드 실행 시 현재 포지션, 일일 PnL, 전략별 상태가 5초 이내에 응답된다
  3. MTF 필터를 활성화하면 상위 타임프레임 방향과 반대되는 단기 진입 신호가 차단된다
  4. MTF 필터를 비활성화하면 단기 신호가 상위 타임프레임 무관하게 통과된다 (설정으로 제어 가능)
**Plans**: 3 plans

Plans:
- [ ] 06-01-PLAN.md — Discord 알림 통합 (체결/상태변화/시스템이상/백테스트 결과 이벤트) (MON-01)
- [ ] 06-02-PLAN.md — Discord /status 커맨드 (포지션 + 일일 PnL + 전략 상태 즉시 조회) (MON-02)
- [ ] 06-03-PLAN.md — MTF confirmation gate (상위 타임프레임 방향 필터) (MON-04)

### Phase 7: Auto-Discovery
**Goal**: Optuna 기반 자동 탐색이 후보 전략을 draft 상태로 발굴하고, ccxt를 통해 Binance/Upbit 외 거래소 데이터와 주문 실행을 지원한다
**Depends on**: Phase 6
**Requirements**: DISC-01, DISC-02
**Success Criteria** (what must be TRUE):
  1. 탐색 실행 시 지정한 indicator 조합과 파라미터 범위를 자동 sweep하고, 기준 통과 후보가 draft 상태로 registry에 등록된다
  2. 탐색이 완료되면 Discord로 후보 전략 목록과 Sharpe 점수가 통보된다
  3. Bybit 또는 OKX 거래소를 설정에 추가하면 해당 거래소의 OHLCV 데이터 수급과 페이퍼 주문 실행이 동작한다
**Plans**: 2 plans

Plans:
- [ ] 07-01-PLAN.md — IndicatorSweeper 구현 (Optuna TPE, 워크포워드 + 멀티심볼 검증 내장)
- [ ] 07-02-PLAN.md — ccxt 멀티거래소 확장 (Bybit, OKX 데이터 수급 + 주문 실행)

### Phase 8: Monitoring Dashboard
**Goal**: 웹 대시보드에서 전체 전략 파이프라인(탐색→백테스트→페이퍼→실매매)의 상태와 성과를 한눈에 확인하고 설정을 변경할 수 있다
**Depends on**: Phase 7
**Requirements**: MON-03
**Success Criteria** (what must be TRUE):
  1. 대시보드에서 전체 전략의 현재 상태(draft/testing/paper/active/archived)와 단계별 현황을 볼 수 있다
  2. 실시간 포지션, 전략별 PnL 차트, 시스템 상태(스캐너/스케줄러 헬스)를 30초 이내 갱신으로 확인할 수 있다
  3. 대시보드에서 전략 설정(임계치, 필터 on/off)을 변경하면 다음 스캔 사이클부터 반영된다
  4. 자동 탐색 큐의 진행 현황(완료/전체 trial 수, 현재 Sharpe)을 실시간으로 볼 수 있다
**Plans**: 2 plans

Plans:
- [ ] 08-01-PLAN.md — DashboardDataService + 멀티페이지 대시보드 (Lifecycle 뷰 + Portfolio PnL + System Health)
- [ ] 08-02-PLAN.md — IndicatorSweeper sweep_status.json writer + Sweep Progress 패널 + Settings Editor

### Phase 9: Production Wiring — Orchestrator & Bootstrap
**Goal:** 구현 완료된 PositionSizer와 PerformanceMonitor가 프로덕션 실행 경로에 실제로 배선되어 동작한다
**Depends on**: Phase 5
**Requirements**: RISK-01, RISK-02
**Gap Closure:** Closes gaps from audit (P0 — Production Behavior Breaks)
**Success Criteria** (what must be TRUE):
  1. orchestrator.process_signal()에서 PositionSizer.calculate()가 호출되어 quantity가 ATR/Kelly 기반으로 계산된다
  2. PortfolioRiskManager.get_allocation_weights()가 주문 전 호출된다
  3. application bootstrap에서 StrategyPerformanceMonitor.run_daemon()이 시작되어 데몬 스레드가 실행된다
**Plans**: 0 plans

Plans:
- (to be planned with `/gsd:plan-phase 9`)

### Phase 10: Event & Notification Wiring
**Goal:** EventNotifier의 4개 이벤트 타입이 모두 프로덕션에서 발화되고, BacktestHistoryPlugin이 Discord에서 활성화된다
**Depends on**: Phase 6
**Requirements**: MON-01, DISC-01
**Gap Closure:** Closes gaps from audit (P1 — Cross-Phase Contract Incomplete)
**Success Criteria** (what must be TRUE):
  1. LifecycleManager 상태 전이 시 notify_lifecycle_transition이 호출된다
  2. BacktestRunner.run() 완료 시 notify_backtest_complete가 호출된다
  3. IndicatorSweeper sweep 완료 시 notify_backtest_complete가 호출된다
  4. BacktestHistoryPlugin이 DEFAULT_COMMAND_PLUGINS에 등록되어 Discord 커맨드가 활성화된다
**Plans**: 0 plans

Plans:
- (to be planned with `/gsd:plan-phase 10`)

### Phase 11: Cross-Phase Data Contracts
**Goal:** PromotionGate가 백테스트 기준값과 교차 비교하고, CPCV가 sweep 파이프라인에서 사용 가능하다
**Depends on**: Phase 7
**Requirements**: LIFE-03, BT-05
**Gap Closure:** Closes gaps from audit (P1 — Cross-Phase Contract Incomplete)
**Success Criteria** (what must be TRUE):
  1. PromotionGate.evaluate()가 BacktestRepository 기준 Sharpe와 비교하여 paper Sharpe가 낮으면 승격을 차단한다
  2. IndicatorSweeper._objective()에서 CPCV 모드를 선택하면 WalkForward 대신 CPCV 교차검증이 실행된다
**Plans**: 0 plans

Plans:
- (to be planned with `/gsd:plan-phase 11`)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Lifecycle Foundation | 1/3 | In Progress|  |
| 2. Backtest Quality Gates | 6/7 | In Progress|  |
| 3. Paper Trading Stage | 2/2 | Complete | 2026-03-11 |
| 4. Portfolio Risk | 2/2 | Complete   | 2026-03-11 |
| 5. Performance Monitoring | 2/2 | Complete   | 2026-03-11 |
| 6. Alert & MTF Enrichment | 1/3 | In Progress|  |
| 7. Auto-Discovery | 0/2 | Not started | - |
| 8. Monitoring Dashboard | 0/2 | Not started | - |
| 9. Production Wiring | 0/0 | Not started | - |
| 10. Event & Notification Wiring | 0/0 | Not started | - |
| 11. Cross-Phase Data Contracts | 0/0 | Not started | - |
