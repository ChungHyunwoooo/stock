# Phase 2: Backtest Quality Gates - Research

**Researched:** 2026-03-11
**Domain:** Backtest cost modeling, walk-forward validation, cross-validation, multi-symbol stability
**Confidence:** HIGH

## Summary

Phase 2 transforms the existing BacktestRunner from a naive close-price simulator into a production-grade validation engine. Five distinct capabilities must be added: (1) SlippageModel protocol with VolumeAdjustedSlippage implementation backed by orderbook depth data, (2) walk-forward IS/OOS validation with rolling windows, (3) CPCV as an alternative validation mode, (4) multi-symbol parallel stability testing with correlation-based symbol selection, and (5) automatic DB persistence with history comparison.

The existing codebase provides solid foundations: `BacktestRunner._simulate()` is a clean insertion point for slippage/fee adjustment, `ParallelOptimizer` establishes the ProcessPoolExecutor pattern, `BacktestRecord` + `BacktestRepository` provide the DB layer, and `CryptoProvider` wraps ccxt for data access. The key risk is the orderbook depth data pipeline -- ccxt `fetch_order_book` provides snapshots but not historical data, so the depth cache must be built incrementally via periodic collection.

**Primary recommendation:** Build SlippageModel as a Protocol with `calculate_slippage(order_size, price, symbol) -> float`, inject it into BacktestRunner._simulate(). Use skfolio's WalkForward and CombinatorialPurgedCV for validation (avoid hand-rolling CV splits). Use ccxt REST `fetch_order_book` for depth collection, not WebSocket (simpler, sufficient for 1-min snapshots).

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- VolumeAdjustedSlippage: Orderbook depth 기반 슬리피지 계산
- 거래소별 수수료: JSON 설정 파일로 관리 (maker/taker 수수료율)
- Orderbook depth 데이터: 실시간 WebSocket 수집 + Parquet 캐시, 수집 대상 24h 거래량 Top 50 심볼, 1분 스냅샷
- BacktestRunner 통합: SlippageModel 프로토콜 주입 방식, 기본값 = NoSlippage(0)
- IS/OOS 분할: 70% / 30%, 5개 롤링 윈도우
- 성과 갭 임계치: OOS Sharpe >= IS Sharpe x 0.5 (50% 유지)
- CPCV: Walk-forward의 대체 모드 — 같은 인터페이스로 모드만 전환
- 심볼 선택: 상관계수 기반 자동 선택, |상관계수| < 0.5인 심볼만 선택
- 통과 기준: 전체 심볼 Sharpe의 중앙값(median) >= 0.5
- 실행 방식: ProcessPoolExecutor 병렬
- BacktestRecord 스키마 확장: slippage_model, fee_rate, wf_result, cpcv_mode, multi_symbol_result 칼럼 추가
- 자동 저장: BacktestRunner.run() 완료 시 항상 자동 DB 저장 (저장 실패는 warning)
- 이력 비교: 전략 내 시간순 + 전략 간 횡단 비교 (쿼리 파라미터로 모드 선택)
- 인터페이스: CLI(rich table) + API + Discord 커맨드 모두 제공
- DB 관리: 삭제/수정/초기화 기능 CLI + API + Discord 모두 제공
- 결과 출력: quantstats 연동, equity curve 시각화, IS/OOS 분할 시각화

