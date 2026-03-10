# Architecture

> 새 파일 생성 전 기존 모듈로 해결 가능한지 확인 필수.

---

## 데이터 흐름 (3계층)

```
OHLCV → indicator → pattern → signal → alert → order
(원시)   (수치)     (구조)    (판단)   (알림)   (주문)
```

```
[indicators/]  수치 계산 (RSI=45.2, EMA=50000)
      ↓
[patterns/]    구조 인식 (쌍바닥, HH/HL, 캔들 패턴)
      ↓
[analysis/]    방향 판단 (BULL/BEAR/NEUTRAL + 신뢰도)
```

---

## 핵심 파이프라인

```
[Discord 명령] → [pattern_alert] → [pattern_detector + pullback_detector + candle_patterns]
                                   → [risk_manager] → [Discord 전송 + 차트]

[자동 스캐너]  → [pattern_alert._loop()] → 동일 파이프라인 (30초 간격)
```

---

## 디렉토리 역할

| 경로 | 역할 |
|------|------|
| `engine/core/` | 도메인 모델 + DB + 저장소 (models, ports, repository) |
| `engine/data/` | 데이터 수급 (provider, cache, websocket) |
| `engine/indicators/` | 수치 계산 (price, momentum, volume, custom) |
| `engine/patterns/` | 구조 인식 (차트패턴, 캔들, 시장구조, 지지저항) |
| `engine/analysis/` | 방향 판단 + 신호 종합 (direction, confluence, regime) |
| `engine/strategy/` | 전략 룰 (detector, evaluator, risk, plugin) |
| `engine/execution/` | 주문 실행 (paper_broker, 향후 live_broker) |
| `engine/notifications/` | 알림 전송 (discord_webhook, alert_*, 향후 telegram) |
| `engine/interfaces/` | 사용자 접점 (Discord 봇, scanner 런타임) |
| `engine/backtest/` | 백테스트 프레임워크 |
| `engine/application/` | 서비스 계층 (trading orchestration) |
| `api/` | REST API (FastAPI routers) |
| `config/` | 설정 (변경 빈도 낮음) |
| `state/` | 런타임 상태 (자동 생성, 변경 빈도 높음) |
| `strategies/` | 전략 레지스트리 + 정의 + 연구 (STRUCTURE.md 참조) |

---

## 용어 사전

| 용어 | 정의 | 반환 타입 |
|------|------|-----------|
| **indicator** | OHLCV → 수치 계산 결과 | `float`, `ndarray`, `SingleResult` |
| **pattern** | indicator/OHLCV → 구조 인식 | `dict{name, direction}` |
| **signal** | pattern + indicator → 매매 판단 | `TradingSignal(side, action)` |
| **alert** | signal → 사용자 통보 | side effect |
| **order** | alert 승인 → 실제 주문 | `OrderRequest` |

### 혼동 주의

| 쌍 | 구분 |
|----|------|
| indicator / pattern | 숫자 vs 구조/형태 |
| signal / alert | 내부 판단 vs 외부 통보 |
| direction / side | 시장 방향(BULL/BEAR/NEUTRAL) vs 포지션(LONG/SHORT) |
| trend / direction | 구조적 추세(BULLISH/BEARISH/RANGING) vs 최종 판단 |
| confidence / score | 0~1 최종 신뢰도 vs 중간 계산 점수 |
| detector / scanner | 단일 심볼 감지 vs 다수 심볼 순회 |
| filter / detector | 미충족 제거 vs 충족 발견 |
| strategy / signal | 룰셋 정의(JSON) vs 적용 결과 |

### 금지 용어 (모호)

`result`(단독), `data`(단독), `value`(단독), `info`, `process` → 구체적으로 명시

---

## 네이밍 규칙

### 디렉토리

