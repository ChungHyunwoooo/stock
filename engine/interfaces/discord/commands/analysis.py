from __future__ import annotations

import io
import logging

import discord
from discord import Interaction, app_commands

from engine.application.trading.charts import build_analysis_chart

logger = logging.getLogger(__name__)
from engine.application.trading.presenters import (
    build_analysis_report_presentation,
    build_signal_presentation,
)
from engine.application.trading.scanner import RecentSignalAnalysisService
from engine.interfaces.discord.autocomplete import (
    exchange_autocomplete,
    resolve_exchange_for_interaction,
    symbol_autocomplete,
    timeframe_autocomplete,
)
from engine.interfaces.discord.context import DiscordBotContext


def _embed_from_signal(presentation) -> discord.Embed:
    """SignalPresentation → discord.Embed (scan 포맷 통일)."""
    embed = discord.Embed(
        title=presentation.title,
        color=presentation.color,
        description=presentation.description if presentation.description else None,
    )
    for field in presentation.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    embed.set_footer(text=presentation.footer)
    return embed


def _embed_from_report(presentation) -> discord.Embed:
    """ReportPresentation → discord.Embed."""
    embed = discord.Embed(title=presentation.title, color=presentation.color)
    for field in presentation.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    embed.set_footer(text=presentation.footer)
    return embed


class AnalysisCommandPlugin:
    name = 'analysis'

    def __init__(self, analysis_service: RecentSignalAnalysisService | None = None) -> None:
        self.analysis_service = analysis_service or RecentSignalAnalysisService()

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:
        @tree.command(name='analysis', description='Run the same analysis used by alert scanning')
        @app_commands.describe(
            exchange='binance, bybit, okx, upbit',
            symbol='e.g. BTC/USDT or KRW-BTC',
            timeframe='1m, 5m, 15m, 30m, 1h, 4h, 1d',
        )
        @app_commands.autocomplete(
            exchange=exchange_autocomplete,
            symbol=symbol_autocomplete,
            timeframe=timeframe_autocomplete,
        )
        async def analysis(
            interaction: Interaction,
            exchange: str = '',
            symbol: str = 'BTC/USDT',
            timeframe: str = '15m',
        ) -> None:
            await interaction.response.defer(thinking=True)
            resolved_exchange = resolve_exchange_for_interaction(
                interaction,
                symbol_hint=symbol,
                explicit_exchange=exchange or None,
            )
            context.preferences.set_recent_exchange(interaction.user.id, resolved_exchange)

            # "all" → 여러 TF 순회 분석
            if timeframe.lower() == 'all':
                all_tfs = ['5m', '15m', '30m', '1h', '4h']
                chart_tfs = ['5m', '1h', '4h']  # 차트 생성 대상 TF
                files = []
                all_signals = []
                tf_summaries = []
                reports_by_tf = {}

                for tf in all_tfs:
                    report = self.analysis_service.build_report(
                        symbol=symbol, timeframe=tf, exchange=resolved_exchange,
                    )
                    reports_by_tf[tf] = report

                    trend_emoji = {
                        'BULLISH': '\U0001f7e2', 'BEARISH': '\U0001f534',
                    }.get(report.trend_bias, '\u26aa')
                    trend_kr = {
                        'BULLISH': '\uc0c1\uc2b9', 'BEARISH': '\ud558\ub77d',
                    }.get(report.trend_bias, '\ud6a1\ubcf4')
                    vol_text = f"\uac70\ub798\ub7c9 {report.volume_ratio:.1f}x" if report.volume_ratio >= 0.1 else "\uac70\ub798\ub7c9 \ubbf8\ubbf8"
                    tf_summaries.append(
                        f"**{tf}** {trend_emoji}{trend_kr} | "
                        f"\ubcc0\ub3d9 {report.price_change_pct:+.2f}% | "
                        f"{vol_text} | "
                        f"\uc2dc\uadf8\ub110 {report.signal_count}\uac1c"
                    )

                    for sig in report.signals:
                        if 'exchange' not in sig.metadata:
                            sig.metadata['exchange'] = resolved_exchange
                        if 'timeframe' not in sig.metadata:
                            sig.metadata['timeframe'] = tf
                        all_signals.append(sig)

                all_signals.sort(key=lambda s: s.confidence, reverse=True)

                ticker = symbol.replace('KRW-', '').replace('/USDT', '').replace('/KRW', '')

                # 1개 통합 요약 embed + 5m 차트
                summary_embed = discord.Embed(
                    title=f'\U0001f4ca \uc804\uccb4 TF \ubd84\uc11d: {ticker}',
                    description='\n'.join(tf_summaries),
                    color=0x2196F3,
                )
                summary_embed.set_footer(text=f'{resolved_exchange} | all TF')

                chart_5m = build_analysis_chart(reports_by_tf['5m'])
                if chart_5m:
                    summary_embed.set_image(url='attachment://chart_5m.png')
                    files.append(discord.File(io.BytesIO(chart_5m), filename='chart_5m.png'))
                embeds = [summary_embed]

                # 1h, 4h 차트 embed (각 TF별 차트)
                for ctf in chart_tfs[1:]:
                    chart_data = build_analysis_chart(reports_by_tf[ctf])
                    if chart_data:
                        fname = f'chart_{ctf}.png'
                        chart_embed = discord.Embed(
                            title=f'\U0001f4c8 {ticker} [{ctf}]',
                            color=0x2196F3,
                        )
                        chart_embed.set_image(url=f'attachment://{fname}')
                        files.append(discord.File(io.BytesIO(chart_data), filename=fname))
                        embeds.append(chart_embed)

                # 시그널 (남은 embed 슬롯)
                remaining = 10 - len(embeds)
                mode_label = context.control.get_state().mode.value
                for signal in all_signals[:remaining]:
                    presentation = build_signal_presentation(signal, mode_label)
                    embeds.append(_embed_from_signal(presentation))

                await interaction.followup.send(embeds=embeds[:10], files=files)
                return

            # 단일 TF 분석 (기존 로직)
            report = self.analysis_service.build_report(
                symbol=symbol,
                timeframe=timeframe,
                exchange=resolved_exchange,
            )
            print(f'[ANALYSIS] {symbol} [{timeframe}] on {resolved_exchange} — signals={len(report.signals)}', flush=True)
            chart_data = build_analysis_chart(report)
            print(f'[ANALYSIS] chart_data: {type(chart_data)} size={len(chart_data) if chart_data else 0}', flush=True)

            embeds = []
            files = []
            mode_label = context.control.get_state().mode.value

            # 차트 embed (별도 카드로 표시)
            if chart_data:
                ticker = symbol.replace('KRW-', '').replace('/USDT', '').replace('/KRW', '')
                chart_embed = discord.Embed(
                    title=f'\U0001f4c8 {ticker} [{timeframe}]',
                    color=0x2196F3,
                )
                chart_embed.set_image(url='attachment://analysis_chart.png')
                files.append(discord.File(io.BytesIO(chart_data), filename='analysis_chart.png'))
                embeds.append(chart_embed)

            # 시그널 embeds
            if report.signals:
                for signal in report.signals[:4]:
                    if 'exchange' not in signal.metadata:
                        signal.metadata['exchange'] = resolved_exchange
                    presentation = build_signal_presentation(signal, mode_label)
                    embeds.append(_embed_from_signal(presentation))
            else:
                report_presentation = build_analysis_report_presentation(report)
                embeds.append(_embed_from_report(report_presentation))

            await interaction.followup.send(embeds=embeds, files=files)