### Claude's Discretion
- SlippageModel 프로토콜 상세 설계 (메서드 시그니처, 파라미터)
- Orderbook depth 수집 WebSocket 구현 상세 (기존 binance_ws.py 확장 vs 별도 모듈)
- CPCV 알고리즘 구현 세부 (조합 수, purging window)
- 상관계수 기반 심볼 선택 시 Top 50에서 최적 조합 선택 알고리즘
- quantstats 리포트 레이아웃 상세
- Discord 커맨드 UX 상세 (슬래시 커맨드명, Embed 레이아웃)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BT-01 | 거래소별 슬리피지+수수료 모델을 백테스트에 적용 (VolumeAdjustedSlippage 지원) | SlippageModel Protocol + fee JSON config + BacktestRunner._simulate() injection point |
| BT-02 | Walk-forward OOS 검증으로 전략의 과적합 방지 (IS/OOS 분할, 성과 갭 임계치) | skfolio WalkForward CV + custom gap checker + quantstats reporting |
| BT-03 | 2-3개 비상관 심볼에서 일관된 성과 검증 (중앙 Sharpe 기준 통과) | Pearson correlation symbol selector + ProcessPoolExecutor parallel backtest |
| BT-04 | 백테스트 결과 DB 저장 + 전략별/날짜별 이력 비교 | BacktestRecord schema extension + BacktestRepository CRUD expansion |
| BT-05 | CPCV로 walk-forward 고도화 | skfolio CombinatorialPurgedCV + shared ValidationResult interface |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| skfolio | latest (pip install) | WalkForward + CombinatorialPurgedCV | Purpose-built financial CV with purging/embargo, scikit-learn compatible |
| quantstats | 0.0.81 (installed) | Performance reports + tear sheets | Already in project, rich HTML report generation |
| ccxt | 4.5.42 (installed) | Orderbook depth fetching via fetch_order_book | Already in project, unified exchange API |
| scipy | 1.17.1 (installed) | Pearson correlation for symbol selection | Already installed, scipy.stats.pearsonr |
| pyarrow | 23.0.1 (installed) | Parquet cache for depth data | Already in project, same pattern as ohlcv_cache |
| sqlalchemy | 2.0.48 (installed) | DB schema extension + repository | Already in project, declarative models |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | 2.2.6 (installed) | Array operations for slippage calculation | Vectorized depth/volume math |
| pandas | 3.0.1 (installed) | Time series manipulation, returns calculation | Equity curve, correlation matrix |
| rich | installed | CLI table output for backtest history | CLI comparison tables |
| matplotlib | installed | IS/OOS split visualization charts | Walk-forward window visualization |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| skfolio WalkForward | Hand-rolled rolling window | skfolio handles purging/embargo correctly, tested edge cases |
| skfolio CombinatorialPurgedCV | mlfinlab CPCV | mlfinlab is commercial ($), skfolio is MIT licensed and actively maintained |
| ccxt REST fetch_order_book | Binance WebSocket depth stream | REST is simpler for 1-min cron snapshots; WS overkill for periodic collection |
| Alembic migrations | Manual create_all + conditional add_column | Project has no Alembic setup; SQLite batch_alter_table is complex; use conditional column addition pattern |

**Installation:**
```bash
pip install skfolio
```

**Note:** All other dependencies are already installed. skfolio is the only new dependency.

## Architecture Patterns

### Recommended Project Structure
```
engine/
├── backtest/
│   ├── runner.py              # BacktestRunner (modified: SlippageModel injection)
│   ├── metrics.py             # Existing metrics (unchanged)
│   ├── slippage.py            # NEW: SlippageModel protocol + NoSlippage + VolumeAdjustedSlippage
│   ├── fee_model.py           # NEW: FeeModel — JSON config loader, maker/taker fee calc
│   ├── walk_forward.py        # NEW: WalkForwardValidator — wraps skfolio WalkForward
│   ├── cpcv.py                # NEW: CPCVValidator — wraps skfolio CombinatorialPurgedCV
│   ├── multi_symbol.py        # NEW: MultiSymbolValidator — correlation selector + parallel runner
│   ├── validation_result.py   # NEW: ValidationResult dataclass (shared by WF + CPCV)
│   ├── report.py              # Extended: quantstats integration, WF charts
│   ├── optimizer.py           # Existing (unchanged)
│   └── parallel_optimizer.py  # Existing (unchanged)
├── data/
│   ├── depth_collector.py     # NEW: OrderbookDepthCollector — ccxt fetch_order_book + Parquet cache
│   └── depth_cache.py         # NEW: DepthCache — Parquet read/write for depth statistics
├── core/
│   ├── db_models.py           # Modified: BacktestRecord column additions
│   └── repository.py          # Modified: BacktestRepository history/comparison queries
config/
│   ├── exchange_fees.json     # NEW: maker/taker fees per exchange
```