```
1. 복수형 (동종 파일 컬렉션): indicators/, patterns/, alerts/
   구조적 하위 계층: backtest/, domain/, infrastructure/
2. 영어 소문자 + 단일 단어 선호 (snake_case 최소화)
3. 약어 금지: infra/ ✗, infrastructure/ ✓
4. 계층 최대 3단계: engine/indicators/price/
5. __init__.py: 외부 공개 함수만 re-export
6. 파일 5개 이상 → 하위 dir 분리 검토
7. 새 dir 생성 시 기존 dir로 해결 가능한지 먼저 확인
```

### 파일

```
파일명 = [접두사_대상] + [접미사_역할].py

접두사: 대상이 명확할 때 필수 (upbit_, discord_, strategy_)
        dir가 네임스페이스면 생략 가능 (indicators/momentum/rsi.py)
접미사: 역할 표시 (_detector, _scanner, _cache, _store 등)
        지표/패턴 자체는 접미사 없음 (rsi.py, bollinger.py)
```

**접미사 사전:**

| 접미사 | 역할 | 예시 |
|--------|------|------|
| `_provider` | 외부 데이터 조달 | `upbit_provider.py` |
| `_cache` | 캐싱 | `ohlcv_cache.py` |
| `_detector` | 패턴/조건 감지 | `pattern_detector.py` |
| `_scanner` | 주기적 순회 탐색 | `signal_scanner.py` |
| `_filter` | 조건부 필터링 | `watermelon_filter.py` |
| `_manager` | 상태 관리/조율 | `risk_manager.py` |
| `_store` | 영속 저장/로드 | `json_store.py` |
| `_evaluator` | 룰/조건 평가 | `strategy_evaluator.py` |
| `_base` | 추상/인터페이스 | `provider_base.py` |
| (없음) | 지표/패턴 자체 | `rsi.py`, `bollinger.py` |

**동사 사전 (함수명):**

| 동사 | 용도 | 예시 |
|------|------|------|
| `calc_` | 수치 계산 | `calc_adx_filter()` |
| `detect_` | 패턴/구조 감지 | `detect_chart_patterns()` |
| `evaluate_` | 룰/조건 판정 | `evaluate_condition_group()` |
| `judge_` | 최종 방향 판단 | `judge_direction()` |
| `fetch_` | 외부 데이터 조회 | `fetch_ohlcv()` |
| `build_` | 복합 객체 조립 | `build_context()` |
| `is_` / `has_` | bool 판별 | `is_trending()` |
| `apply_` | 변환/적용 | `apply_risk_management()` |

### 파일 분할 규칙

```
1. 파일당 하나의 책임 (단일 지표, 단일 패턴, 단일 기능)
2. 300줄 초과 시 분할 검토
3. 공유 타입/유틸 → base.py에 집중
4. 하위 호환 re-export는 __init__.py에서만
5. 테스트는 원본과 1:1 매칭 (test_xxx.py)
```

---

## 새 전략 추가 체크리스트

1. `engine/strategy/`에 감지기 작성 (PatternSignal 재사용)
2. `pattern_alert.py` → `_analyze_tf()`에 감지기 호출 추가
3. `_build_message()`에 한글 패턴명 매핑 추가
4. `commands/scanner.py` → `_PATTERN_HELP`에 설명 추가
5. `backtest/pattern_backtest.py`에 백테스트 함수 추가
6. 테스트 작성 (감지/미감지/edge case, 커버리지 80%+)
7. `strategies/registry.json`에 항목 추가 + 전략 dir 생성

---

## 금지 사항

- **새 스캐너 파일 금지** — `pattern_alert.py`가 유일한 오케스트레이터
- **버전 파일 금지** — v2, v3 파일명 사용 안 함 (git으로 관리)
- **재정의/재구현 금지** — 기존 모듈의 기능을 다른 파일에 다시 만들지 않음
- **기능/이름 변경 시 제안→승인→적용** — 임의 적용 금지
- **폐기 전략 재구현 금지** — strategies/deprecated 참조
- **레거시 부활 금지**
- **모호한 파일명 금지** — 접두사(대상) + 접미사(역할) 준수
