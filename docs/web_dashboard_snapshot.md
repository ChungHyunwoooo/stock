# Web Dashboard 스냅샷 (삭제 전 기록)

엔진 완성 후 대시보드/포지션 관리 UI 재구현 시 참고.

## 스택
- Next.js (App Router) + TypeScript + Tailwind + shadcn/ui
- API: FastAPI 백엔드 (/stock/api)
- 배포: nginx reverse proxy (deploy/)

## 페이지 (7,490줄)
| 페이지 | 기능 |
|--------|------|
| `/` | 메인 대시보드 |
| `/strategies` | 전략 목록 + CRUD |
| `/strategies/[id]` | 전략 상세 |
| `/builder` | 전략 빌더 (조건식 GUI) |
| `/backtest` | 백테스트 실행 + 결과 |
| `/screener` | 실시간 스크리너 |
| `/alerts` | Discord 알림 설정 + 스캔 |
| `/bot` | 봇 제어 (시작/정지/설정/포지션) |
| `/regime` | 레짐 분석 |
| `/knowledge` | 지식 태깅 시스템 |

## 주요 컴포넌트
- `candlestick-chart.tsx` — OHLCV 차트
- `equity-chart.tsx` — 수익곡선
- `indicator-chart.tsx` — 지표 오버레이
- `symbol-search.tsx` — 심볼 검색 (Command)
- `navbar.tsx` — 네비게이션
- `builder/` — 조건식 빌더 (indicator-row, condition-row)

## API 클라이언트 (`lib/api.ts`)
- strategies: list, get, create, update, delete
- backtests: run, scan, list
- alerts: discord config, scan
- bot: status, start, stop, config, positions, detectors
- screener: scan
- regime: analyze
- knowledge: list, search, tags
- symbols: list

## 재구현 시 주의
- shadcn/ui 컴포넌트 16종 사용
- API 엔드포인트는 `api/routers/` 참조
- git에서 `web/` 복원 가능 (커밋 f010b1c 이전)
