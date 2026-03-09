# Strategy Review — 전략 탐색 및 검증 결과

## 검증 환경

- 데이터: Binance 1H (2017-08 ~ 2025-03, 7.5년)
- 교차 검증: Binance + OKX + Bybit (3개 거래소)
- 벤치마크: BULL 7구간 / BEAR 5구간 / RANGE 6구간 (총 18구간)
- 고정금액: 자본 10만원, 거래당 1만원, 복리 없음
- 수수료: 0.04% taker (편도), 진입+청산 = 0.08%
- 레버리지: 3x
- 수수료 계산: (raw_pnl - fee_rate*2) * leverage

---

## 1. 지표 기반 전략

### 1-1. EMA Stack (Triple EMA 추세추종)

| 항목 | 내용 |
|------|------|
| 조건 | EMA8 > EMA21 > EMA55 (정배열) + ADX > 25 + 풀백 |
| 방향 | LONG/SHORT |
| TP | entry + 2.4 * SL거리 |
| SL | EMA55 * 0.998 |
| 결과 | LONG only + BULL/RANGE: +38,458원 |
| 판정 | **보류** — 패턴 전략 대비 열등, 하지만 안정적 (MDD 9.4%) |

### 1-2. BB Squeeze (Bollinger + Keltner)

| 항목 | 내용 |
|------|------|
| 조건 | BB가 KC 안에 진입(squeeze) → 해제 시 MACD 방향 진입 |
| 결과 | WR 34.4%, -17,790원 |
| 판정 | **폐기** — 전 구간 적자 |

### 1-3. BB Bounce (볼린저 반등)

| 항목 | 내용 |
|------|------|
| 조건 | close <= BB하단 + RSI < 30 + ADX < 25 |
| 결과 | SL 버그 수정 후 WR 25.6%, -29,375원 |
| 판정 | **폐기** — SL 계산 버그 있었음. 수정 후 전멸 |

### 1-4. 횡보 전략 4종 (Grid / Donchian / RSI+S&R / Keltner)

| 전략 | 결과 |
|------|------|
| Grid Trading | 적자 |
| Donchian Breakout | 적자 |
| RSI + Support/Resistance | 적자 |
| Keltner Mean Reversion | 적자 |
| 판정 | **전멸** — 크립토 선물 횡보장에서 수수료+변동성에 잡아먹힘 |

### 1-5. 수박지표 (Watermelon Indicator)

| 항목 | 내용 |
|------|------|
| 조건 | EMA+StdDev 바닥 축적 신호 (D1 기준) |
| crypto_fast | 15건, WR 60%, +40,749원, MDD 3.3% |
| crypto_mid | 13건, WR 69.2%, +25,062원, MDD 4.2% |
| 판정 | **보류** — 수익률 좋지만 2년간 15건. 독립 운용 불가, 보조 신호 가능 |

---

## 2. 패턴 기반 전략

### 2-1. Double Bottom (쌍바닥) — LONG

| 항목 | 내용 |
|------|------|
| 조건 | 로컬 저점 2개 유사(2% 이내) + 넥라인 돌파 |
| SL | 두 저점 중 낮은 값 * 0.998 |
| TP | entry + 2.0 * SL거리 |
| BULL 결과 | Binance +291K, OKX +225K, Bybit +137K (구간승률 16/16) |
| BEAR 결과 | 적자 (-79K) |
| 판정 | **채택 (BULL 전용)** |

### 2-2. Ascending Triangle (상승삼각형) — LONG

| 항목 | 내용 |
|------|------|
| 조건 | 수평 저항(고점 유사 1% 이내) + 상승 지지(저점 상승) + 돌파 |
| SL | 최근 저점 * 0.998 |
| TP | entry + 2.0 * SL거리 |
| BULL 결과 | Binance +113K, OKX +81K, Bybit +52K (구간승률 16/16) |
| BEAR 결과 | 적자 (-54K) |
| 판정 | **채택 (BULL 전용)** |

### 2-3. Double Top (쌍봉) — SHORT

| 항목 | 내용 |
|------|------|
| 조건 | 로컬 고점 2개 유사(2% 이내) + 넥라인 하향 이탈 |
| SL | 두 고점 중 높은 값 * 1.002 |
| TP | entry - 2.0 * SL거리 |
| BEAR 결과 | Binance +221K, OKX +103K, Bybit +54K (구간승률 10/10) |
| BULL 결과 | 적자 (-249K) |
| 판정 | **채택 (BEAR 전용)** |

### 2-4. Descending Triangle (하강삼각형) — SHORT

| 항목 | 내용 |
|------|------|
| 조건 | 수평 지지(저점 유사 1% 이내) + 하강 저항(고점 하락) + 하방 돌파 |
| SL | 최근 고점 * 1.002 |
| TP | entry - 2.0 * SL거리 |
| BEAR 결과 | Binance +79K, OKX +39K, Bybit +35K (구간승률 10/10) |
| BULL 결과 | 적자 (-48K) |
| 판정 | **채택 (BEAR 전용)** |

### 2-5. Bull Flag (상승깃발) — LONG

| 항목 | 내용 |
|------|------|
| 결과 | 전 구간 적자 |
| 판정 | **폐기** |

### 2-6. Bear Flag (하락깃발) — SHORT

