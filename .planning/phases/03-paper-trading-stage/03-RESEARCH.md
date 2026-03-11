# Phase 3: Paper Trading Stage - Research

**Researched:** 2026-03-11
**Domain:** PaperBroker 영속화, Paper 성과 조회, Paper→Live 승격 게이트
**Confidence:** HIGH

## Summary

Phase 3은 기존 in-memory PaperBroker를 SQLite 영속화하고, paper 성과를 3채널(CLI/API/Discord)로 조회하며, 정량 기준 충족 시에만 paper→active 승격을 허용하는 게이트를 구현한다. 기존 코드베이스에 Phase 2에서 확립된 패턴(Repository, DB migration, 3채널 인터페이스, Discord 확인 버튼)이 이미 존재하므로, 새로운 라이브러리 없이 기존 패턴을 확장하는 것이 핵심이다.

TradeRecord(broker="paper")가 이미 DB에 존재하므로 거래 이력은 추가 테이블 없이 활용 가능하다. 필요한 것은 (1) paper_balances/paper_pnl_snapshots 테이블, (2) PaperBroker 초기화 시 DB 복원, (3) 승격 기준 검증 로직(PromotionGate), (4) LifecycleManager.transition()에 gate 삽입이다.

**Primary recommendation:** 기존 Repository/Migration/3채널 패턴을 그대로 복제 확장. 새 라이브러리 불필요. TradeRepository.summary()를 승격 판정 메트릭 계산의 기반으로 재사용.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **글로벌 원칙: 하드코딩 금지** — 모든 수치/임계치는 config 파일 기반 + 전략별 오버라이드 가능
- **저장 범위: 전체** — 포지션 + 잔고 + 일별 PnL 스냅샷 + 미체결 주문 + 전략별 세션 메타데이터
- **저장소: 기존 SQLite DB 확장** — paper_positions, paper_balances, paper_pnl_snapshots 등 테이블 추가. 기존 database.py + Repository 패턴 재사용
- **PnL 스냅샷: 이중 기록** — 거래 발생 시마다 누적 PnL 기록 + 일별 1회 스냅샷
- **재시작 시 미체결 주문: 전부 취소** — 포지션/잔고만 복원
- **승격 기준 수치 (기본값, config + 전략별 오버라이드):**
  - 최소 페이퍼 기간: 7일
  - 최소 거래 건수: 타임프레임 매핑 (1m~15m→20건, 1h~4h→10건, 1d~1w→5건)
  - Sharpe >= 0.3, 승률 >= 30%, 최대DD <= -20%, 누적 PnL > 0
  - StrategyDefinition에 promotion_gates 필드 추가
- **Paper 성과 조회: CLI + API + Discord 전부** — 전략별 + 전체 요약 + 심볼별
- **계산 방식: 혼합** — 일별 집계 캐시 + 당일분만 실시간 계산
- **승격 가능 표시: 진행률 + 예상 승격 시점**
- **자동 체크: 주기적** — config 설정 주기
- **알림: 1회 + 대시보드 뱃지** — 기준 최초 충족 시 Discord 알림 1회
- **승격 실행: 확인 버튼** — `/전략승격 [strategy_id]` → Embed + 확인/취소
- **승격 후처리: 상태 전이 + Discord 알림 + 페이퍼 성과 아카이빙**
- **미충족 시 피드백: 상세 리포트** — 미충족 항목별 현재값/기준값 비교 + 일별 PnL 추이 + equity curve 차트 Discord Embed

### Claude's Discretion
- PaperBroker DB 스키마 상세 (테이블 구조, 칼럼, 인덱스)
- 자동 체크 주기 기본값
- PnL 스냅샷 집계 + 당일분 실시간 합산 구현 상세
- 예상 승격 시점 추정 알고리즘
- Discord Embed 레이아�트 상세
- CLI rich table 레이아웃 상세
- API 엔드포인트 경로/응답 스키마

