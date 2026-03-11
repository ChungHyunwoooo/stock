# Phase 1: Lifecycle Foundation - Context

**Gathered:** 2026-03-11
**Status:** Ready for planning

<domain>
## Phase Boundary

전략 상태머신(draft→testing→paper→active→archived) + LifecycleManager로 모든 상태 전이를 코드로 강제한다. Discord 슬래시 커맨드로 전략 상태를 변경할 수 있고, 레퍼런스 전략 1개를 draft로 등록하는 워크플로우를 문서화한다. 실제 gate 로직(Sharpe/승률 기준)은 Phase 2~3 범위.

</domain>

<decisions>
## Implementation Decisions

### 상태 저장소 일원화
- registry.json이 single source of truth — LifecycleManager가 이 파일만 수정
- deprecated 상태를 archived로 통합 (deprecated_reason → archived_reason 마이그레이션)
- DB(StrategyRecord)는 전략 상태 관리에서 제외 — 백테스트 결과/거래 이력 저장소로 한정
- definition.json의 status 필드는 무시 — registry.json의 status만 사용
- API 전략 조회는 registry.json을 직접 읽어서 응답

### 전이 규칙 엄격도
- 상태: draft → testing → paper → active → archived (paper 추가)
- 제한적 역전이 허용: active→paper(강등), testing→draft(되돌리기), archived→draft(재활성화)
- 무작위 역전이 차단 (예: active→draft 불가)
- Phase 1은 상태머신만 구현 — gate 전제 조건 검증은 Phase 2~3에서 추가
- 전이 이력을 registry.json에 기록: 각 전략 항목에 status_history 배열 [{from, to, date, reason}]

### Discord 승격/퇴출 UX
- 단일 커맨드: `/전략전이 [strategy_id] [target_status]`
- Autocomplete 드롭다운으로 등록된 전략 목록 표시 (상태별 필터링)
- 실행 전 확인 버튼 표시 ("전략 X를 paper→active로 승격합니다. 확인/취소")
- 결과는 Discord Embed로 상세 표시: 전략명, 상태변경, 전이이력, 현재 전략 현황 테이블

### 레퍼런스 전략 임포트
- 변환 프로세스 설계는 Claude 재량
- research.md 필수 항목: 출처(논문/URL), 전략 로직 요약, 백테스트 결과 요약
- Phase 1에서 레퍼런스 전략 1개만 draft로 등록 (워크플로우 증명 목적)
- 기존 7개 active 전략은 편입하지 않음 — 신규 등록 전략부터 상태머신 적용

### Claude's Discretion
- 레퍼런스 전략 변환 프로세스(수동/반자동) 설계
- 허용된 전이 맵의 정확한 구현 방식 (dict, 그래프 등)
- Discord Embed 레이아웃 상세
- registry.json 스키마 확장 세부 (status_history 외 필드)

</decisions>

<specifics>
## Specific Ideas

- 기존 전략(active 7개, deprecated 9개)은 현행 유지 — 상태머신 관리 대상 아님
- deprecated → archived 용어 통합은 신규 전략에만 적용
- 전략 수가 적으므로(수십 개) 파일 읽기 vs DB 조회 성능 차이 무의미

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `StrategyStatus` enum (`engine/schema.py:26`): draft/testing/active/archived — paper 추가 필요
- `StrategyDefinition` model (`engine/schema.py:116`): 전략 정의 스키마, status 필드 포함
- `StrategyCatalog` (`engine/application/trading/strategies.py:15`): registry.json 읽기 + active 필터링
- `api/routers/strategies.py`: PATCH /status 엔드포인트 존재 — LifecycleManager 연동 필요
- Discord bot 인프라: 슬래시 커맨드 + 웹훅 알림 기반

### Established Patterns
- Port/Adapter 패턴: BrokerPort, NotificationPort, RuntimeStorePort (`engine/core/ports.py`)
- JSON 기반 전략 관리: `strategies/{id}/definition.json` + `research.md`
- registry.json: 전략 메타데이터 중앙 관리 (id, name, status, direction, timeframe, regime, definition path)

### Integration Points
- `StrategyCatalog.list_definitions()`: status 필터링 로직 변경 필요 (active 외 상태 지원)
- `StrategyMonitorService`: 전략 로드 시 상태 검증 추가 가능
- `api/routers/strategies.py`: update_status에 LifecycleManager 전이 검증 삽입
- Discord bot: 신규 슬래시 커맨드 `/전략전이` 추가

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-lifecycle-foundation*
*Context gathered: 2026-03-11*
