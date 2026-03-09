# Architecture — 모듈 책임 맵

> 새 전략/기능 추가 시 반드시 이 문서를 먼저 읽고, 해당 모듈에 추가할 것.
> 새 파일 생성 전 기존 모듈로 해결 가능한지 확인 필수.

---

## 핵심 파이프라인

```
[Discord 명령] → [pattern_alert] → [pattern_detector + pullback_detector + candle_patterns]
                                   → [risk_manager] → [Discord 전송 + 차트]

[자동 스캐너]  → [pattern_alert._loop()] → 동일 파이프라인 (30초 간격)
```

---

## 모듈 책임

### engine/strategy/ — 전략 핵심 (새 전략은 여기에만 추가)

| 파일 | 책임 | 수정 시점 |
|------|------|----------|
| `pattern_detector.py` | 차트 패턴 감지 (쌍바닥/쌍봉/삼각형) + SR 기반 SL/TP | 새 차트 패턴 추가 시 |
| `pullback_detector.py` | EMA 눌림목 패턴 감지 | 눌림목 로직 변경 시 |
| `candle_patterns.py` | TA-Lib 캔들 패턴 (21종) 스캔 + 방향 편향 | 캔들 패턴 추가/제거 시 |
| `pattern_alert.py` | 스캐너 오케스트레이터 (분석→메시지→전송) | UI/전송 로직 변경 시 |
| `pattern_scanner.py` | 실시간 스캐너 (pred_multi + 패턴 + 오케스트레이터 연동) | 실시간 매매 로직 변경 시 |
| `risk_manager.py` | 리스크 관리 (동시포지션/일일손실/쿨다운) | 리스크 룰 변경 시 |
| `watermelon_filter.py` | 수박지표 보조 신호 (LONG 확신도 부스트) | 보조 지표 추가 시 |
| `detector_registry.py` | 감지기 스펙 등록/로드 (JSON 기반) | 감지기 설정 구조 변경 시 |
| `condition.py` | 조건식 평가 엔진 (JSON 전략 정의용) | 조건 문법 확장 시 |
| `engine.py` | 전략 실행 엔진 (StrategyDefinition → 시그널) | 전략 스키마 변경 시 |
| `alert_v2.py` | 거래소 간 비교 알림 (Binance/OKX/Bybit) | 멀티거래소 알림 변경 시 |
| `scheduler.py` | 봇 스케줄러 (포지션 추적 + 알림 전송) | 스케줄링 로직 변경 시 |
| `risk.py` | 리스크 계산 유틸 (SL/TP 비율) | SL/TP 계산식 변경 시 |

### engine/data/ — 데이터 조달

| 파일 | 책임 |
|------|------|
| `base.py` | DataProvider 팩토리 (`get_provider()`) |
| `provider_upbit.py` | Upbit REST API (pyupbit, 역방향 페이징, rate limit) |
| `provider_crypto.py` | Binance/OKX/Bybit (ccxt) |
| `provider_fdr.py` | 한국 주식 (FinanceDataReader) |
| `upbit_cache.py` | 실시간 캐시 (닫힌 봉 캐시 + 현재 봉 갱신) |
| `upbit_ranking.py` | Upbit KRW 상위 N 코인 (거래량 기준, 5분 캐시) |
| `upbit_ws.py` | Upbit WebSocket (실시간 체결) |
| `cache.py` | 범용 OHLCV 캐시 |

### engine/analysis/ — 분석 도구 (독립 함수, 전략에서 import)

| 파일 | 책임 |
|------|------|
| `chart_patterns.py` | 12종 차트 패턴 감지 (swing 기반) |
| `key_levels.py` | 지지/저항 레벨 계산 |
| `market_structure.py` | 시장 구조 분석 (HH/HL/LH/LL) |
| `confluence.py` | 합류 점수 계산 |
| `mtf_confluence.py` | 멀티타임프레임 합류 |
| `trend_strength.py` | ADX 필터 |
| `volume_profile.py` | 볼륨 프로파일 (VPVR) |
| `bollinger.py` | 볼린저 밴드 위치 |
| `confidence.py` | 신뢰도 점수 계산 |
| `cross_exchange.py` | 거래소 간 리드-래그 |
| `exchange_dominance.py` | 거래소 도미넌스 분석 |
| `pullback.py` | 풀백 품질 측정 |
| `smc.py` | Smart Money Concepts (CHoCH/BOS/OB) |
| `candle_patterns.py` | 캔들 패턴 (analysis 레벨, chart_patterns 보조) |

### engine/backtest/ — 백테스트

| 파일 | 책임 |
|------|------|
| `pattern_backtest.py` | **주력** — 6종 패턴 백테스트 |
| `confluence_backtest_v2.py` | 2-pass 합류 백테스트 (1H→5m) |
| `confluence_backtest.py` | 1-pass 합류 백테스트 (4H) — v2 통합 후 삭제 예정 |
| `strategy_base.py` | 공용 기반 (StrategyTrade, load_ohlcv, calc_metrics) |
| `metrics.py` | 성과 지표 (WR, PF, Sharpe, MDD) |
| `benchmark_periods.py` | BULL/BEAR/RANGE 벤치마크 구간 정의 |
| `direction_predictor.py` | pred_multi 방향 예측기 |
| `slippage.py` | 슬리피지 모델 (고정/변동성/혼합) |
| `report.py` | 백테스트 리포트 생성 |
| `runner.py` | 전략 실행기 (StrategyDefinition 기반) |
| `optimizer.py` | 파라미터 최적화 (grid search) |
| `scanner_backtest.py` | 스캐너 백테스트 프레임워크 |
| `scanner_optimizer.py` | 스캐너 파라미터 최적화 |
| `auto_reoptimize.py` | 자동 재최적화 스케줄러 |