### Deferred Ideas (OUT OF SCOPE)
None
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LIFE-02 | 페이퍼 트레이딩 단계에서 PaperBroker 상태가 세션 간 영속되고 PnL이 추적된다 | DB 스키마 설계 + PaperBroker __init__ 복원 로직 + PnL 스냅샷 이중 기록 패턴 |
| LIFE-03 | Paper→Live 승격 시 Sharpe/승률/기간/최대DD 기준을 자동 검증하고, 미충족 시 승격을 차단한다 | PromotionGate 클래스 + LifecycleManager.transition() gate 삽입 + Discord 확인 버튼 패턴 |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 기존 사용중 | ORM + DB migration | 프로젝트 전체 DB 계층 |
| Pydantic | 기존 사용중 | Config/Schema 검증 | StrategyDefinition 등 전 도메인 |
| discord.py | 기존 사용중 | Discord 봇 + slash commands | Phase 1에서 확립 |
| FastAPI | 기존 사용중 | REST API | Phase 2에서 확립 |
| Rich | 기존 사용중 | CLI 테이블 출력 | Phase 2 history_cli 패턴 |
| matplotlib | 기존 사용중 | equity curve 차트 생성 | Phase 2 report.py |
| numpy/pandas | 기존 사용중 | 수치 계산 | Sharpe/DD 계산 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| quantstats | 기존 사용중 | 성과 분석 리포트 | 승격 판정 리포트 생성 시 |

### Alternatives Considered
없음 — 모든 라이브러리가 이미 프로젝트에 존재. 새 의존성 추가 불필요.

## Architecture Patterns

### Recommended Project Structure
```
engine/
├── execution/
│   └── paper_broker.py          # DB 영속화 확장 (기존 파일 수정)
├── core/
│   ├── db_models.py             # PaperBalance, PaperPnlSnapshot 모델 추가
│   ├── database.py              # _migrate_paper_phase3() 추가
│   └── repository.py            # PaperRepository 추가
├── strategy/
│   ├── lifecycle_manager.py     # transition()에 gate 검증 삽입
│   └── promotion_gate.py        # NEW: 승격 기준 검증 로직
├── backtest/
│   └── report.py                # 승격 리포트 생성 함수 추가 (재사용)
├── interfaces/
│   └── discord/commands/
│       └── paper_trading.py     # NEW: /페이퍼현황, /전략승격 커맨드
api/
└── routers/
    └── paper.py                 # NEW: Paper 성과 조회 API
config/
└── paper_trading.json           # NEW: 승격 기준 기본값 + 체크 주기
```

### Pattern 1: DB 영속화 (Phase 2 Migration 패턴 재사용)
**What:** PRAGMA table_info + ALTER TABLE ADD COLUMN idempotent migration
**When to use:** 새 테이블/칼럼 추가 시
**Example:**
```python
# Source: engine/core/database.py (기존 _migrate_backtests_phase2 패턴)
def _migrate_paper_phase3(engine: Engine) -> None:
    """Add Phase 3 paper trading tables if missing."""
    with engine.connect() as conn:
        # PaperBalance 테이블
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS paper_balances (
                id INTEGER PRIMARY KEY,
                strategy_id VARCHAR(100) NOT NULL,
                balance REAL NOT NULL,
                equity REAL NOT NULL,
                unrealized_pnl REAL DEFAULT 0.0,
                snapshot_at DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # PaperPnlSnapshot 테이블
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS paper_pnl_snapshots (
                id INTEGER PRIMARY KEY,
                strategy_id VARCHAR(100) NOT NULL,
                date VARCHAR(10) NOT NULL,
                cumulative_pnl REAL NOT NULL,
                daily_pnl REAL NOT NULL,
                trade_count INTEGER DEFAULT 0,
                win_count INTEGER DEFAULT 0,
                equity REAL NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(strategy_id, date)
            )
        """))
        conn.commit()
```