| 항목 | 내용 |
|------|------|
| 결과 | BEAR에서 +12K이지만 다른 레짐 적자, 구간승률 낮음 |
| 판정 | **폐기** — DESC_TRIANGLE이 상위 호환 |

---

## 3. 타임프레임 검증

| TF | BULL 성능 | BEAR 성능 | 판정 |
|----|----------|----------|------|
| **1H** | WR 50%+, 구간승률 100% | WR 47%+, 구간승률 100% | **최적** |
| 30m | WR 47%, BULL만 유효 | BEAR 붕괴 | 부적합 |
| 15m | WR 43%, 급격 열화 | 불안정 | 부적합 |
| 5m | WR 41%, 전멸 | 전멸 | 부적합 |

---

## 4. 최종 포트폴리오

```
BULL (상승장)
  ├─ Double Bottom (LONG) — 주력
  └─ Ascending Triangle (LONG) — 보조

BEAR (하락장)
  ├─ Double Top (SHORT) — 주력
  └─ Descending Triangle (SHORT) — 보조

RANGE (횡보장)
  └─ 미매매 (현금 보유)
```

### 운용 규칙

1. **방향 필터: pred_multi (선행 예측)** — 후행 레짐 판단(EMA200) 대체
   - Momentum (20봉 수익률 방향)
   - EMA Cross (EMA21 vs EMA55)
   - Structure (고점/저점 상승·하강 패턴)
   - 3개 중 2개 이상 동의 → 해당 방향, 아니면 NEUTRAL
2. pred_multi == LONG → LONG 패턴만 활성화 (Double Bottom, Asc Triangle)
3. pred_multi == SHORT → SHORT 패턴만 활성화 (Double Top, Desc Triangle)
4. pred_multi == NEUTRAL → 전략 비활성, 현금 대기
5. 타임프레임: 1H 고정
6. 동시 포지션: 심볼당 1개

### 검증 근거

- 3개 거래소 (Binance/OKX/Bybit) 교차 검증
- 18개 벤치마크 구간 (BULL 7 / BEAR 5 / RANGE 6)
- BULL 전략 구간승률: 16/16 (100%)
- BEAR 전략 구간승률: 10/10 (100%)
- 2017~2025 전체 기간 커버
- look-ahead bias 방지 확인
- **pred_multi vs 후행 레짐 필터 비교** (Binance BTC 전체 구간):
  - pred_multi: +55,624원, MDD 21.1%
  - 후행 레짐(EMA200): +41,368원, MDD 27.7%
  - pred_multi가 수익 +34%, MDD -24% 개선

---

## 5. 폐기 전략 목록

| 전략 | 유형 | 폐기 사유 |
|------|------|----------|
| BB Squeeze | 지표 | 전 구간 적자, WR 34% |
| BB Bounce | 지표 | SL 버그 수정 후 전멸, 평균회귀 크립토 부적합 |
| Grid Trading | 횡보 | 수수료에 잠식 |
| Donchian Breakout | 횡보 | 적자 |
| RSI + S/R | 횡보 | 적자 |
| Keltner MR | 횡보 | 적자 |
| Bull Flag | 패턴 | 전 구간 적자 |
| Bear Flag | 패턴 | DESC_TRIANGLE 대비 열등 |
| EMA Stack SHORT | 지표 | BEAR에서 적자 |

---

## 6. 미결 사항

- [x] 레짐 필터 → pred_multi 선행 예측으로 대체 완료
- [x] 통합 실시간 엔진 구축 완료
  - `engine/strategy/pattern_detector.py` — 패턴 감지 (백테스트/실시간 공용)
  - `engine/strategy/pattern_scanner.py` — 실시간 스캐너 (pred_multi + 패턴 + 신호)
  - 기존 `TradingOrchestrator` + `PaperBroker` 연동
- [x] 슬리피지 시뮬레이션 완료 (`engine/backtest/slippage.py`)
  - 고정/변동성/혼합 3개 모델
  - 영향: 0.01% 편도 → 거래당 약 0.06% 추가 비용 (3x 레버리지)
  - 수익 전략에 미미한 영향 (DOUBLE_BOTTOM 104.5% → 99.5%)
- [x] 리스크 관리 완료 (`engine/strategy/risk_manager.py`)
  - 심볼당 동시 포지션 1개
  - 전체 동시 포지션 5개 제한
  - 일일 최대 손실 5% 제한
  - 연속 SL 3회 시 해당 심볼 일시 정지
  - SL 후 5봉 쿨다운
- [x] 수박지표 보조 신호 통합 완료 (`engine/strategy/watermelon_filter.py`)
  - D1 수박지표 활성 시 LONG 패턴 확신도 +0.2 부스트
  - 독립 신호 생성 안함, LONG 패턴 존재 시에만 보조 역할
  - 스캐너 설정: `use_watermelon=True` (기본 활성)
- [x] Upbit KRW 마켓 지원 완료 (`engine/data/provider_upbit.py`)
  - pyupbit 기반 DataProvider 구현 (ccxt 우회)
  - 심볼 자동 변환: BTC/KRW ↔ KRW-BTC
  - 역방향 페이징 + rate limiting (8 req/s)
  - 팩토리 자동 라우팅: `get_provider("crypto_spot", exchange="upbit")`