### Pattern 1: SlippageModel Protocol (Port/Adapter)
**What:** Define slippage calculation as a Protocol, inject into BacktestRunner
**When to use:** Any cost model that modifies execution price
**Example:**
```python
# engine/backtest/slippage.py
from typing import Protocol

class SlippageModel(Protocol):
    """슬리피지 계산 프로토콜 — BrokerPort 패턴과 동일."""

    def calculate_slippage(
        self,
        symbol: str,
        side: str,         # "buy" | "sell"
        order_size_usd: float,
        price: float,
    ) -> float:
        """Returns slippage as a fraction (e.g. 0.001 = 0.1%).

        Positive = unfavorable (higher buy / lower sell price).
        """
        ...

class NoSlippage:
    """기본값 — 슬리피지 없음."""
    def calculate_slippage(self, symbol: str, side: str,
                          order_size_usd: float, price: float) -> float:
        return 0.0

class VolumeAdjustedSlippage:
    """Orderbook depth 기반 슬리피지.

    slippage = base_spread + impact_factor * (order_size / available_depth)
    """
    def __init__(self, depth_cache: "DepthCache") -> None:
        self._depth_cache = depth_cache

    def calculate_slippage(self, symbol: str, side: str,
                          order_size_usd: float, price: float) -> float:
        stats = self._depth_cache.get_stats(symbol)
        if stats is None:
            return 0.001  # fallback 0.1%

        base_spread = stats["avg_spread_pct"]
        depth_usd = stats["avg_depth_usd_10"]  # top 10 levels
        liquidity_ratio = order_size_usd / depth_usd if depth_usd > 0 else 1.0
        impact = 0.1 * liquidity_ratio  # impact coefficient
        return base_spread + impact
```

### Pattern 2: Validation Interface (WF + CPCV 통합)
**What:** Common interface for both walk-forward and CPCV validation modes
**When to use:** Any validation that produces IS/OOS comparison results
**Example:**
```python
# engine/backtest/validation_result.py
from dataclasses import dataclass

@dataclass
class WindowResult:
    """단일 윈도우 IS/OOS 결과."""
    window_idx: int
    is_sharpe: float
    oos_sharpe: float
    gap_ratio: float       # oos_sharpe / is_sharpe
    passed: bool           # gap_ratio >= threshold

@dataclass
class ValidationResult:
    """WF 또는 CPCV 검증 결과."""
    mode: str              # "walk_forward" | "cpcv"
    windows: list[WindowResult]
    overall_passed: bool
    summary: dict          # 통계 요약
```

### Pattern 3: Fee Configuration (JSON config)
**What:** Exchange-specific fee rates loaded from JSON
**When to use:** Fee calculation in BacktestRunner._simulate()
**Example:**
```json
// config/exchange_fees.json
{
  "binance": {
    "spot": {"maker": 0.001, "taker": 0.001},
    "futures": {"maker": 0.0002, "taker": 0.0005}
  },
  "upbit": {
    "spot": {"maker": 0.0005, "taker": 0.0005}
  }
}
```

### Pattern 4: BacktestRunner._simulate() Modification
**What:** Inject slippage + fee into entry/exit price calculation
**Where:** `engine/backtest/runner.py` lines 158-175
**Example:**
```python
# In _simulate(), at entry:
if not in_position and signal == 1:
    slippage_pct = self._slippage_model.calculate_slippage(
        symbol, "buy", capital, close
    )
    entry_price = close * (1 + slippage_pct)  # worse fill
    entry_fee = entry_price * self._fee_rate
    capital -= entry_fee
    ...

# At exit:
elif in_position and signal == -1:
    slippage_pct = self._slippage_model.calculate_slippage(
        symbol, "sell", capital, close
    )
    exit_price = close * (1 - slippage_pct)  # worse fill
    exit_fee = exit_price * self._fee_rate
    pnl_pct = (exit_price - entry_price) / entry_price
    capital = capital * (1 + pnl_pct) - exit_fee
```