### engine/interfaces/ — 외부 인터페이스

| 경로 | 책임 |
|------|------|
| `discord/control_bot.py` | Discord 봇 부트스트랩 (guild sync) |
| `discord/commands/scanner.py` | `/스캔`, `/자동시작`, `/자동중지`, `/순위`, `/설정`, `/패턴` |
| `discord/commands/analysis.py` | `/분석` 명령 |
| `discord/commands/pattern.py` | `/패턴감지` 명령 |
| `discord/commands/runtime.py` | `/상태`, `/일시정지`, `/재개`, `/모드` |
| `discord/commands/orders.py` | `/대기주문`, `/승인`, `/거부` |
| `discord/commands/base.py` | CommandPlugin 기반 클래스 |
| `scanner/runtime.py` | 스캐너 런타임 관리 |

### engine/alerts/ — 알림 전송

| 파일 | 책임 |
|------|------|
| `discord.py` | Signal 모델 + webhook 전송 |
| `discord_bot.py` | 봇 인스턴스 관리 |
| `bot_config.py` | 봇 설정 로드 |
| `positions.py` | 포지션 추적 + 알림 |

### 기타

| 경로 | 책임 |
|------|------|
| `engine/schema.py` | 전략 정의 스키마 (Pydantic) |
| `engine/cli.py` | CLI 명령어 (typer) |
| `engine/regime/` | 레짐 판단 (crypto, sector) |
| `engine/store/` | DB 저장소 (SQLite) |
| `engine/knowledge/` | 지식 태깅 시스템 |
| `engine/indicators/` | 지표 계산 (compute, registry, custom) |
| `engine/plugins/` | 플러그인 등록/실행 |
| `engine/infrastructure/` | 인프라 (paper_broker, webhook, json_store) |
| `engine/domain/trading/` | 도메인 모델 (Trade, Position, ports) |

---

## 새 전략 추가 체크리스트

1. **감지기 작성**: `engine/strategy/` 에 `{name}_detector.py` 생성
   - 함수 시그니처: `detect_{name}(df: pd.DataFrame, ...) -> list[PatternSignal]`
   - `PatternSignal` 재사용 (pattern_detector.py에서 import)
   - SR 기반 SL/TP 헬퍼 재사용 (`_calc_long_tp`, `_calc_short_tp`)

2. **pattern_alert.py 연동**: `_analyze_tf()` 에 감지기 호출 추가
   - import 추가
   - 결과를 signals 리스트에 append

3. **메시지 포맷**: `_build_message()` 에 한글 패턴명 매핑 추가

4. **Discord 헬프**: `commands/scanner.py` → `_PATTERN_HELP` 에 설명 추가

5. **백테스트**: `backtest/pattern_backtest.py` 에 백테스트 함수 추가

6. **테스트 작성**: `tests/test_{name}_detector.py`
   - 최소: 감지 정상, 미감지 정상, edge case
   - 커버리지 80%+

7. **이 문서 업데이트**: 모듈 책임 테이블에 추가

---

## 금지 사항

- **새 스캐너 파일 금지**: `pattern_alert.py`가 유일한 스캐너 오케스트레이터
- **중복 백테스트 스크립트 금지**: 파라미터는 config/JSON으로 분리
- **레거시 부활 금지**: `engine/legacy/` 삭제됨, 복원 불가
- **폐기 전략 재구현 금지**: BB Squeeze, BB Bounce, Grid, Donchian, RSI+S/R, Keltner MR, Bull/Bear Flag (STRATEGY_REVIEW.md 참조)

---

## 폐기 전략 목록 (재구현 금지)

| 전략 | 폐기 사유 | 삭제일 |
|------|----------|--------|
| BB Squeeze | 전 구간 적자, WR 34% | 2026-03-09 |
| BB Bounce | SL 버그 수정 후 전멸 | 2026-03-09 |
| Grid Trading | 수수료에 잠식 | 2026-03-09 |
| Donchian Breakout | 적자 | 2026-03-09 |
| RSI + S/R | 적자 | 2026-03-09 |
| Keltner MR | 적자 | 2026-03-09 |
| Bull Flag | 전 구간 적자 | 2026-03-09 |
| Bear Flag | DESC_TRIANGLE 대비 열등 | 2026-03-09 |
| EMA Stack SHORT | BEAR에서 적자 | 2026-03-09 |
| Upbit Scanner (10종) | pattern_alert로 교체 | 2026-03-09 |
| Swing Scanner (6종) | pattern_alert로 교체 | 2026-03-09 |

---

## 채택 전략 (운용 중)

| 전략 | 방향 | 레짐 | 타임프레임 | 검증 |
|------|------|------|-----------|------|
| Double Bottom | LONG | BULL | 1H (+ 5m/15m/30m/4h 스캔) | 3거래소 16/16 구간승률 |
| Double Top | SHORT | BEAR | 1H | 3거래소 10/10 구간승률 |
| Ascending Triangle | LONG | BULL | 1H | 3거래소 16/16 구간승률 |
| Descending Triangle | SHORT | BEAR | 1H | 3거래소 10/10 구간승률 |
| Pullback (EMA) | LONG/SHORT | 추세 | 4H 최적 | 144거래 53.5% WR, +62.6R |
| TA-Lib 캔들 21종 | 보조 | 전체 | 전체 | 보조 신호 (방향 편향) |
| 수박지표 | 보조 (LONG) | BULL | D1 | 15건 WR 60% (독립 불가) |

---

*최종 업데이트: 2026-03-09 — 코드 다이어트 후 (33,735줄 → 19,068줄)*