### Pattern 2: Repository 패턴 (BacktestRepository 복제)
**What:** Session 기반 CRUD, 모든 DB 접근은 Repository 경유
**When to use:** paper_balances, paper_pnl_snapshots 접근
**Example:**
```python
# Source: engine/core/repository.py (BacktestRepository 패턴)
class PaperRepository:
    def save_balance(self, session: Session, record: PaperBalance) -> PaperBalance:
        session.add(record)
        session.flush()
        return record

    def get_daily_snapshots(
        self, session: Session, strategy_id: str, limit: int = 90
    ) -> list[PaperPnlSnapshot]:
        stmt = (
            select(PaperPnlSnapshot)
            .where(PaperPnlSnapshot.strategy_id == strategy_id)
            .order_by(PaperPnlSnapshot.date.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())
```

### Pattern 3: PromotionGate (순수 도메인 로직)
**What:** 승격 기준 검증을 담당하는 독립 클래스. 외부 서비스 의존 없음.
**When to use:** LifecycleManager.transition()에서 paper→active 전이 시 호출
**Example:**
```python
@dataclass
class PromotionResult:
    passed: bool
    checks: dict[str, PromotionCheck]  # gate_name -> check result
    summary: str

@dataclass
class PromotionCheck:
    name: str
    required: float
    actual: float
    passed: bool

class PromotionGate:
    def evaluate(
        self, strategy_id: str, config: PromotionConfig
    ) -> PromotionResult:
        """모든 승격 기준을 검증하고 결과 반환."""
        ...
```

### Pattern 4: Discord 확인 버튼 (Phase 1 TransitionConfirmView 재사용)
**What:** `/전략승격` → Embed 표시 → 확인/취소 버튼 → 확인 시 transition 실행
**When to use:** 승격 커맨드 구현 시
**Example:**
```python
# Source: engine/interfaces/discord/commands/lifecycle.py
class PromotionConfirmView(discord.ui.View):
    def __init__(self, strategy_id, promotion_result, context):
        super().__init__(timeout=60)
        self.strategy_id = strategy_id
        self.result = promotion_result
        self.context = context

    @discord.ui.button(label="확인", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        # LifecycleManager.transition() 호출
        entry = self.context.lifecycle_manager.transition(
            self.strategy_id, "active", reason="승격 승인"
        )
        # 승격 후처리: Discord 알림 + 아카이빙
        ...
```

### Pattern 5: 3채널 인터페이스 (Phase 2 확립 패턴)
**What:** 동일 비즈니스 로직을 CLI(Rich table) + API(FastAPI router) + Discord(slash command)로 노출
**When to use:** Paper 성과 조회
**Architecture:**
```
PaperRepository (DB 접근)
    └── paper_cli.py (Rich table, CLI 진입점)
    └── api/routers/paper.py (FastAPI, REST)
    └── discord/commands/paper_trading.py (slash command, Embed)
```

### Anti-Patterns to Avoid
- **PaperBroker 내부에 DB 로직 직접 구현:** Repository 패턴 위반. PaperBroker는 Repository를 주입받아 사용
- **승격 기준 하드코딩:** config 파일 기반 + 전략별 오버라이드 필수
- **LifecycleManager에 gate 로직 직접 작성:** PromotionGate를 별도 클래스로 분리하고 LifecycleManager는 호출만
- **TradeRecord 재정의:** 기존 TradeRecord(broker="paper")를 그대로 활용. 별도 paper 거래 테이블 만들지 않음

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sharpe ratio 계산 | 직접 수식 구현 | numpy 기반 일별 수익률 계산 또는 quantstats.stats.sharpe() | 연환산 계수, 무위험 수익률 처리 미묘함 |
| Equity curve 차트 | 직접 이미지 생성 | report.py의 _equity_png_b64() 재사용 | 이미 검증된 차트 생성 함수 존재 |
| Discord Embed 레이아웃 | 처음부터 작성 | BacktestHistoryPlugin의 _build_history_embed() 패턴 복제 | 일관된 UX |
| DB migration | Alembic 도입 | PRAGMA table_info + CREATE TABLE IF NOT EXISTS | Phase 2에서 확립된 경량 패턴, 의존성 추가 불필요 |
| CLI rich table | 처음부터 작성 | history_cli.py의 show_history() 패턴 복제 | 일관된 UX |
| 확인/취소 버튼 | 새 View 설계 | lifecycle.py TransitionConfirmView 패턴 복제 | 검증된 UX 흐름 |