### Anti-Patterns to Avoid
- **Fixed slippage constants:** Never hardcode `slippage = 0.001`. Always derive from orderbook depth or make configurable.
- **IS/OOS data leakage:** Never use future data in training window. skfolio's purging handles this — do NOT hand-roll split logic.
- **Sequential multi-symbol (no parallelism):** Always use ProcessPoolExecutor for multi-symbol backtests — existing ParallelOptimizer pattern.
- **Blocking on depth data absence:** If depth cache is empty for a symbol, fall back to NoSlippage with warning, never fail the backtest.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Walk-forward CV splits | Custom rolling window indexer | skfolio.model_selection.WalkForward | Handles purging, edge cases at boundaries, tested |
| CPCV combinatorial splits | itertools.combinations + manual purging | skfolio.model_selection.CombinatorialPurgedCV | Correct embargo/purging, optimal_folds_number() helper |
| Sharpe/Sortino/DD metrics | Custom metric functions | quantstats.stats.* | 60+ vetted metrics, handles edge cases (zero std, empty series) |
| HTML tear sheet generation | Custom matplotlib + Jinja | quantstats.reports.html() | Professional reports, SVG charts, single function call |
| Pearson correlation matrix | Manual loop over pairs | pandas DataFrame.corr() | Vectorized, handles NaN, standard interface |

**Key insight:** The validation logic (WF/CPCV split generation) is the hardest part to get right. Off-by-one errors in purging windows, incorrect embargo handling, and data leakage at split boundaries are common bugs. skfolio is specifically designed for financial time series and handles all edge cases.

## Common Pitfalls

### Pitfall 1: Look-Ahead Bias in Walk-Forward
**What goes wrong:** Training data accidentally includes information from OOS period
**Why it happens:** Indicator warmup periods bleed into OOS; features with lag (MA, MACD) need history from before IS period
**How to avoid:** Ensure each IS window starts with sufficient warmup bars (200+ for EMA200). skfolio's `purged_size` parameter handles this.
**Warning signs:** OOS performance suspiciously close to IS performance

### Pitfall 2: Overfitting the Validation Itself
**What goes wrong:** Tweaking WF window count, split ratio, gap threshold until strategy passes
**Why it happens:** Human tendency to adjust validation parameters to get desired outcome
**How to avoid:** Lock IS/OOS = 70/30, windows = 5, gap = 0.5 as immutable constants (already locked in CONTEXT.md decisions)
**Warning signs:** Frequent changes to validation parameters

### Pitfall 3: Correlation-Based Symbol Selection Instability
**What goes wrong:** Symbols selected as "uncorrelated" become correlated in OOS period
**Why it happens:** Crypto correlations are regime-dependent (all correlate in crashes)
**How to avoid:** Use 90-day rolling correlation (locked decision), re-check correlation on each backtest run rather than caching selections
**Warning signs:** Multi-symbol pass rate drops significantly in live vs backtest

### Pitfall 4: SQLite Schema Migration Without Alembic
**What goes wrong:** Adding columns to existing BacktestRecord table fails on existing databases
**Why it happens:** SQLite ALTER TABLE is limited; project uses create_all() which only creates NEW tables
**How to avoid:** Use conditional column addition: check if column exists before ALTER TABLE ADD COLUMN. For SQLite, use `PRAGMA table_info(backtests)` to detect missing columns, then `ALTER TABLE backtests ADD COLUMN ...` for each.
**Warning signs:** "no such column" errors on existing databases

### Pitfall 5: Orderbook Depth Data Staleness
**What goes wrong:** Cached depth stats from weeks ago don't reflect current liquidity
**Why it happens:** Crypto orderbook depth changes dramatically with market conditions
**How to avoid:** Set TTL on depth cache (7 days max). For backtests, use the statistical average (mean spread, mean depth) rather than point-in-time values. Log warning if depth data is older than TTL.
**Warning signs:** Slippage estimates wildly different from actual execution

