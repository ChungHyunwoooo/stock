"""IndicatorSweeper + SweepConfig 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_sweep_config_dict() -> dict:
    """최소 SweepConfig dict — RSI 1개 indicator, n_trials=3."""
    return {
        "indicators": [
            {
                "indicator_name": "RSI",
                "param_ranges": {"timeperiod": (10, 20, 2)},
                "output_template": "rsi_{timeperiod}",
            }
        ],
        "n_trials": 3,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "timeframe": "1h",
        "start": "2025-01-01",
        "end": "2025-06-30",
        "market": "crypto_futures",
        "sharpe_threshold": 0.5,
        "wf_gap_threshold": 0.5,
        "entry_conditions_template": [
            {"left": "rsi", "op": "lt", "right": 30}
        ],
        "exit_conditions_template": [
            {"left": "rsi", "op": "gt", "right": 70}
        ],
    }


def _mock_equity_curve(n: int = 100) -> pd.Series:
    """단조 증가 equity curve (Sharpe > 0)."""
    return pd.Series(
        [10000 + i * 10 for i in range(n)],
        index=pd.date_range("2025-01-01", periods=n, freq="h"),
    )


# ---------------------------------------------------------------------------
# Test 1: SweepConfig.from_dict
# ---------------------------------------------------------------------------

class TestSweepConfig:
    def test_from_dict_parses_indicator_search_space(self):
        from engine.strategy.sweep_config import SweepConfig

        d = _make_sweep_config_dict()
        config = SweepConfig.from_dict(d)

        assert len(config.indicators) == 1
        assert config.indicators[0].indicator_name == "RSI"
        assert config.n_trials == 3
        assert config.symbols == ["BTCUSDT", "ETHUSDT"]
        assert config.sharpe_threshold == 0.5


# ---------------------------------------------------------------------------
# Test 2: _build_strategy
# ---------------------------------------------------------------------------

class TestBuildStrategy:
    def test_build_strategy_creates_strategy_definition(self):
        import optuna

        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        study = optuna.create_study(direction="maximize")
        trial = study.ask()

        strategy = sweeper._build_strategy(trial)

        from engine.schema import StrategyDefinition
        assert isinstance(strategy, StrategyDefinition)
        assert len(strategy.indicators) >= 1
        assert strategy.status.value == "draft"


# ---------------------------------------------------------------------------
# Test 3: _objective success path (mock)
# ---------------------------------------------------------------------------

class TestObjectiveSuccess:
    @patch("engine.strategy.indicator_sweeper.MultiSymbolValidator")
    @patch("engine.strategy.indicator_sweeper.WalkForwardValidator")
    @patch("engine.strategy.indicator_sweeper.BacktestRunner")
    def test_objective_returns_median_sharpe_on_success(
        self, MockRunner, MockWF, MockMS
    ):
        import optuna

        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        # Mock BacktestRunner
        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.5
        mock_result.equity_curve = _mock_equity_curve()
        MockRunner.return_value.run.return_value = mock_result

        # Mock WalkForwardValidator — passed
        mock_wf_result = MagicMock()
        mock_wf_result.overall_passed = True
        MockWF.return_value.validate.return_value = mock_wf_result

        # Mock MultiSymbolValidator — passed with median_sharpe=1.2
        mock_ms_result = MagicMock()
        mock_ms_result.passed = True
        mock_ms_result.median_sharpe = 1.2
        MockMS.return_value.validate.return_value = mock_ms_result

        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        score = sweeper._objective(trial)

        assert score == 1.2
        MockRunner.return_value.run.assert_called_once()
        MockWF.return_value.validate.assert_called_once()
        MockMS.return_value.validate.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: _objective failure paths (mock)
# ---------------------------------------------------------------------------

class TestObjectiveFailure:
    @patch("engine.strategy.indicator_sweeper.MultiSymbolValidator")
    @patch("engine.strategy.indicator_sweeper.WalkForwardValidator")
    @patch("engine.strategy.indicator_sweeper.BacktestRunner")
    def test_objective_returns_neg_inf_on_wf_failure(
        self, MockRunner, MockWF, MockMS
    ):
        import optuna

        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.0
        mock_result.equity_curve = _mock_equity_curve()
        MockRunner.return_value.run.return_value = mock_result

        # WalkForward fails
        mock_wf_result = MagicMock()
        mock_wf_result.overall_passed = False
        MockWF.return_value.validate.return_value = mock_wf_result

        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        score = sweeper._objective(trial)

        assert score == float("-inf")
        MockMS.return_value.validate.assert_not_called()

    @patch("engine.strategy.indicator_sweeper.MultiSymbolValidator")
    @patch("engine.strategy.indicator_sweeper.WalkForwardValidator")
    @patch("engine.strategy.indicator_sweeper.BacktestRunner")
    def test_objective_returns_neg_inf_on_ms_failure(
        self, MockRunner, MockWF, MockMS
    ):
        import optuna

        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.0
        mock_result.equity_curve = _mock_equity_curve()
        MockRunner.return_value.run.return_value = mock_result

        mock_wf_result = MagicMock()
        mock_wf_result.overall_passed = True
        MockWF.return_value.validate.return_value = mock_wf_result

        # MultiSymbol fails
        mock_ms_result = MagicMock()
        mock_ms_result.passed = False
        MockMS.return_value.validate.return_value = mock_ms_result

        study = optuna.create_study(direction="maximize")
        trial = study.ask()
        score = sweeper._objective(trial)

        assert score == float("-inf")


# ---------------------------------------------------------------------------
# Test 5: _register_candidates (mock LifecycleManager)
# ---------------------------------------------------------------------------

class TestRegisterCandidates:
    @patch("engine.strategy.indicator_sweeper.LifecycleManager")
    def test_register_candidates_calls_lifecycle_register(self, MockLM):
        import optuna

        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        MockLM.return_value.register.side_effect = lambda entry: entry

        # Create a study with completed trials above threshold
        study = optuna.create_study(direction="maximize")

        # Add a completed trial with value above threshold
        study.add_trial(
            optuna.trial.create_trial(
                params={"RSI_timeperiod": 14},
                distributions={"RSI_timeperiod": optuna.distributions.IntDistribution(10, 20, step=2)},
                values=[0.8],
            )
        )

        candidates = sweeper._register_candidates(study)

        assert len(candidates) >= 1
        MockLM.return_value.register.assert_called()


# ---------------------------------------------------------------------------
# Test 6: _notify_results (mock DiscordWebhookNotifier)
# ---------------------------------------------------------------------------

class TestNotifyResults:
    @patch("engine.strategy.indicator_sweeper.DiscordWebhookNotifier")
    def test_notify_results_sends_discord_message(self, MockNotifier):
        from engine.strategy.indicator_sweeper import IndicatorSweeper
        from engine.strategy.sweep_config import SweepConfig

        config = SweepConfig.from_dict(_make_sweep_config_dict())
        sweeper = IndicatorSweeper(config)

        MockNotifier.return_value.send_text.return_value = True

        candidates = [
            {"id": "auto_rsi_001", "sharpe": 0.8},
            {"id": "auto_rsi_002", "sharpe": 1.2},
        ]
        sweeper._notify_results(candidates)

        MockNotifier.return_value.send_text.assert_called_once()
        call_msg = MockNotifier.return_value.send_text.call_args[0][0]
        assert "auto_rsi_001" in call_msg
        assert "0.8" in call_msg
