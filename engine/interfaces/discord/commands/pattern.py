from __future__ import annotations

import io
import logging

import discord
import pandas as pd
from discord import Interaction, app_commands

from engine.analysis.chart_patterns import ChartPattern, detect_chart_patterns
from engine.application.trading.charts import build_analysis_chart
from engine.application.trading.scanner import RecentSignalAnalysisService
from engine.data.base import get_provider
from engine.interfaces.discord.autocomplete import (
    exchange_autocomplete,
    resolve_exchange_for_interaction,
    symbol_autocomplete,
    timeframe_autocomplete,
)
from engine.interfaces.discord.context import DiscordBotContext

logger = logging.getLogger(__name__)

_DIRECTION_EMOJI = {
    "BULLISH": "\U0001f7e2",
    "BEARISH": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

_DIRECTION_COLOR = {
    "BULLISH": 0x26a69a,
    "BEARISH": 0xef5350,
    "NEUTRAL": 0xF1C40F,
}

_ALL_TFS = ["15m", "1h", "4h", "1d"]


def _pattern_embed(pattern: ChartPattern, symbol: str, timeframe: str, exchange: str) -> discord.Embed:
    ticker = symbol.replace("KRW-", "").replace("/USDT", "").replace("/KRW", "")
    emoji = _DIRECTION_EMOJI.get(pattern.direction, "\u26aa")
    color = _DIRECTION_COLOR.get(pattern.direction, 0xF1C40F)

    filled = int(pattern.confidence * 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)

    embed = discord.Embed(
        title=f"{emoji} {pattern.name} [{timeframe}] \u2014 {ticker}",
        description=pattern.description,
        color=color,
    )
    embed.add_field(name="\uc2e0\ub8b0\ub3c4", value=f"{bar} **{pattern.confidence:.0%}**", inline=True)
    embed.add_field(name="\ubc29\ud5a5", value=f"{emoji} {pattern.direction}", inline=True)

    if pattern.key_prices:
        price_lines = []
        for k, v in pattern.key_prices.items():
            label = k.replace("_", " ").title()
            price_lines.append(f"{label}: **{v:,.0f}**")
        embed.add_field(name="\ud575\uc2ec \uac00\uaca9", value="\n".join(price_lines), inline=False)

    embed.set_footer(text=f"{exchange} | {timeframe}")
    return embed


class PatternCommandPlugin:
    name = "pattern"

    def __init__(self, analysis_service: RecentSignalAnalysisService | None = None) -> None:
        self.analysis_service = analysis_service or RecentSignalAnalysisService()

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name="pattern", description="Detect classic chart patterns (Double Top, H&S, Cup&Handle, etc.)")
        @app_commands.describe(
            exchange="binance, bybit, okx, upbit",
            symbol="e.g. BTC/USDT or KRW-BTC",
            timeframe='15m, 1h, 4h, 1d (or "all")',
        )
        @app_commands.autocomplete(
            exchange=exchange_autocomplete,
            symbol=symbol_autocomplete,
            timeframe=timeframe_autocomplete,
        )
        async def pattern(
            interaction: Interaction,
            exchange: str = "",
            symbol: str = "BTC/USDT",
            timeframe: str = "4h",
        ) -> None:
            await interaction.response.defer(thinking=True)
            resolved_exchange = resolve_exchange_for_interaction(
                interaction,
                symbol_hint=symbol,
                explicit_exchange=exchange or None,
            )
            context.preferences.set_recent_exchange(interaction.user.id, resolved_exchange)

            timeframes = _ALL_TFS if timeframe.lower() == "all" else [timeframe]

            embeds: list[discord.Embed] = []
            files: list[discord.File] = []
            found_any = False

            for tf in timeframes:
                report = self.analysis_service.build_report(
                    symbol=symbol, timeframe=tf, exchange=resolved_exchange,
                    lookback_bars=300,
                )

                market = _market_for_symbol(symbol)
                provider = get_provider(market, exchange=resolved_exchange)
                end = pd.Timestamp.now(tz="UTC")
                delta_map = {
                    "5m": pd.Timedelta(hours=18),
                    "15m": pd.Timedelta(days=3),
                    "30m": pd.Timedelta(days=6),
                    "1h": pd.Timedelta(days=14),
                    "4h": pd.Timedelta(days=60),
                    "1d": pd.Timedelta(days=360),
                }
                start = end - delta_map.get(tf, pd.Timedelta(days=14))
                df = provider.fetch_ohlcv(
                    symbol,
                    start.strftime("%Y-%m-%d %H:%M:%S"),
                    end.strftime("%Y-%m-%d %H:%M:%S"),
                    tf,
                )

                if df.empty:
                    continue

                patterns = detect_chart_patterns(df, lookback=min(len(df), 120))
                if not patterns:
                    continue

                found_any = True

                # 차트 첨부 (첫 TF만)
                if not files:
                    chart_data = build_analysis_chart(report)
                    if chart_data:
                        ticker = symbol.replace("KRW-", "").replace("/USDT", "").replace("/KRW", "")
                        chart_embed = discord.Embed(
                            title=f"\U0001f4c8 {ticker} [{tf}]",
                            color=0x2196F3,
                        )
                        chart_embed.set_image(url="attachment://pattern_chart.png")
                        files.append(discord.File(io.BytesIO(chart_data), filename="pattern_chart.png"))
                        embeds.append(chart_embed)

                for p in patterns[:3]:
                    embeds.append(_pattern_embed(p, symbol, tf, resolved_exchange))

                if len(embeds) >= 9:
                    break

            if not found_any:
                ticker = symbol.replace("KRW-", "").replace("/USDT", "").replace("/KRW", "")
                tfs_label = ", ".join(timeframes)
                embed = discord.Embed(
                    title=f"\U0001f50d {ticker} \ud328\ud134 \ubd84\uc11d",
                    description=f"[{tfs_label}] \uad6c\uac04\uc5d0\uc11c \uac10\uc9c0\ub41c \ud328\ud134\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.",
                    color=0x888888,
                )
                embeds.append(embed)

            await interaction.followup.send(embeds=embeds[:10], files=files)


def _market_for_symbol(symbol: str):
    from engine.schema import MarketType  # lazy to avoid circular import
    normalized = symbol.upper()
    if "/" in normalized or normalized.startswith(("KRW-", "BTC-", "USDT-")):
        return MarketType.crypto_spot
    if normalized.isdigit():
        return MarketType.kr_stock
    return MarketType.us_stock
