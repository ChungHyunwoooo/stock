from __future__ import annotations

from dataclasses import dataclass

from engine.application.trading.reports import AnalysisReport
from engine.domain.trading.models import TradingSignal


@dataclass(frozen=True, slots=True)
class SignalField:
    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True, slots=True)
class SignalPresentation:
    title: str
    color: int
    fields: list[SignalField]
    footer: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ReportPresentation:
    title: str
    color: int
    fields: list[SignalField]
    footer: str


_STRAT_NAMES = {
    "UPBIT_EMA_RSI_VWAP": "EMA+RSI+VWAP",
    "UPBIT_SUPERTREND": "\uc288\ud37c\ud2b8\ub80c\ub4dc",
    "UPBIT_MACD_DIV": "MACD \ub2e4\uc774\ubc84\uc804\uc2a4",
    "UPBIT_STOCH_RSI": "\uc2a4\ud1a0\uce90\uc2a4\ud2f1RSI",
    "UPBIT_FIBONACCI": "\ud53c\ubcf4\ub098\uce58",
    "UPBIT_ICHIMOKU": "\uc77c\ubaa9\uade0\ud615\ud45c",
    "UPBIT_EARLY_PUMP": "\ucd08\uae30\uae09\ub4f1 \uac10\uc9c0",
    "UPBIT_SMC": "\uc2a4\ub9c8\ud2b8\uba38\ub2c8",
    "UPBIT_HIDDEN_DIV": "\ud788\ub4e0 \ub2e4\uc774\ubc84\uc804\uc2a4",
    "UPBIT_BB_RSI_STOCH": "BB+RSI+Stoch",
    "UPBIT_MEGA_PUMP": "\uae09\ub4f1\uc804\uc870 \uac10\uc9c0",
    "UPBIT_TOMMY_MACD": "Tommy MACD \ud53c\ud06c\uc544\uc6c3",
    "UPBIT_TOMMY_BB_RSI": "Tommy BB+RSI \uac15\ud654",
}


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}"
    elif p >= 100:
        return f"{p:,.1f}"
    elif p >= 10:
        return f"{p:,.2f}"
    elif p >= 1:
        return f"{p:,.3f}"
    else:
        return f"{p:,.4f}"


