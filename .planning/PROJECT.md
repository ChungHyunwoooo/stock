# AutoTrader — Automated Trading Pipeline

## What This Is

멀티 거래소 대상 자동화 트레이딩 봇. Indicator 수집부터 전략 자동 탐색, 백테스트 검증, 페이퍼 트레이딩, 실매매 투입, 성과 모니터링까지 전체 파이프라인을 자동화한다. 스캘핑(1m~5m), 단타(15m~1h), 스윙(4h~1d), 멀티 타임프레임 조합을 모두 지원한다.

## Core Value

**수익을 주는 자동화 봇** — 전략 발굴부터 실매매까지 사람 개입 없이 돌아가되, 성과 저하 시 즉시 알림으로 제어권을 유지한다.

## Requirements

### Validated

<!-- 기존 코드베이스에서 이미 작동하는 기능 -->

- ✓ 멀티 거래소 OHLCV 데이터 수급 (Binance, Upbit, FDR) + 캐시 — existing
- ✓ 기술 지표 계산 엔진 (TA-Lib + 커스텀 indicator registry) — existing
- ✓ 차트/캔들 패턴 인식 (chart_patterns, candle_patterns, pullback 등) — existing
- ✓ 방향 판단 엔진 (direction.py weighted confidence scoring) — existing
- ✓ 전략 정의 스키마 (JSON StrategyDefinition + condition_evaluator) — existing
- ✓ 자동 스캐너 데몬 (pattern_alert.py, 30초 간격) — existing
- ✓ 주문 실행 프레임워크 (Paper/Binance/Upbit broker) — existing
- ✓ Discord 웹훅 알림 + 슬래시 커맨드 봇 — existing
- ✓ 트레이딩 오케스트레이터 (alert_only/semi_auto/auto 모드) — existing
- ✓ 백테스트 프레임워크 (runner, metrics, optimizer) — existing
- ✓ REST API (FastAPI) — existing
- ✓ 전략별 리스크 관리 (risk_manager, scalping_risk) — existing
- ✓ 스캘핑 전략 4종 (BB bounce/squeeze, triple EMA, EMA crossover) — existing
- ✓ SQLite 거래 DB + Repository 패턴 — existing

### Active

<!-- 새로 구축할 범위 -->

- [ ] Indicator 체계적 수집 — 라이브러리(TA-Lib, pandas-ta) 래핑 + 커스텀 indicator 직접 구현
- [ ] 전략 자동 탐색 엔진 — indicator 조합 자동 sweep + 파라미터 최적화
- [ ] 레퍼런스 기반 전략 구현 — 논문/커뮤니티 전략을 definition.json으로 변환
- [ ] 고도화된 백테스트 검증 — 수익률 기준 + 다기간/다시장 안정성 + 실제 데이터 기반 슬리피지/수수료 모델링
- [ ] 페이퍼 트레이딩 단계 — 백테스트 통과 → 페이퍼 트레이딩 검증 → 실매매 투입 파이프라인
- [ ] 멀티 거래소 확장 — Binance/Upbit 외 거래소 지원 (ccxt 기반)
- [ ] 포트폴리오 레벨 리스크 관리 — 전략 간 상관관계 체크 + 전체 포지션 한도 + 자본 배분 최적화
- [ ] 성과 모니터링 시스템 — 실시간 전략 성과 추적, 성과 저하 감지, 알림 후 수동 교체
- [ ] 실시간 알림 고도화 — 매매 체결/전략 상태 변화/시스템 이상/백테스트 결과 (Discord 등)
- [ ] 모니터링 대시보드 — 실시간 포지션, 전략 성과, 시스템 상태, 전략 탐색 현황, 설정 변경
- [ ] 전략 생명주기 관리 — 발굴 → 백테스트 → 페이퍼 → 실매매 → 모니터링 → 퇴출 자동화

### Out of Scope

- 자동 전략 교체 — 성과 저하 시 알림만, 교체는 수동 판단
- HFT(초고빈도 매매) — 인프라 요구사항이 다름
- 자체 거래소 운영 — 기존 거래소 API 활용
- 모바일 앱 — 웹 대시보드 + Discord 알림으로 충분

## Context

- 기존 코드베이스: 3계층 파이프라인 아키텍처 (OHLCV → indicators → patterns → analysis → signal → alert) 확립
- Port/Adapter 패턴으로 broker/notifier/store 교체 가능한 구조
- 전략은 데이터(JSON)로 관리, 코드가 아님
- Python 3.12, TA-Lib, ccxt, FastAPI, SQLAlchemy, Discord.py 스택
- systemd 기반 Linux 배포 환경
- 스캘핑부터 스윙까지 전 타임프레임 지원 필요
- 멀티 타임프레임 조합 판단 (예: 4h 추세 + 15m 진입)

## Constraints

- **Tech stack**: Python 기반 유지 — 기존 엔진과 일관성
- **Exchange API**: ccxt 통합 거래소 API 사용 — 멀티 거래소 호환
- **Data**: TA-Lib C 라이브러리 시스템 설치 필수
- **Architecture**: 기존 3계층 파이프라인 + Port/Adapter 패턴 준수
- **Strategy format**: JSON StrategyDefinition 스키마 유지
- **Naming**: 기존 네이밍 규칙 준수 (subject_role.py, calc_/detect_/evaluate_ 등)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 전략 조합 탐색: ref + auto sweep 혼합 | 레퍼런스로 검증된 전략 기반 + 자동 탐색으로 발견 영역 확장 | — Pending |
| 백테스트 검증: 수익 + 안정성 이중 기준 | 과적합 방지, 다기간/다시장 안정성 확보 | — Pending |
| 슬리피지 모델: 실제 데이터 기반 | 정적 모델 대비 실매매 괴리 최소화 | — Pending |
| 페이퍼 트레이딩 단계 도입 | 백테스트→실매매 사이 실시간 검증으로 리스크 감소 | — Pending |
| 포트폴리오 리스크 관리 | 다전략 동시 운용 시 상관관계/전체 노출 관리 필수 | — Pending |
| 성과 저하 시 알림 후 수동 교체 | 자동 교체보다 사람 판단이 더 안전 | — Pending |
| 대시보드: 웹 기반 (Streamlit 또는 확장) | 기존 Streamlit 인프라 활용 가능 | — Pending |

---
*Last updated: 2026-03-11 after initialization*
