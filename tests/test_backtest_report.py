"""Tests for backtest report generation -- quantstats, IS/OOS chart, full report."""

from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest

from engine.backtest.report import (
    generate_full_report,
    generate_quantstats_report,
    generate_report,
    generate_summary,
    generate_validation_chart,
)
from engine.backtest.runner import BacktestResult, TradeRecord
from engine.backtest.validation_result import ValidationResult, WindowResult


def _make_equity_curve(n: int = 100, start_val: float = 10_000.0) -> pd.Series:
    """Create a synthetic monotonically increasing equity curve."""
    import numpy as np

    rng = np.random.default_rng(42)
    returns = 1 + rng.normal(0.001, 0.01, n)
    values = start_val * returns.cumprod()
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.Series(values, index=dates, dtype=float)


def _make_backtest_result(equity_curve: pd.Series | None = None) -> BacktestResult:
    """Create a synthetic BacktestResult for testing."""
    ec = equity_curve if equity_curve is not None else _make_equity_curve()
    return BacktestResult(
        symbol="BTC/USDT",
        timeframe="1d",
        start_date="2025-01-01",
        end_date="2025-04-10",
        initial_capital=10_000.0,
        final_capital=float(ec.iloc[-1]),
        total_return=float(ec.iloc[-1] / ec.iloc[0] - 1),
        sharpe_ratio=1.5,
        max_drawdown=-0.05,
        trades=[
            TradeRecord("2025-01-05", "2025-01-10", 100.0, 110.0, 0.10),
            TradeRecord("2025-02-01", "2025-02-15", 105.0, 115.0, 0.095),
        ],
        equity_curve=ec,
    )


def _make_validation_result(n_windows: int = 5, all_pass: bool = True) -> ValidationResult:
    """Create a synthetic ValidationResult."""
    windows = []
    for i in range(n_windows):
        is_sharpe = 1.5 + i * 0.1
        oos_sharpe = is_sharpe * (0.8 if all_pass else 0.3)
        gap = oos_sharpe / is_sharpe if is_sharpe != 0 else 0
        windows.append(
            WindowResult(
                window_idx=i,
                is_sharpe=is_sharpe,
                oos_sharpe=oos_sharpe,
                gap_ratio=gap,
                passed=gap >= 0.5,
            )
        )
    return ValidationResult(
        mode="walk_forward",
        windows=windows,
        overall_passed=all_pass,
        summary={"n_windows": n_windows, "gap_threshold": 0.5},
    )


class TestExistingFunctionsBackwardCompat:
    """Existing generate_summary and generate_report must remain working."""

    def test_generate_summary_returns_dict(self) -> None:
        result = _make_backtest_result()
        summary = generate_summary(result)
        assert isinstance(summary, dict)
        assert "total_return" in summary
        assert "sharpe_ratio" in summary

    def test_generate_report_returns_html_path(self) -> None:
        result = _make_backtest_result()
        path = generate_report(result)
        assert os.path.isfile(path)
        assert path.endswith(".html")
        with open(path) as f:
            content = f.read()
        assert "BTC/USDT" in content
        os.unlink(path)


class TestGenerateQuantstatsReport:
    """generate_quantstats_report produces HTML tearsheet."""

    def test_creates_html_file(self) -> None:
        ec = _make_equity_curve(200)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "tearsheet.html")
            path = generate_quantstats_report(ec, title="Test Strategy", output=out)
            assert os.path.isfile(path)
            assert os.path.getsize(path) > 0

    def test_default_output_creates_directory(self) -> None:
        ec = _make_equity_curve(200)
        path = generate_quantstats_report(ec, title="Auto Path Test")
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0
        os.unlink(path)

    def test_empty_equity_curve_returns_path(self) -> None:
        ec = pd.Series([], dtype=float)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "empty.html")
            path = generate_quantstats_report(ec, output=out)
            assert os.path.isfile(path)


class TestGenerateValidationChart:
    """generate_validation_chart produces IS/OOS bar chart PNG."""

    def test_creates_png_file(self) -> None:
        vr = _make_validation_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "validation.png")
            path = generate_validation_chart(vr, output=out)
            assert os.path.isfile(path)
            assert os.path.getsize(path) > 0

    def test_default_output_creates_directory(self) -> None:
        vr = _make_validation_result()
        path = generate_validation_chart(vr)
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0
        os.unlink(path)

    def test_cpcv_mode_in_output(self) -> None:
        vr = _make_validation_result()
        vr = ValidationResult(
            mode="cpcv",
            windows=vr.windows,
            overall_passed=vr.overall_passed,
            summary=vr.summary,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "cpcv.png")
            path = generate_validation_chart(vr, output=out)
            assert os.path.isfile(path)

    def test_fail_windows_handled(self) -> None:
        vr = _make_validation_result(all_pass=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "fail.png")
            path = generate_validation_chart(vr, output=out)
            assert os.path.isfile(path)


class TestGenerateFullReport:
    """generate_full_report combines equity, quantstats, IS/OOS, judgment."""

    def test_creates_html_with_validation(self) -> None:
        br = _make_backtest_result()
        vr = _make_validation_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "full.html")
            path = generate_full_report(br, validation_result=vr, output=out)
            assert os.path.isfile(path)
            assert os.path.getsize(path) > 0
            with open(path) as f:
                html = f.read()
            assert "BTC/USDT" in html
            # Should contain IS/OOS section
            assert "IS/OOS" in html or "Validation" in html
            # Should contain judgment
            assert "PASS" in html or "FAIL" in html

    def test_creates_html_without_validation(self) -> None:
        br = _make_backtest_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "no_val.html")
            path = generate_full_report(br, validation_result=None, output=out)
            assert os.path.isfile(path)
            assert os.path.getsize(path) > 0
            with open(path) as f:
                html = f.read()
            assert "BTC/USDT" in html

    def test_includes_quantstats_metrics(self) -> None:
        br = _make_backtest_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "metrics.html")
            path = generate_full_report(br, output=out)
            with open(path) as f:
                html = f.read()
            # Should contain metric labels
            assert "Sharpe" in html or "sharpe" in html
            assert "Drawdown" in html or "drawdown" in html

    def test_output_file_not_empty(self) -> None:
        br = _make_backtest_result()
        vr = _make_validation_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "size_check.html")
            path = generate_full_report(br, vr, output=out)
            assert os.path.getsize(path) > 100  # non-trivial content
