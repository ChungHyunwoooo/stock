# Requirements: AutoTrader

**Defined:** 2026-03-11
**Core Value:** 수익을 주는 자동화 봇 — 전략 발굴부터 실매매까지 사람 개입 없이 돌아가되, 성과 저하 시 즉시 알림으로 제어권 유지

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Backtest Quality

- [x] **BT-01**: 거래소별 슬리피지+수수료 모델을 백테스트에 적용할 수 있다 (configurable per exchange, VolumeAdjustedSlippage 지원)
- [ ] **BT-02**: Walk-forward OOS 검증으로 전략의 과적합을 방지할 수 있다 (다기간 IS/OOS 분할, IS-OOS 성과 갭 임계치 적용)
- [x] **BT-03**: 전략이 2-3개 비상관 심볼에서 일관된 성과를 보이는지 검증할 수 있다 (중앙 Sharpe 기준 통과)
- [x] **BT-04**: 백테스트 결과를 DB에 저장하고 전략별/날짜별 이력을 비교할 수 있다
- [ ] **BT-05**: CPCV(Combinatorial Purged Cross-Validation)로 walk-forward를 고도화할 수 있다

### Strategy Lifecycle

- [x] **LIFE-01**: 전략 상태가 draft→testing→paper→active→archived 순서로만 전이되며, 규칙 위반 전이를 차단한다
- [x] **LIFE-02**: 페이퍼 트레이딩 단계에서 PaperBroker 상태가 세션 간 영속되고 PnL이 추적된다
- [x] **LIFE-03**: Paper→Live 승격 시 Sharpe/승률/기간/최대DD 기준을 자동 검증하고, 미충족 시 승격을 차단한다
- [x] **LIFE-04**: 논문/커뮤니티의 레퍼런스 전략을 JSON StrategyDefinition으로 변환하는 구조화된 워크플로우가 있다

### Risk Management

- [ ] **RISK-01**: 실매매 전략의 20거래 롤링 윈도우 성과가 백테스트 기준 대비 저하되면 Discord 알림을 발송한다
- [x] **RISK-02**: ATR 또는 Kelly fraction 기반으로 변동성에 따른 가변 포지션 사이징이 적용된다
- [x] **RISK-03**: 신규 진입 시 기존 활성 전략과의 신호 상관관계가 0.7 초과이면 진입을 차단한다

### Monitoring & Alerts

- [ ] **MON-01**: 매매 체결/전략 상태 변화/시스템 이상/백테스트 결과를 실시간 Discord 알림으로 받을 수 있다
- [ ] **MON-02**: Discord /status 커맨드로 현재 포지션, 일일 PnL, 전략 상태를 즉시 조회할 수 있다
- [ ] **MON-03**: 웹 대시보드에서 실시간 포지션, 전략 성과, 시스템 상태, 전략 탐색 현황, 설정을 확인/변경할 수 있다
- [ ] **MON-04**: 단기 타임프레임 진입 신호를 상위 타임프레임 방향 확인으로 필터링할 수 있다 (MTF confirmation gate)

### Strategy Discovery

- [ ] **DISC-01**: indicator 조합을 자동 sweep하고 optuna 기반 Bayesian 파라미터 최적화로 후보 전략을 발굴할 수 있다
- [ ] **DISC-02**: ccxt 기반으로 Binance/Upbit 외 거래소(Bybit, OKX 등)의 데이터 수급 및 주문 실행을 지원한다

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Portfolio

- **PORT-01**: 전체 전략 합산 일일 손실이 설정 한도 초과 시 모든 신규 진입을 자동 차단

### Advanced Discovery

- **ADVD-01**: LLM/ML 기반 자동 indicator 특성 선택 (해석 불가 리스크)
- **ADVD-02**: 소셜/카피 트레이딩 기반 전략 공유

## Out of Scope

| Feature | Reason |
|---------|--------|
| 자동 전략 교체 | 73% 자동화 봇 실패 — 알림 후 수동 판단이 안전 |
| HFT (초고빈도 매매) | co-location + C++ 필요, Python 스택 비호환 |
| 대시보드 실시간 폴링 (1초) | CPU 과부하 — 30초 간격 폴링으로 충분 |
| 모바일 앱 | Discord + 웹 대시보드로 커버 |
| 멀티 브로커 차익거래 | 초저지연 + 규제 이슈 — 멀티 브로커는 리던던시 용도만 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BT-01 | Phase 2 | Complete |
| BT-02 | Phase 2 | Pending |
| BT-03 | Phase 2 | Complete |
| BT-04 | Phase 2 | Complete |
| BT-05 | Phase 2 | Pending |
| LIFE-01 | Phase 1 | Complete |
| LIFE-02 | Phase 3 | Complete |
| LIFE-03 | Phase 3 | Complete |
| LIFE-04 | Phase 1 | Complete |
| RISK-01 | Phase 5 | Pending |
| RISK-02 | Phase 4 | Complete |
| RISK-03 | Phase 4 | Complete |
| MON-01 | Phase 6 | Pending |
| MON-02 | Phase 6 | Pending |
| MON-03 | Phase 8 | Pending |
| MON-04 | Phase 6 | Pending |
| DISC-01 | Phase 7 | Pending |
| DISC-02 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-03-11*
*Last updated: 2026-03-11 after roadmap creation — all 19 requirements mapped*