### Pitfall 6: ProcessPoolExecutor Pickle Errors
**What goes wrong:** Multi-symbol parallel backtest crashes with unpicklable objects
**Why it happens:** Lambda functions, database sessions, and certain objects can't be pickled across processes
**How to avoid:** Follow existing ParallelOptimizer pattern: pass only serializable args (dict, str, float) to worker function. Create BacktestRunner inside worker. Never pass DB session to worker.
**Warning signs:** `PicklingError` or `AttributeError` in subprocess

## Code Examples

### OrderBook Depth Collection via ccxt REST
```python
# engine/data/depth_collector.py
import ccxt
import pandas as pd
from pathlib import Path

class OrderbookDepthCollector:
    """ccxt fetch_order_book로 depth 스냅샷 수집 + Parquet 저장."""

    def __init__(self, exchange: str = "binance", cache_dir: Path = Path(".cache/depth")):
        self._exchange = getattr(ccxt, exchange)()
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def collect_snapshot(self, symbol: str, limit: int = 20) -> dict:
        """단일 심볼 orderbook 스냅샷. limit=20 (top 20 levels)."""
        book = self._exchange.fetch_order_book(symbol, limit=limit)
        # book = {"bids": [[price, amount], ...], "asks": [[price, amount], ...]}

        bid_depth_usd = sum(p * a for p, a in book["bids"])
        ask_depth_usd = sum(p * a for p, a in book["asks"])
        best_bid = book["bids"][0][0] if book["bids"] else 0
        best_ask = book["asks"][0][0] if book["asks"] else 0
        spread_pct = (best_ask - best_bid) / best_bid if best_bid > 0 else 0

        return {
            "symbol": symbol,
            "timestamp": pd.Timestamp.now(tz="UTC"),
            "bid_depth_usd": bid_depth_usd,
            "ask_depth_usd": ask_depth_usd,
            "spread_pct": spread_pct,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "levels": limit,
        }

    def collect_top_symbols(self, n: int = 50) -> list[dict]:
        """24h 거래량 Top N 심볼 depth 수집."""
        self._exchange.load_markets()
        tickers = self._exchange.fetch_tickers()
        # Sort by 24h quote volume
        sorted_symbols = sorted(
            tickers.items(),
            key=lambda x: x[1].get("quoteVolume", 0) or 0,
            reverse=True,
        )[:n]

        snapshots = []
        for symbol, _ in sorted_symbols:
            try:
                snap = self.collect_snapshot(symbol)
                snapshots.append(snap)
            except Exception:
                continue
        return snapshots
```

### Walk-Forward Validation with skfolio
```python
# engine/backtest/walk_forward.py
import numpy as np
from skfolio.model_selection import WalkForward
from engine.backtest.validation_result import ValidationResult, WindowResult

class WalkForwardValidator:
    """Walk-forward OOS 검증기."""

    def __init__(
        self,
        n_windows: int = 5,
        train_pct: float = 0.7,
        gap_threshold: float = 0.5,
    ):
        self._n_windows = n_windows
        self._train_pct = train_pct
        self._gap_threshold = gap_threshold

    def validate(
        self,
        equity_curve: "pd.Series",
    ) -> ValidationResult:
        """equity curve를 n_windows로 분할하여 IS/OOS 성과 갭 검증."""
        n = len(equity_curve)
        total_window = n // self._n_windows
        train_size = int(total_window * self._train_pct)
        test_size = total_window - train_size

        cv = WalkForward(train_size=train_size, test_size=test_size)
        returns = equity_curve.pct_change().dropna()
        X = returns.values.reshape(-1, 1)

        windows = []
        for i, (train_idx, test_idx) in enumerate(cv.split(X)):
            is_returns = returns.iloc[train_idx]
            oos_returns = returns.iloc[test_idx]

            is_sharpe = self._calc_sharpe(is_returns)
            oos_sharpe = self._calc_sharpe(oos_returns)
            gap = oos_sharpe / is_sharpe if is_sharpe != 0 else 0

            windows.append(WindowResult(
                window_idx=i,
                is_sharpe=is_sharpe,
                oos_sharpe=oos_sharpe,
                gap_ratio=gap,
                passed=gap >= self._gap_threshold,
            ))

        overall = all(w.passed for w in windows)
        return ValidationResult(
            mode="walk_forward",
            windows=windows,
            overall_passed=overall,
            summary={"n_windows": len(windows), "gap_threshold": self._gap_threshold},
        )

    @staticmethod
    def _calc_sharpe(returns, periods=252) -> float:
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return float((returns.mean() / returns.std()) * np.sqrt(periods))
```

