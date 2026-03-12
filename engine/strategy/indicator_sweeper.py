"""IndicatorSweeper -- Optuna TPE 기반 자동 전략 탐색기.

indicator 조합과 파라미터 범위를 자동 sweep하고,
walk-forward OOS + multi-symbol 검증을 통과한 후보를
draft 상태로 registry에 등록, Discord로 결과를 통보한다.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import optuna

from engine.backtest.multi_symbol import MultiSymbolValidator
from engine.backtest.runner import BacktestRunner
from engine.backtest.walk_forward import WalkForwardValidator
from engine.notifications.discord_webhook import DiscordWebhookNotifier
from engine.schema import (
    Condition,
    ConditionGroup,
    ConditionOp,
    Direction,
    IndicatorDef,
    MarketType,
    RiskParams,
    StrategyDefinition,
    StrategyStatus,
)
from engine.strategy.lifecycle_manager import LifecycleManager
from engine.strategy.sweep_config import IndicatorSearchSpace, SweepConfig

logger = logging.getLogger(__name__)


class IndicatorSweeper:
    """Optuna TPE sampler로 indicator 파라미터를 자동 탐색한다.

    Parameters
    ----------
    config : SweepConfig
        탐색 공간 및 검증 기준 설정.
    registry_path : str
        strategies/registry.json 경로.
    """

    def __init__(
        self,
        config: SweepConfig,
        registry_path: str = "strategies/registry.json",
    ) -> None:
        self._config = config
        self._registry_path = registry_path

    def run(self) -> list[dict]:
        """Optuna study 생성 + sweep 실행 + 후보 등록 + Discord 통보.

        Returns
        -------
        list[dict]
            등록된 후보 전략 리스트.
        """
        storage = optuna.storages.JournalStorage(
            optuna.storages.JournalFileBackend("sweep_journal.log")
        )
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(),
            storage=storage,
            study_name=f"sweep_{uuid.uuid4().hex[:8]}",
        )

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study.optimize(self._objective, n_trials=self._config.n_trials)

        candidates = self._register_candidates(study)
        self._notify_results(candidates)

        # 최종 상태 기록 (candidates_found 반영)
        completed_trials = [
            t for t in study.trials
            if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None
        ]
        best_sharpe = max((t.value for t in completed_trials), default=0.0)
        self._write_sweep_status(
            completed=self._config.n_trials,
            total=self._config.n_trials,
            best_sharpe=best_sharpe,
            candidates_found=len(candidates),
        )

        logger.info(
            "Sweep 완료: %d trials, %d 후보 등록",
            self._config.n_trials,
            len(candidates),
        )
        return candidates

    def _write_sweep_status(
        self,
        completed: int,
        total: int,
        best_sharpe: float,
        candidates_found: int,
        state_dir: Path | None = None,
    ) -> None:
        """state/sweep_status.json에 진행 상태를 기록한다.

        Parameters
        ----------
        state_dir : Path | None
            상태 파일 디렉토리. None이면 ``state/`` 사용.
        """
        target_dir = state_dir or Path("state")
        target_dir.mkdir(parents=True, exist_ok=True)

        status = {
            "completed": completed,
            "total": total,
            "best_sharpe": best_sharpe,
            "candidates_found": candidates_found,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        status_path = target_dir / "sweep_status.json"
        tmp_path = status_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(status_path))

    def _objective(self, trial: optuna.Trial) -> float:
        """Optuna objective 함수.

        1. trial.suggest_*로 파라미터 샘플링
        2. _build_strategy로 StrategyDefinition 생성
        3. BacktestRunner로 1차 백테스트 (첫 번째 심볼)
        4. WalkForwardValidator로 OOS 검증
        5. MultiSymbolValidator로 멀티심볼 검증
        6. median_sharpe 반환
        """
        strategy = self._build_strategy(trial)

        # 1차 백테스트 (첫 번째 심볼)
        runner = BacktestRunner(auto_save=False)
        result = runner.run(
            strategy,
            symbol=self._config.symbols[0],
            start=self._config.start,
            end=self._config.end,
            timeframe=self._config.timeframe,
            market=self._config.market,
        )

        # Walk-forward OOS 검증
        wf = WalkForwardValidator(gap_threshold=self._config.wf_gap_threshold)
        wf_result = wf.validate(result.equity_curve)
        if not wf_result.overall_passed:
            return float("-inf")

        # Multi-symbol 검증
        ms = MultiSymbolValidator()
        ms_result = ms.validate(
            strategy,
            symbols=self._config.symbols,
            start=self._config.start,
            end=self._config.end,
            timeframe=self._config.timeframe,
        )
        if not ms_result.passed:
            sharpe = float("-inf")
        else:
            sharpe = ms_result.median_sharpe

        # trial 완료 후 sweep 상태 기록
        completed = trial.number + 1  # 0-indexed
        # 현재까지 유효 sharpe 최대값
        best_so_far = max(sharpe, 0.0) if sharpe != float("-inf") else 0.0
        if hasattr(self, "_best_sharpe"):
            self._best_sharpe = max(self._best_sharpe, best_so_far)
        else:
            self._best_sharpe = best_so_far
        self._write_sweep_status(
            completed=completed,
            total=self._config.n_trials,
            best_sharpe=self._best_sharpe,
            candidates_found=0,  # run() 완료 후 최종 갱신
        )

        return sharpe

    def _build_strategy(self, trial: optuna.Trial) -> StrategyDefinition:
        """trial 파라미터로 StrategyDefinition을 생성한다."""
        indicators: list[IndicatorDef] = []

        for space in self._config.indicators:
            params: dict[str, int | float] = {}
            for param_name, (lo, hi, step) in space.param_ranges.items():
                key = f"{space.indicator_name}_{param_name}"
                if isinstance(lo, int) and isinstance(hi, int) and isinstance(step, int):
                    params[param_name] = trial.suggest_int(key, lo, hi, step=step)
                else:
                    params[param_name] = trial.suggest_float(
                        key, float(lo), float(hi), step=float(step)
                    )

            # output alias: 템플릿의 placeholder를 파라미터 값으로 치환
            output_alias = space.output_template
            for k, v in params.items():
                output_alias = output_alias.replace(f"{{{k}}}", str(v))

            indicators.append(
                IndicatorDef(
                    name=space.indicator_name,
                    params=params,
                    output=output_alias,
                )
            )

        # entry/exit 조건 템플릿 → Condition 변환
        entry_conditions = [
            Condition(
                left=c["left"],
                op=ConditionOp(c["op"]),
                right=c["right"],
            )
            for c in self._config.entry_conditions_template
        ]
        exit_conditions = [
            Condition(
                left=c["left"],
                op=ConditionOp(c["op"]),
                right=c["right"],
            )
            for c in self._config.exit_conditions_template
        ]

        # 최소 1개 조건 보장
        if not entry_conditions:
            first_output = indicators[0].output
            alias = first_output if isinstance(first_output, str) else list(first_output.values())[0]
            entry_conditions = [Condition(left=alias, op=ConditionOp.lt, right=30)]
        if not exit_conditions:
            first_output = indicators[0].output
            alias = first_output if isinstance(first_output, str) else list(first_output.values())[0]
            exit_conditions = [Condition(left=alias, op=ConditionOp.gt, right=70)]

        return StrategyDefinition(
            name=f"auto_sweep_{trial.number}",
            version="1.0",
            status=StrategyStatus.draft,
            markets=[MarketType(self._config.market)],
            direction=Direction.long,
            timeframes=[self._config.timeframe],
            indicators=indicators,
            entry=ConditionGroup(logic="and", conditions=entry_conditions),
            exit=ConditionGroup(logic="and", conditions=exit_conditions),
            risk=RiskParams(),
        )

    def _register_candidates(self, study: optuna.Study) -> list[dict]:
        """기준 통과 trial을 draft로 등록한다.

        Returns
        -------
        list[dict]
            등록된 후보 리스트 (id, sharpe 포함).
        """
        lm = LifecycleManager(registry_path=self._registry_path)
        candidates: list[dict] = []

        for trial in study.trials:
            if (
                trial.state == optuna.trial.TrialState.COMPLETE
                and trial.value is not None
                and trial.value >= self._config.sharpe_threshold
            ):
                strategy = self._build_strategy(trial)
                strategy_id = f"auto_{strategy.indicators[0].name.lower()}_{uuid.uuid4().hex[:6]}"

                # definition.json 저장
                strategy_dir = Path("strategies") / strategy_id
                strategy_dir.mkdir(parents=True, exist_ok=True)
                definition = strategy.model_dump(mode="json")
                definition["name"] = strategy_id
                (strategy_dir / "definition.json").write_text(
                    json.dumps(definition, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                # registry에 draft 등록
                entry = {
                    "id": strategy_id,
                    "name": strategy_id,
                    "status": "draft",
                    "sharpe": trial.value,
                    "params": trial.params,
                }
                lm.register(entry)

                candidates.append({
                    "id": strategy_id,
                    "sharpe": trial.value,
                    "params": trial.params,
                })

        return candidates

    def _notify_results(self, candidates: list[dict]) -> None:
        """Discord로 sweep 결과를 통보한다."""
        notifier = DiscordWebhookNotifier()

        if not candidates:
            msg = "[Sweep] 완료 -- 기준 통과 후보 없음"
        else:
            lines = [f"[Sweep] 완료 -- {len(candidates)}개 후보 등록"]
            for c in candidates:
                lines.append(f"  - {c['id']}: Sharpe={c['sharpe']:.4f}")
            msg = "\n".join(lines)

        notifier.send_text(msg)