## Common Pitfalls

### Pitfall 1: PaperBroker 초기화 시 DB 세션 수명 관리
**What goes wrong:** PaperBroker가 장시간 실행되므로 __init__에서 열은 DB 세션이 stale해짐
**Why it happens:** SQLite는 장시간 열린 세션에서 WAL 파일 증가, lock 이슈 발생 가능
**How to avoid:** PaperBroker는 DB 세션을 보유하지 않음. 각 DB 작업마다 `with get_session() as session:` 패턴 사용 (기존 프로젝트 패턴)
**Warning signs:** "database is locked" 에러, 메모리 증가

### Pitfall 2: PnL 스냅샷 중복 기록
**What goes wrong:** 일별 스냅샷이 같은 날 여러 번 기록됨
**Why it happens:** 스케줄러가 여러 번 실행되거나 프로세스 재시작
**How to avoid:** UNIQUE(strategy_id, date) 제약조건 + INSERT OR REPLACE (SQLite upsert)
**Warning signs:** 동일 날짜 중복 행

### Pitfall 3: Sharpe ratio 계산 시 거래 부족
**What goes wrong:** 거래 5건 미만일 때 Sharpe가 극단값 또는 NaN
**Why it happens:** 수익률 분산이 0이거나 샘플 부족
**How to avoid:** 최소 거래 건수 미충족 시 Sharpe 검증 자체를 skip하고 "거래 부족" 피드백
**Warning signs:** Sharpe = inf, NaN, 또는 비현실적 수치

### Pitfall 4: 승격 기준 오버라이드 우선순위 혼동
**What goes wrong:** 글로벌 config vs 전략별 promotion_gates 중 어느 것이 우선인지 불명확
**Why it happens:** 다단계 config merge 로직 미비
**How to avoid:** 명확한 우선순위: 전략별 promotion_gates > 글로벌 config > 코드 기본값. 3단계 merge
**Warning signs:** 전략별 오버라이드가 무시됨

### Pitfall 5: paper→active 전이 시 race condition
**What goes wrong:** Discord 확인 버튼 클릭 사이에 전략 상태가 변경됨
**Why it happens:** 동시 사용자 또는 자동 체크와 수동 승격이 겹침
**How to avoid:** LifecycleManager.transition()이 이미 atomic(tempfile + rename). 전이 전 상태 재확인
**Warning signs:** 잘못된 상태에서의 전이 시도

### Pitfall 6: 재시작 시 포지션 복원 후 시장 괴리
**What goes wrong:** 복원된 포지션의 진입가가 현재 시장가와 크게 괴리
**Why it happens:** Paper 특성상 장시간 미체결 포지션은 없지만, 재시작 간격이 길 수 있음
**How to avoid:** 복원 시 포지션 목록 로깅 + 경고. 실제 가격 반영은 다음 시그널 처리 시
**Warning signs:** 비현실적 미실현 PnL

## Code Examples

### TradeRepository 활용한 Paper 성과 계산
```python
# Source: engine/core/repository.py TradeRepository.summary() 확장
# 기존 summary()가 이미 broker 필터 지원
def get_paper_summary(session, strategy_name):
    repo = TradeRepository()
    return repo.summary(session, strategy_name=strategy_name, broker="paper")
    # Returns: {total, wins, losses, win_rate, total_profit, avg_profit_pct, ...}
```