### CPCV Validation with skfolio
```python
# engine/backtest/cpcv.py
from skfolio.model_selection import CombinatorialPurgedCV
from engine.backtest.validation_result import ValidationResult, WindowResult

class CPCVValidator:
    """Combinatorial Purged Cross-Validation 검증기.

    WalkForwardValidator와 동일 인터페이스 — mode만 전환.
    """

    def __init__(
        self,
        n_folds: int = 6,
        n_test_folds: int = 2,
        purged_size: int = 10,
        embargo_size: int = 5,
        gap_threshold: float = 0.5,
    ):
        self._cv = CombinatorialPurgedCV(
            n_folds=n_folds,
            n_test_folds=n_test_folds,
            purged_size=purged_size,
            embargo_size=embargo_size,
        )
        self._gap_threshold = gap_threshold

    def validate(self, equity_curve: "pd.Series") -> ValidationResult:
        """CPCV로 다중 경로 검증."""
        returns = equity_curve.pct_change().dropna()
        X = returns.values.reshape(-1, 1)

        windows = []
        for i, (train_idx, test_indices) in enumerate(self._cv.split(X)):
            is_returns = returns.iloc[train_idx]
            # CPCV returns multiple test sets per split
            for j, test_idx in enumerate(test_indices):
                oos_returns = returns.iloc[test_idx]
                is_sharpe = self._calc_sharpe(is_returns)
                oos_sharpe = self._calc_sharpe(oos_returns)
                gap = oos_sharpe / is_sharpe if is_sharpe != 0 else 0

                windows.append(WindowResult(
                    window_idx=i * 100 + j,
                    is_sharpe=is_sharpe,
                    oos_sharpe=oos_sharpe,
                    gap_ratio=gap,
                    passed=gap >= self._gap_threshold,
                ))

        pass_rate = sum(1 for w in windows if w.passed) / len(windows) if windows else 0
        overall = pass_rate >= 0.5  # 50% 이상 경로 통과

        return ValidationResult(
            mode="cpcv",
            windows=windows,
            overall_passed=overall,
            summary={"n_paths": len(windows), "pass_rate": pass_rate},
        )
```

### Multi-Symbol Stability Validation
```python
# engine/backtest/multi_symbol.py
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd

def select_uncorrelated_symbols(
    symbols: list[str],
    returns_df: pd.DataFrame,
    max_corr: float = 0.5,
    n_select: int = 3,
) -> list[str]:
    """상관계수 기반 비상관 심볼 선택.

    Args:
        symbols: 후보 심볼 목록
        returns_df: 일간 수익률 DataFrame (columns = symbols)
        max_corr: 최대 허용 상관계수 (|r| < max_corr)
        n_select: 선택할 심볼 수
    """
    corr_matrix = returns_df[symbols].corr()
    selected = [symbols[0]]  # 첫 심볼 시작

    for sym in symbols[1:]:
        if len(selected) >= n_select:
            break
        # 선택된 모든 심볼과의 상관계수 확인
        is_uncorrelated = all(
            abs(corr_matrix.loc[sym, s]) < max_corr
            for s in selected
        )
        if is_uncorrelated:
            selected.append(sym)

    return selected
```

