# RSI Divergence -- Research

## 출처
- **논문/URL**: Constance Brown, *Technical Analysis for the Trading Professional*, McGraw-Hill, 1999. Andrew Cardwell RSI Divergence 이론.
- **저자/커뮤니티**: Andrew Cardwell (RSI 재해석), Constance Brown (체계화)

## 전략 로직 요약
- **진입 조건**: RSI(14)가 30 이하에서 bullish divergence (가격은 lower low, RSI는 higher low) 발생 시 LONG. RSI(14)가 70 이상에서 bearish divergence (가격은 higher high, RSI는 lower high) 발생 시 SHORT.
- **청산 조건**: RSI가 50 크로스 시 또는 ATR(14) 기반 stop-loss 도달 시
- **사용 지표**: RSI(14), ATR(14)
- **타임프레임**: 1h
- **방향**: both (long + short)

## 백테스트 결과 요약
| 항목 | 값 |
|------|-----|
| 기간 | 이론적 참고치 (실 백테스트 Phase 2 예정) |
| 총 수익률 | N/A (문헌 기준 참고치) |
| 승률 | ~55-60% (문헌 기준) |
| Sharpe | ~1.0-1.5 (문헌 기준) |
| 최대 DD | N/A (실측 필요) |

## 메모
Phase 1 워크플로우 증명용 레퍼런스. Phase 2에서 실 백테스트 수행 예정.
definition.json의 entry/exit 조건은 simplified 표현 -- divergence 패턴의 정밀한 조건 표현은 Phase 2 condition_evaluator 확장 후 업데이트.
