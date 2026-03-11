"""SweepConfig -- Optuna TPE sweep 탐색 공간 정의."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IndicatorSearchSpace:
    """단일 indicator의 파라미터 탐색 범위.

    Attributes:
        indicator_name: TA-Lib indicator 이름 (e.g. "RSI", "MACD")
        param_ranges: 파라미터별 (min, max, step) 범위
        output_template: output alias 템플릿 (e.g. "rsi_{timeperiod}")
    """

    indicator_name: str
    param_ranges: dict[str, tuple[int | float, int | float, int | float]]
    output_template: str


@dataclass
class SweepConfig:
    """Optuna sweep 전체 설정.

    Attributes:
        indicators: 탐색할 indicator 목록과 파라미터 범위
        n_trials: Optuna trial 수
        symbols: 백테스트 대상 심볼
        timeframe: 바 사이즈
        start: 백테스트 시작일
        end: 백테스트 종료일
        market: 시장 타입
        sharpe_threshold: 후보 등록 최소 Sharpe
        wf_gap_threshold: walk-forward gap threshold
        entry_conditions_template: entry 조건 템플릿
        exit_conditions_template: exit 조건 템플릿
    """

    indicators: list[IndicatorSearchSpace]
    n_trials: int = 100
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "1h"
    start: str = ""
    end: str = ""
    market: str = "crypto_futures"
    sharpe_threshold: float = 0.5
    wf_gap_threshold: float = 0.5
    entry_conditions_template: list[dict] = field(default_factory=list)
    exit_conditions_template: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> SweepConfig:
        """dict에서 SweepConfig를 생성한다."""
        indicators = [
            IndicatorSearchSpace(
                indicator_name=ind["indicator_name"],
                param_ranges={
                    k: tuple(v) for k, v in ind["param_ranges"].items()
                },
                output_template=ind["output_template"],
            )
            for ind in d.get("indicators", [])
        ]
        return cls(
            indicators=indicators,
            n_trials=d.get("n_trials", 100),
            symbols=d.get("symbols", []),
            timeframe=d.get("timeframe", "1h"),
            start=d.get("start", ""),
            end=d.get("end", ""),
            market=d.get("market", "crypto_futures"),
            sharpe_threshold=d.get("sharpe_threshold", 0.5),
            wf_gap_threshold=d.get("wf_gap_threshold", 0.5),
            entry_conditions_template=d.get("entry_conditions_template", []),
            exit_conditions_template=d.get("exit_conditions_template", []),
        )