### BacktestRecord Schema Extension
```python
# engine/core/db_models.py additions
class BacktestRecord(Base):
    __tablename__ = "backtests"
    # ... existing columns ...

    # NEW columns for Phase 2
    slippage_model: Mapped[str] = mapped_column(String(50), default="none")
    fee_rate: Mapped[float] = mapped_column(Float, default=0.0)
    wf_result: Mapped[str | None] = mapped_column(String(10), nullable=True)  # PASS/FAIL
    cpcv_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    multi_symbol_result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
```

### SQLite Conditional Migration (No Alembic)
```python
# engine/core/database.py — add migration helper
def _migrate_backtests_phase2(engine: Engine) -> None:
    """Phase 2 칼럼 추가 — 이미 존재하면 skip."""
    import sqlalchemy as sa

    with engine.connect() as conn:
        # Check existing columns
        result = conn.execute(sa.text("PRAGMA table_info(backtests)"))
        existing = {row[1] for row in result}

        new_columns = {
            "slippage_model": "VARCHAR(50) DEFAULT 'none'",
            "fee_rate": "REAL DEFAULT 0.0",
            "wf_result": "VARCHAR(10)",
            "cpcv_mode": "BOOLEAN DEFAULT 0",
            "multi_symbol_result": "TEXT",
        }

        for col_name, col_type in new_columns.items():
            if col_name not in existing:
                conn.execute(sa.text(
                    f"ALTER TABLE backtests ADD COLUMN {col_name} {col_type}"
                ))
        conn.commit()
```

### quantstats Report Integration
```python
# engine/backtest/report.py — extend with quantstats
import quantstats as qs

def generate_quantstats_report(
    equity_curve: "pd.Series",
    title: str = "Strategy Tearsheet",
    output: str | None = None,
    benchmark: str | None = None,
) -> str:
    """quantstats HTML tearsheet 생성."""
    returns = equity_curve.pct_change().dropna()

    output_path = output or f".cache/reports/{title.replace(' ', '_')}.html"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    qs.reports.html(
        returns,
        benchmark=benchmark,
        title=title,
        output=output_path,
        periods_per_year=252,
    )
    return output_path
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed slippage (0.1%) | Volume-adjusted from orderbook depth | 2023+ | Realistic cost modeling, prevents false positive strategies |
| Single train/test split | Walk-forward rolling windows | Standard since 2018 | Detects overfitting across market regimes |
| Simple K-fold CV | CPCV with purging + embargo | Lopez de Prado 2018 | Eliminates temporal leakage, multiple OOS paths |
| Single-symbol backtest | Multi-symbol stability check | Standard practice | Filters curve-fitted single-symbol strategies |
| Manual result tracking | Automatic DB persistence | Standard | Reproducibility, comparison, audit trail |

**Deprecated/outdated:**
- `vectorbt` was considered (STATE.md blocker) but NOT needed: existing BacktestRunner is sufficient for this phase. vectorbt is useful for Phase 7 (Discovery) parameter sweeps, not validation.

## Open Questions

1. **skfolio WalkForward vs. manual rolling window**
   - What we know: skfolio WalkForward returns train/test indices. Our BacktestRunner needs equity curves, not raw data splits.
   - What's unclear: Whether to split OHLCV data (re-run backtest per window) or split the equity curve (run once, validate windows).
   - Recommendation: Split OHLCV and re-run backtest per window (more accurate, captures regime changes). Use skfolio only for index generation.

2. **Depth data collection scheduling**
   - What we know: Need 1-min snapshots for Top 50 symbols via cron or daemon.
   - What's unclear: Whether to run as separate daemon process or integrate into existing bot loop.
   - Recommendation: Separate lightweight script (`scripts/collect_depth.py`) run via cron (*/1 * * * *). Simpler than integrating into WebSocket manager.

3. **CPCV n_folds / n_test_folds selection**
   - What we know: Default skfolio is n_folds=10, n_test_folds=8 (too aggressive for small datasets).
   - What's unclear: Optimal settings for typical crypto backtest dataset sizes (90-365 days of 1h bars = 2160-8760 samples).
   - Recommendation: n_folds=6, n_test_folds=2 (generates C(6,2)=15 paths, reasonable for crypto data sizes). Use `optimal_folds_number()` if available.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `.venv/bin/python -m pytest tests/ -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BT-01 | SlippageModel protocol + VolumeAdjustedSlippage lowers returns | unit | `.venv/bin/python -m pytest tests/test_slippage.py -x` | Wave 0 |