### Sharpe Ratio 계산 (일별 PnL 스냅샷 기반)
```python
import numpy as np

def calculate_sharpe(daily_pnls: list[float], risk_free_rate: float = 0.0) -> float | None:
    """일별 PnL로 연환산 Sharpe ratio 계산."""
    if len(daily_pnls) < 2:
        return None
    returns = np.array(daily_pnls)
    excess = returns - risk_free_rate / 252
    std = np.std(excess, ddof=1)
    if std == 0:
        return None
    return float(np.mean(excess) / std * np.sqrt(252))
```

### Max Drawdown 계산
```python
import numpy as np

def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """Equity curve에서 최대 낙폭 계산. 음수 반환 (예: -0.15 = -15%)."""
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))
```

### Config 3단계 Merge
```python
def resolve_promotion_config(
    strategy_def: StrategyDefinition,
    global_config: dict,
) -> PromotionConfig:
    """전략별 > 글로벌 > 코드 기본값 순서로 merge."""
    defaults = {
        "min_days": 7,
        "min_trades": _infer_min_trades(strategy_def.timeframes[0]),
        "min_sharpe": 0.3,
        "min_win_rate": 0.30,
        "max_drawdown": -0.20,
        "min_pnl": 0.0,
    }
    # 글로벌 config 덮어쓰기
    merged = {**defaults, **global_config.get("promotion_gates", {})}
    # 전략별 오버라이드
    if hasattr(strategy_def, "promotion_gates") and strategy_def.promotion_gates:
        merged.update(strategy_def.promotion_gates)
    return PromotionConfig(**merged)

def _infer_min_trades(timeframe: str) -> int:
    """타임프레임 매핑으로 최소 거래 건수 추론."""
    mapping = {"1m": 20, "5m": 20, "15m": 20, "1h": 10, "4h": 10, "1d": 5, "1w": 5}
    return mapping.get(timeframe, 10)
```