def build_signal_presentation(signal: TradingSignal, mode_label: str) -> SignalPresentation:
    """scan alert(send_upbit_alert) 포맷과 통일된 시그널 프레젠테이션."""
    entry = signal.entry_price
    side_str = signal.side.value.upper()
    side_emoji = "\U0001f7e2" if side_str == "LONG" else "\U0001f534"
    side_kr = "\ub9e4\uc218" if side_str == "LONG" else "\ub9e4\ub3c4"
    color = 0x26a69a if side_str == "LONG" else 0xef5350

    strat_display = _STRAT_NAMES.get(signal.strategy_id, signal.strategy_id)
    meta = signal.metadata or {}

    # R:R 비율 계산
    risk = abs(entry - signal.stop_loss) if signal.stop_loss is not None else 0
    sl_pct = (risk / entry * 100) if entry else 0

    tp_lines = []
    rr_parts = []
    for i, tp in enumerate(signal.take_profits[:3], 1):
        tp_pct = abs(tp - entry) / entry * 100 if entry else 0
        rr = abs(tp - entry) / risk if risk > 0 else 0
        tp_lines.append(f"TP{i}: {_fmt_price(tp)}\uc6d0 (+{tp_pct:.1f}%) `{rr:.1f}R`")
        rr_parts.append(f"{rr:.1f}R")

    rr_text = " / ".join(rr_parts) if rr_parts else "\u2014"

    # 신뢰도 바 + 분해
    filled = int(signal.confidence * 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    conf_text = f"{bar} **{signal.confidence:.0%}**"
    conf_breakdown = meta.get("confidence_breakdown", "")
    if conf_breakdown:
        conf_text += f"\n`{conf_breakdown}`"

    # 시장 상태 라인
    trend = meta.get("trend", "")
    adx_val = float(meta.get("adx", 0))
    adx_label = "\uac15\ud55c\ucd94\uc138" if adx_val > 25 else ("\uc57d\ucd94\uc138" if adx_val > 18 else "\ud6a1\ubcf4")
    vol_ratio = float(meta.get("vol_ratio", 0))
    obv_trend = meta.get("obv_trend", "")

    market_parts = []
    if trend:
        trend_emoji = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534", "RANGING": "\u26aa"}.get(str(trend), "\u26aa")
        market_parts.append(f"{trend_emoji} {trend}")
    if adx_val > 0:
        market_parts.append(f"ADX {adx_val:.0f} ({adx_label})")
    if vol_ratio > 0:
        vol_emoji = "\U0001f4c8" if vol_ratio >= 1.5 else "\U0001f4ca"
        market_parts.append(f"{vol_emoji} \uac70\ub798\ub7c9 {vol_ratio:.1f}x")
    if obv_trend:
        market_parts.append(f"OBV {obv_trend}")
    market_line = " | ".join(market_parts) if market_parts else ""

    # 주의사항
    warnings = []
    if meta.get("counter_trend", False):
        warnings.append("\u26a0\ufe0f \uc5ed\ucd94\uc138 \uc9c4\uc785")
    if meta.get("is_climactic", False):
        warnings.append("\u26a0\ufe0f \ud074\ub77c\uc774\ub9e5\uc2a4 \uac70\ub798\ub7c9")
    if meta.get("at_resistance", False) and side_str == "LONG":
        warnings.append("\u26a0\ufe0f \uc800\ud56d\uc120 \uadfc\uc811")
    if meta.get("at_support", False) and side_str == "SHORT":
        warnings.append("\u26a0\ufe0f \uc9c0\uc9c0\uc120 \uadfc\uc811")
    warning_text = "\n".join(warnings)

    # Description
    desc_parts = [
        f"**{strat_display}** | {side_kr} | R:R {rr_text}",
        "\u2501" * 20,
        f"**\uc0ac\uc720**: {signal.reason}" if signal.reason else "",
    ]
    if market_line:
        desc_parts.append(f"**\uc2dc\uc7a5**: {market_line}")
    if warning_text:
        desc_parts.append(warning_text)
    description = "\n".join(p for p in desc_parts if p)

    # Fields
    fields = [
        SignalField("\uc9c4\uc785\uac00", f"**{_fmt_price(entry)}\uc6d0**", inline=True),
        SignalField("\uc190\uc808\uac00", f"{_fmt_price(signal.stop_loss)}\uc6d0 (-{sl_pct:.1f}%)" if signal.stop_loss else "\u2014", inline=True),
        SignalField("\uc2e0\ub8b0\ub3c4", conf_text, inline=True),
    ]
    if tp_lines:
        fields.append(SignalField("\ubaa9\ud45c\uac00", "\n".join(tp_lines), inline=False))

    tf = signal.timeframe or meta.get("timeframe", "")
    exchange = meta.get("exchange", "")
    ticker = signal.symbol.replace("KRW-", "").replace("/USDT", "").replace("/KRW", "")
    footer_parts = [exchange, tf, signal.created_at] if exchange else [tf, signal.created_at]

    return SignalPresentation(
        title=f"{side_emoji} {side_str} [{tf}] \u2014 {ticker}",
        color=color,
        fields=fields,
        footer=" | ".join(p for p in footer_parts if p),
        description=description,
    )


def build_analysis_report_presentation(report: AnalysisReport) -> ReportPresentation:
    trend_emoji = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534"}.get(report.trend_bias, "\u26aa")
    color = 0x26a69a if report.trend_bias == "BULLISH" else 0xef5350 if report.trend_bias == "BEARISH" else 0xF1C40F
    trend_kr = {
        "BULLISH": "\uc0c1\uc2b9\ucd94\uc138",
        "BEARISH": "\ud558\ub77d\ucd94\uc138",
        "RANGE": "\ud6a1\ubcf4",
    }.get(report.trend_bias, report.trend_bias)

    fields = [
        SignalField("\ud604\uc7ac\uac00", f"**{_fmt_price(report.last_price)}\uc6d0**", inline=True),
        SignalField("\ubcc0\ub3d9\ub960", f"{report.price_change_pct:+.2f}%", inline=True),
        SignalField("\uac70\ub798\ub7c9", f"{report.volume_ratio:.2f}x", inline=True),
        SignalField("\ucd94\uc138", f"{trend_emoji} {trend_kr}", inline=True),
        SignalField("\uc2dc\uadf8\ub110", f"{report.signal_count}\uac1c", inline=True),
        SignalField("\ubc94\uc704", f"{_fmt_price(report.low)} ~ {_fmt_price(report.high)} ({report.range_pct:.1f}%)", inline=False),
    ]
    if report.notes:
        fields.append(SignalField("\uc694\uc57d", "\n".join(report.notes[:5]), inline=False))
    return ReportPresentation(
        title=f"\U0001f4ca \ubd84\uc11d: {report.symbol} [{report.timeframe}]",
        color=color,
        fields=fields,
        footer=f"{report.exchange} | {report.timeframe} | {report.scanned_at}",
    )