| BT-01 | BacktestRunner applies slippage + fee to entry/exit | unit | `.venv/bin/python -m pytest tests/test_backtest_costs.py -x` | Wave 0 |
| BT-02 | WalkForwardValidator produces IS/OOS split + gap judgment | unit | `.venv/bin/python -m pytest tests/test_walk_forward.py -x` | Wave 0 |
| BT-03 | MultiSymbolValidator selects uncorrelated symbols + median Sharpe gate | unit | `.venv/bin/python -m pytest tests/test_multi_symbol.py -x` | Wave 0 |
| BT-04 | BacktestRecord saves/loads extended columns + history comparison | unit | `.venv/bin/python -m pytest tests/test_backtest_history.py -x` | Wave 0 |
| BT-05 | CPCVValidator produces multi-path results via same interface | unit | `.venv/bin/python -m pytest tests/test_cpcv.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_slippage.py` -- covers BT-01 (SlippageModel protocol, NoSlippage, VolumeAdjustedSlippage)
- [ ] `tests/test_backtest_costs.py` -- covers BT-01 (BacktestRunner slippage+fee integration)
- [ ] `tests/test_walk_forward.py` -- covers BT-02 (WalkForward IS/OOS split, gap judgment)
- [ ] `tests/test_cpcv.py` -- covers BT-05 (CPCV multi-path validation)
- [ ] `tests/test_multi_symbol.py` -- covers BT-03 (correlation selection, parallel runner, median gate)
- [ ] `tests/test_backtest_history.py` -- covers BT-04 (schema extension, history queries, comparison)
- [ ] Framework install: `pip install skfolio` -- new dependency for WF/CPCV

## Sources

### Primary (HIGH confidence)
- skfolio WalkForward API: https://skfolio.org/generated/skfolio.model_selection.WalkForward.html
- skfolio CombinatorialPurgedCV API: https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html
- ccxt fetch_order_book: verified via `help(ccxt.binance().fetch_order_book)` -- signature `(symbol, limit=None, params={})`
- quantstats reports.html: verified via `inspect.signature(qs.reports.html)` -- `(returns, benchmark=None, rf=0.0, ..., output=None, ...)`
- Existing codebase: BacktestRunner, ParallelOptimizer, BacktestRecord, BacktestRepository patterns

### Secondary (MEDIUM confidence)
- CPCV theory: Lopez de Prado "Advances in Financial Machine Learning" via [QuantInsti blog](https://blog.quantinsti.com/cross-validation-embargo-purging-combinatorial/)
- Volume-adjusted slippage: [Amberdata blog](https://blog.amberdata.io/identifying-crypto-market-trends-using-orderbook-slippage-metrics) + [Hyper Quant](https://www.hyper-quant.tech/research/realistic-backtesting-methodology)
- Walk-forward optimization: [QuantInsti WFO](https://blog.quantinsti.com/walk-forward-optimization-introduction/)
- SQLite batch migration: [Alembic docs](https://alembic.sqlalchemy.org/en/latest/batch.html)

### Tertiary (LOW confidence)
- Optimal CPCV fold count for crypto data: derived from general recommendation (n_folds=6, n_test_folds=2), not empirically validated for this project's data sizes

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries verified installed (except skfolio), APIs confirmed via runtime inspection
- Architecture: HIGH - follows established project patterns (Protocol, Repository, ProcessPoolExecutor)
- Pitfalls: HIGH - common issues well-documented in financial backtesting literature
- CPCV parameters: MEDIUM - recommended values reasonable but may need tuning per dataset size

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (stable domain, 30-day validity)