### LifecycleManager Gate 삽입 포인트
```python
# engine/strategy/lifecycle_manager.py 수정
def transition(self, strategy_id: str, target: str, reason: str = "",
               gate: PromotionGate | None = None) -> dict:
    # ... 기존 검증 로직 ...

    # paper→active 전이 시 gate 검증
    if current_status == StrategyStatus.paper and target_status == StrategyStatus.active:
        if gate is None:
            raise InvalidTransitionError("paper→active 전이에는 PromotionGate가 필요합니다")
        result = gate.evaluate(strategy_id)
        if not result.passed:
            raise InvalidTransitionError(
                f"승격 기준 미충족: {result.summary}"
            )

    # ... 나머지 전이 로직 ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PaperBroker in-memory | SQLite 영속화 | Phase 3 | 프로세스 재시작 후 상태 보존 |
| 수동 승격 판단 | 정량 기준 자동 검증 | Phase 3 | 감정적 승격 방지 |
| paper→active 무조건 허용 | gate 기반 조건부 허용 | Phase 3 | 미검증 전략 실매매 진입 차단 |

## Open Questions

1. **자동 체크 주기 기본값**
   - What we know: config로 관리, Claude 재량
   - Recommendation: 6시간 (하루 4회) 기본값. 스캘핑 전략은 1시간으로 오버라이드 가능. 과도한 빈도는 불필요 (기준 충족은 점진적)

2. **예상 승격 시점 추정 알고리즘**
   - What we know: 항목별 진행률 표시 + "거래 N건 부족" 등 추정
   - Recommendation: 기간 기준은 남은 일수 직접 계산. 거래 건수는 최근 7일 평균 거래율로 추정. Sharpe/승률/DD는 "현재 추세 유지 시" 조건부 표시 (정확한 예측 불가하므로 현재값만 표시)

3. **PaperBroker 전략 격리**
   - What we know: 여러 전략이 동시에 paper 상태일 수 있음
   - Recommendation: PaperBroker 인스턴스를 전략별로 생성. strategy_id를 key로 잔고/포지션 분리. DB에 strategy_id 칼럼으로 격리

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (기존 사용중) |
| Config file | tests/conftest.py (talib mock + 공통 fixture) |
| Quick run command | `.venv/bin/python -m pytest tests/test_paper_trading.py -x` |
| Full suite command | `.venv/bin/python -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFE-02a | PaperBroker DB 저장/복원 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py -x` | Wave 0 |
| LIFE-02b | PnL 스냅샷 이중 기록 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py::test_pnl_dual_record -x` | Wave 0 |
| LIFE-02c | 재시작 시 잔고/포지션 복원, 미체결 취소 | unit | `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py::test_restart_restore -x` | Wave 0 |
| LIFE-03a | PromotionGate 기준 충족 시 통과 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_all_criteria_pass -x` | Wave 0 |
| LIFE-03b | PromotionGate 기준 미충족 시 차단 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_criteria_fail_blocks -x` | Wave 0 |
| LIFE-03c | paper→active 전이 시 gate 자동 검증 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_lifecycle_gate_integration -x` | Wave 0 |
| LIFE-03d | 전략별 promotion_gates 오버라이드 | unit | `.venv/bin/python -m pytest tests/test_promotion_gate.py::test_config_override -x` | Wave 0 |
| LIFE-03e | Discord /전략승격 확인 버튼 | unit | `.venv/bin/python -m pytest tests/test_paper_discord.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_paper_broker_persistence.py tests/test_promotion_gate.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_paper_broker_persistence.py` — covers LIFE-02 (PaperBroker DB 영속화)
- [ ] `tests/test_promotion_gate.py` — covers LIFE-03 (승격 게이트 검증)
- [ ] `tests/test_paper_discord.py` — covers LIFE-03e (Discord 승격 커맨드)
- [ ] DB migration: `_migrate_paper_phase3()` in database.py

## Sources

### Primary (HIGH confidence)
- engine/execution/paper_broker.py — 현재 PaperBroker in-memory 구현 확인
- engine/execution/broker_base.py — BaseBroker 추상 인터페이스 확인
- engine/strategy/lifecycle_manager.py — ALLOWED_TRANSITIONS, transition() 메서드 확인
- engine/core/repository.py — BacktestRepository, TradeRepository 패턴 확인
- engine/core/db_models.py — TradeRecord(broker="paper") 칼럼 존재 확인
- engine/core/database.py — _migrate_backtests_phase2() idempotent migration 패턴 확인
- engine/schema.py — StrategyDefinition, StrategyStatus 구조 확인
- engine/backtest/report.py — 리포트 생성 함수 재사용 가능 확인
- engine/backtest/history_cli.py — Rich table CLI 패턴 확인
- engine/interfaces/discord/commands/lifecycle.py — TransitionConfirmView 확인/취소 버튼 패턴 확인
- engine/interfaces/discord/commands/backtest_history.py — Discord slash command 패턴 확인
- engine/interfaces/discord/commands/base.py — DiscordCommandPlugin Protocol 확인
- engine/interfaces/discord/context.py — DiscordBotContext 구조 확인
- api/routers/backtests.py — FastAPI router + BacktestResponse 패턴 확인
- api/dependencies.py — get_db() FastAPI dependency 확인

### Secondary (MEDIUM confidence)
- Sharpe ratio 연환산 계수 (sqrt(252)) — 널리 알려진 금융 표준

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 모든 라이브러리가 이미 프로젝트에 존재하고 패턴이 확립됨
- Architecture: HIGH - Phase 1/2에서 확립된 패턴(Repository, Migration, 3채널, 확인 버튼)을 그대로 복제 확장
- Pitfalls: HIGH - SQLite 세션 관리, PnL 중복, Sharpe 계산 edge case는 잘 알려진 문제

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (안정 도메인, 30일)
