
from engine.application.trading.presenters import build_analysis_report_presentation
from engine.application.trading.reports import AnalysisReport

def test_analysis_report_presentation_contains_summary_fields():
    report = AnalysisReport(
        symbol='BTC/USDT',
        exchange='binance',
        timeframe='15m',
        scanned_at='2026-03-06T00:00:00+00:00',
        last_price=100.0,
        price_change_pct=2.5,
        range_pct=5.0,
        volume_ratio=1.8,
        trend_bias='BULLISH',
        bars=300,
        high=105.0,
        low=95.0,
        signal_count=0,
        notes=['No live entry/exit signal now', 'Trend bias inferred as BULLISH'],
        signals=[],
    )

    presentation = build_analysis_report_presentation(report)
    field_names = [field.name for field in presentation.fields]
    assert 'BTC/USDT' in presentation.title
    assert '15m' in presentation.title
    assert '현재가' in field_names
    assert '추세' in field_names
    assert '시그널' in field_names
