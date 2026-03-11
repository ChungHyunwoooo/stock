# Phase 4: Portfolio Risk - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

<domain>
## Phase Boundary

여러 전략이 동시에 실행될 때 상관 진입이 차단되고 변동성 기반 포지션 사이징이 적용되어 포트폴리오 전체 리스크가 관리된다. 상관관계 필터(RISK-03) + 변동성 기반 포지션 사이징(RISK-02) + Risk Parity 자본 배분을 포함한다.

</domain>

<decisions>
## Implementation Decisions

### 포지션 사이징 통합
- **scalping_risk.py 확장**: 기존 ATR+Kelly 로직을 일반화하여 전 타임프레임(스캘핑/데이트레이딩/스윙)에 적용. ScalpRiskConfig의 범위값을 타임프레임별 프리셋으로 제공
- **곱산 합산**: ATR+Kelly로 기본 수량 계산 → RiskManager.position_size_factor() 곱하기. 두 계층이 독립적으로 동작 (ATR+Kelly = 시장 변동성 반영, position_size_factor = 일일 손실 누적 반영)
- **Kelly 기본값**: Quarter Kelly (fraction=0.25). 최소 20건 거래 이력 있을 때만 적용, 미달 시 고정 risk_per_trade_pct 사용
- **고정 2% 완전 대체**: ATR+Kelly가 고정 risk_per_trade_pct를 완전 대체. Kelly 결과가 높아도 cap 없이 그대로 적용 (RiskManager.position_size_factor()가 드로다운 시 축소하는 안전장치 역할)

### 다전략 자본 배분
- **Risk Parity**: 공분산 행렬 + 역행렬 기반 Risk Parity로 전략별 자본 배분. 전략별 리스크 기여가 동등해지도록 배분
- **직접 구현**: numpy만으로 구현 (10~20줄). riskfolio-lib 의존성 없음. HRP 같은 고급 방법은 미래 확장
- **전략별 최대 배분 비율**: config로 관리 (기본값은 Claude 재량)
- **재계산 주기**: 일단위 정기 재계산 (UTC 0시) + 신호 발생 시마다 즉시 재계산. 전략 추가/제거 시에도 즉시 재계산

### 상관관계 게이트 (기존 패턴 적용)
- **임계치 0.7**: 신규 진입 신호 발생 시 기존 활성 전략과의 신호 상관관계 0.7 초과면 진입 차단
- **config 기반**: 임계치는 config에서 조정 가능 + 전략별 오버라이드
- **차단 알림**: logger.info로 차단 사유 기록 + Discord 알림 (전략명, 상관계수, 차단된 상대 전략)

### 활성화/비활성화 설계
- **통합 방식**: Claude 재량 (주입 패턴 or 데코레이터 등 플래너 판단)
- **비활성화 범위**: 상관관계 게이트만 OFF. ATR+Kelly 사이징과 Risk Parity 배분은 계속 동작
- **차단 로깅**: 로깅 + Discord 알림 동시 제공 (운영 투명성 확보)

### Claude's Discretion
- TradingOrchestrator ↔ PortfolioRiskManager 통합 패턴 (주입 vs 데코레이터 vs 기타)
- 전략별 최대 배분 비율 기본값
- 상관관계 계산 대상 (신호 상관 vs 수익률 상관) 및 윈도우 크기
- Risk Parity 구현 상세 (공분산 추정 방법, 수축 적용 여부)
- scalping_risk.py 확장 시 타임프레임별 프리셋 구체 수치
- Kelly 최소 거래 이력 20건의 config 관리 방식

</decisions>

<specifics>
## Specific Ideas

- scalping_risk.py의 `fractional_kelly()` 함수가 이미 Kelly 계산 완비 — 확장 시 재사용
- multi_symbol.py의 `select_uncorrelated_symbols()` 상관계수 계산 패턴을 실시간 상관 게이트에 참고
- RiskManager.position_size_factor()의 drawdown 기반 축소가 ATR+Kelly와 곱산으로 자연스럽게 합산
- Risk Parity 직접 구현 시 numpy의 `np.linalg.inv` 또는 `scipy.optimize.minimize`로 동등 리스크 기여 최적화

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scalping_risk.py`: calc_atr, calc_atr_percentile, fractional_kelly, calculate_dynamic_sl_tp, calculate_scalp_risk — 전 타임프레임 확장 대상
- `risk_manager.py`: RiskManager (일일 손실 제한 + position_size_factor) — 곱산 합산 대상
- `risk.py`: calculate_position_size, apply_risk_management — 기본 포지션 사이징 함수
- `multi_symbol.py`: select_uncorrelated_symbols (상관계수 greedy 선택) — 상관 게이트 참고 패턴
- `schema.py`: RiskParams (risk_per_trade_pct 필드) — Kelly 대체 시 인터페이스 유지

### Established Patterns
- Config 기반 수치 관리: 모든 임계치는 config JSON + 전략별 오버라이드 (Phase 3 확립)
- Repository 패턴: DB CRUD는 engine/core/repository.py
- 3채널 인터페이스: CLI + API + Discord (Phase 2 확립)

### Integration Points
- `TradingOrchestrator.process_signal()`: 신호 처리 시 PortfolioRiskManager 게이트 삽입
- `AlertScannerRuntime.scan_once()`: 신호 발생 루프에서 포지션 사이징 적용
- `scalping_risk.py`: ScalpRiskConfig 확장 + 타임프레임별 프리셋 추가
- `RiskManager.allow_entry()`: 기존 심볼별 리스크 체크 후 상관관계 게이트 추가 레이어
- Discord 웹훅: 상관관계 차단 알림 전송

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-portfolio-risk*
*Context gathered: 2026-03-12*
