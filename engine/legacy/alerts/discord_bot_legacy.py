"""Interactive Discord Bot for Upbit KRW Day Trading.

Slash commands for controlling the scanner and viewing signals.
Runs alongside the webhook alerts — bot handles interaction,
webhooks handle automated notifications.

The bot client is recreated on each start to avoid stale aiohttp sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "discord.json"


def _load_token() -> str | None:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        return data.get("bot_token")
    return None


def _build_strategy_list(config):
    """Build list of enabled strategy scan functions from config."""
    from engine.strategy.upbit_scanner import (
        scan_ema_rsi_vwap, scan_supertrend, scan_macd_divergence,
        scan_stoch_rsi, scan_fibonacci, scan_ichimoku, scan_early_pump,
        scan_smc, scan_hidden_divergence, scan_bb_rsi_stoch,
    )
    strategies = []
    if config.enable_ema_rsi_vwap:
        strategies.append(("EMA+RSI+VWAP", scan_ema_rsi_vwap))
    if config.enable_supertrend:
        strategies.append(("Supertrend", scan_supertrend))
    if config.enable_macd_div:
        strategies.append(("MACD Divergence", scan_macd_divergence))
    if config.enable_stoch_rsi:
        strategies.append(("StochRSI", scan_stoch_rsi))
    if config.enable_fibonacci:
        strategies.append(("Fibonacci", scan_fibonacci))
    if config.enable_ichimoku:
        strategies.append(("Ichimoku", scan_ichimoku))
    if config.enable_early_pump:
        strategies.append(("Early Pump", scan_early_pump))
    if config.enable_smc:
        strategies.append(("SMC", scan_smc))
    if config.enable_hidden_div:
        strategies.append(("Hidden Div", scan_hidden_divergence))
    if config.enable_bb_rsi_stoch:
        strategies.append(("BB+RSI+Stoch", scan_bb_rsi_stoch))
    return strategies


# ---------------------------------------------------------------------------
# Bot state
# ---------------------------------------------------------------------------

_bot: discord.Client | None = None
_bot_thread: threading.Thread | None = None
_bot_running = False


def _create_bot() -> discord.Client:
    """Create a fresh bot client with all slash commands registered."""
    global _bot

    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)
    cmd_tree = app_commands.CommandTree(client)

    # -- on_ready -----------------------------------------------------------

    @client.event
    async def on_ready():
        logger.info("Discord bot logged in as %s", client.user)
        try:
            synced = await cmd_tree.sync()
            logger.info("Synced %d commands", len(synced))
        except Exception as e:
            logger.error("Command sync failed: %s", e)

    @cmd_tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.exception("Command error: %s", error)
        msg = f"명령어 오류: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg)
        except Exception:
            pass

    # -- /start -------------------------------------------------------------

    @cmd_tree.command(name="start", description="Upbit KRW 스캐너 시작")
    async def cmd_start(interaction: discord.Interaction):
        from engine.strategy.upbit_scanner import start, status, is_running

        if is_running():
            s = status()
            await interaction.response.send_message(
                f"이미 실행 중입니다.\n"
                f"스캔 #{s['scan_count']} | {s['symbols_count']}종목 | 간격 {s['scan_interval_sec']}초"
            )
            return

        start()
        s = status()
        from engine.strategy.upbit_scanner import UpbitScannerConfig
        cfg = UpbitScannerConfig.load()
        strats = _build_strategy_list(cfg)
        names = ", ".join(n for n, _ in strats)
        await interaction.response.send_message(
            f"**스캐너 시작됨**\n"
            f"전략: {names}\n"
            f"종목: KRW 전체 (거래량 상위 자동 선별)\n"
            f"간격: {s['scan_interval_sec']}초"
        )

    # -- /stop --------------------------------------------------------------

    @cmd_tree.command(name="stop", description="Upbit KRW 스캐너 정지")
    async def cmd_stop(interaction: discord.Interaction):
        from engine.strategy.upbit_scanner import stop, is_running

        if not is_running():
            await interaction.response.send_message("스캐너가 실행 중이 아닙니다.")
            return

        stop()
        await interaction.response.send_message("**스캐너 정지됨**")

    # -- /status ------------------------------------------------------------

    @cmd_tree.command(name="status", description="스캐너 상태 확인")
    async def cmd_status(interaction: discord.Interaction):
        from engine.strategy.upbit_scanner import status

        s = status()
        running = " Running" if s["running"] else " Stopped"
        mode = s.get("mode", "polling")
        mode_label = "WebSocket" if mode == "websocket" else "Polling"

        embed = discord.Embed(
            title=f"Trading Bot {running}",
            color=0x26a69a if s["running"] else 0xef5350,
        )
        embed.add_field(name="모드", value=mode_label, inline=True)
        embed.add_field(name="스캔 횟수", value=str(s["scan_count"]), inline=True)
        embed.add_field(name="감시 종목", value=f"{s['symbols_count']}개", inline=True)
        embed.add_field(name="최근 알림", value=f"{s['recent_alerts']}건", inline=True)
        embed.add_field(name="MTF 필터", value="ON" if s.get("enable_mtf") else "OFF", inline=True)

        # WebSocket status
        ws_status = s.get("ws_status")
        if ws_status:
            ws_connected = "연결됨" if ws_status.get("connected") else "끊김"
            embed.add_field(
                name="WebSocket",
                value=f"{ws_connected} | Tick: {ws_status.get('tick_count', 0):,} | 재연결: {ws_status.get('reconnect_count', 0)}",
                inline=False,
            )

        # Cache stats
        cache_stats = s.get("cache_stats")
        if cache_stats:
            embed.add_field(
                name="캐시",
                value=f"항목: {cache_stats.get('active_entries', 0)} | 히트율: {cache_stats.get('hit_rate', 0)}%",
                inline=False,
            )

        # Per-timeframe status
        tf_info = s.get("timeframes", {})
        if tf_info:
            tf_lines = []
            for label in ["4h", "1h", "30m", "5m"]:
                info = tf_info.get(label)
                if not info:
                    continue
                icon = "\u2705" if info.get("running") else "\u274c"
                scans = info.get("scan_count", 0)
                interval = info.get("scan_interval_sec", 0)
                last = info.get("last_scan", "—") or "—"
                tf_lines.append(f"{icon} **{label}** — {interval}s 간격 | #{scans} | {last}")
            if tf_lines:
                embed.add_field(
                    name="타임프레임 스캔",
                    value="\n".join(tf_lines),
                    inline=False,
                )

        if s["last_scan"]:
            embed.add_field(name="마지막 스캔", value=s["last_scan"], inline=False)

        await interaction.response.send_message(embed=embed)

    # -- /scan --------------------------------------------------------------

    @cmd_tree.command(name="scan", description="Upbit KRW 전 종목 즉시 스캔 (전 전략, v2 다중컨펌)")
    async def cmd_scan(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import (
            fetch_upbit_ohlcv, generate_chart,
            send_upbit_alert, UpbitScannerConfig, _get_active_symbols,
            validate_signal_rr,
        )
        from engine.analysis import build_context

        config = UpbitScannerConfig.load()
        strategies = _build_strategy_list(config)
        loop = asyncio.get_event_loop()
        # 자동(거래량 상위) + 수동(config.symbols) 합집합
        auto_syms = await loop.run_in_executor(None, _get_active_symbols)
        manual_syms = list(config.symbols) if config.symbols else []
        seen = set(auto_syms)
        symbols = list(auto_syms)
        for s in manual_syms:
            if s not in seen:
                symbols.append(s)
                seen.add(s)

        signals: list[tuple] = []
        for sym in symbols:
            try:
                df = await loop.run_in_executor(
                    None, lambda s=sym: fetch_upbit_ohlcv(s)
                )
                if df is None:
                    continue
                # Build analysis context once per symbol
                try:
                    ctx = await loop.run_in_executor(None, lambda d=df: build_context(d))
                except Exception:
                    ctx = {}
                for _name, scan_fn in strategies:
                    try:
                        sig = scan_fn(df, sym, config, context=ctx)
                        if sig:
                            sig = validate_signal_rr(sig)
                        if sig:
                            signals.append((sig, df))
                    except TypeError:
                        try:
                            sig = scan_fn(df, sym, config)
                            if sig:
                                sig = validate_signal_rr(sig)
                            if sig:
                                signals.append((sig, df))
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(0.1)

        strat_names = ", ".join(n for n, _ in strategies)
        if not signals:
            await interaction.followup.send(
                f"**{len(symbols)}종목 × {len(strategies)}전략 스캔 완료** — 시그널 없음\n"
                f"전략: {strat_names}\n"
                f"자동 스캔 중 감지되면 알림됩니다."
            )
            return

        # Strategy name mapping
        _strat_short = {
            "UPBIT_EMA_RSI_VWAP": "EMA+RSI",
            "UPBIT_SUPERTREND": "SuperTrend",
            "UPBIT_MACD_DIV": "MACD",
            "UPBIT_STOCH_RSI": "StochRSI",
            "UPBIT_FIBONACCI": "Fibo",
            "UPBIT_ICHIMOKU": "Ichimoku",
            "UPBIT_EARLY_PUMP": "Pump",
            "UPBIT_SMC": "SMC",
            "UPBIT_HIDDEN_DIV": "HidDiv",
            "UPBIT_BB_RSI_STOCH": "BB+RSI",
        }

        def _fmt(p: float) -> str:
            if p >= 1000:
                return f"{p:,.0f}"
            elif p >= 10:
                return f"{p:.2f}"
            else:
                return f"{p:.3f}"

        # Build summary embed
        embed = discord.Embed(
            title=f"스캔 결과 — {len(signals)}개 시그널",
            description=(
                f"**{len(symbols)}종목 × {len(strategies)}전략**\n"
                f"전략: {strat_names}"
            ),
            color=0x2196F3,
        )

        # Group by signal and add fields (max 25 fields in embed)
        for i, (sig, df) in enumerate(signals[:20]):
            ticker = sig.symbol.replace("KRW-", "")
            strat = _strat_short.get(sig.strategy, sig.strategy)
            side_icon = "🟢" if sig.side == "LONG" else "🔴"
            sl_pct = abs(sig.stop_loss - sig.entry) / sig.entry * 100
            tp1_pct = abs(sig.take_profits[0] - sig.entry) / sig.entry * 100

            embed.add_field(
                name=f"{side_icon} {ticker} — {strat}",
                value=(
                    f"진입: **{_fmt(sig.entry)}**원\n"
                    f"SL: {_fmt(sig.stop_loss)} (-{sl_pct:.1f}%) | "
                    f"TP1: {_fmt(sig.take_profits[0])} (+{tp1_pct:.1f}%)\n"
                    f"신뢰도: {sig.confidence:.0%}"
                ),
                inline=True,
            )

        if len(signals) > 20:
            embed.set_footer(text=f"외 {len(signals) - 20}개 시그널 생략")

        await interaction.followup.send(embed=embed)

        # Also send individual alerts via webhook for logging
        for sig, df in signals:
            try:
                chart_data = await loop.run_in_executor(
                    None, lambda d=df, s=sig: generate_chart(d, s, config)
                )
                await loop.run_in_executor(
                    None, lambda s=sig, c=chart_data: send_upbit_alert(s, c)
                )
            except Exception as e:
                logger.warning("Scan alert send error: %s", e)

    # -- /coin --------------------------------------------------------------

    @cmd_tree.command(name="coin", description="특정 코인 전 전략 + 다중컨펌 분석 (v2)")
    @app_commands.describe(symbol="종목 (예: BTC, ETH, SOL)")
    async def cmd_coin(interaction: discord.Interaction, symbol: str):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import (
            fetch_upbit_ohlcv, generate_chart, UpbitScannerConfig, _calc_vwap,
            validate_signal_rr,
        )
        from engine.analysis import build_context
        import talib

        ticker = f"KRW-{symbol.upper()}"
        config = UpbitScannerConfig.load()
        loop = asyncio.get_event_loop()

        df = await loop.run_in_executor(None, lambda: fetch_upbit_ohlcv(ticker))
        if df is None or len(df) < 50:
            await interaction.followup.send(f"`{ticker}` 데이터를 가져올 수 없습니다.")
            return

        close = df["close"].values
        vwap = _calc_vwap(df).values
        curr = float(close[-1])
        curr_vwap = float(vwap[-1])

        # Build v2 analysis context
        try:
            ctx = await loop.run_in_executor(None, lambda: build_context(df))
        except Exception:
            ctx = {}

        structure = ctx.get("structure", {})
        adx = ctx.get("adx", {})
        vol_ctx = ctx.get("volume", {})
        bb = ctx.get("bb", {})
        candle = ctx.get("candle", {})
        kl = ctx.get("key_levels", {})
        pb = ctx.get("pullback", {})

        # Color by structure trend
        color_map = {"BULLISH": 0x26a69a, "BEARISH": 0xef5350, "RANGING": 0x607D8B}
        embed = discord.Embed(
            title=f"{symbol.upper()}/KRW 다중컨펌 분석",
            color=color_map.get(structure.get("trend", "RANGING"), 0x607D8B),
        )
        embed.add_field(name="현재가", value=f"{curr:,.0f}원", inline=True)
        embed.add_field(
            name="시장구조",
            value=f"{structure.get('trend', '?')} (HH:{structure.get('hh_count', 0)} HL:{structure.get('hl_count', 0)})",
            inline=True,
        )
        embed.add_field(
            name="ADX",
            value=f"{adx.get('adx', 0):.1f} {'추세' if adx.get('is_trending') else '횡보'} ({adx.get('trend_direction', '?')})",
            inline=True,
        )
        embed.add_field(
            name="거래량",
            value=f"{vol_ctx.get('vol_ratio', 0):.1f}x | OBV:{vol_ctx.get('obv_trend', '?')} | MFI:{vol_ctx.get('mfi', 0):.0f}",
            inline=True,
        )
        embed.add_field(
            name="BB",
            value=f"%B:{bb.get('pct_b', 0):.2f} | {'스퀴즈' if bb.get('is_squeeze') else '확장' if bb.get('is_expansion') else '보통'}",
            inline=True,
        )
        embed.add_field(
            name="VWAP",
            value=f"{curr_vwap:,.0f}원 ({'상단' if curr > curr_vwap else '하단'})",
            inline=True,
        )

        # Key levels
        sup = kl.get("nearest_support", 0)
        res = kl.get("nearest_resistance", 0)
        kl_text = ""
        if sup > 0:
            kl_text += f"지지: {sup:,.0f}{'  근접' if kl.get('at_support') else ''}\n"
        if res > 0:
            kl_text += f"저항: {res:,.0f}{'  근접' if kl.get('at_resistance') else ''}"
        if kl_text:
            embed.add_field(name="키레벨", value=kl_text or "없음", inline=True)

        # Candle patterns
        candle_parts = []
        if candle.get("bullish_engulfing"):
            candle_parts.append("상승장악형")
        if candle.get("bearish_engulfing"):
            candle_parts.append("하락장악형")
        if candle.get("bullish_pin_bar"):
            candle_parts.append("상승핀바")
        if candle.get("bearish_pin_bar"):
            candle_parts.append("하락핀바")
        if candle.get("inside_bar"):
            candle_parts.append("내포봉")
        embed.add_field(
            name="캔들",
            value=", ".join(candle_parts) if candle_parts else "패턴 없음",
            inline=True,
        )

        # Pullback
        if pb.get("is_pullback_to_ema"):
            pb_text = f"EMA 터치 (깊이:{pb.get('pullback_depth_pct', 0):.1f}%) {'바운스확인' if pb.get('bounce_confirmed') else '대기중'}"
        else:
            pb_text = "되돌림 없음"
        embed.add_field(name="풀백", value=pb_text, inline=True)

        # BOS
        bos_parts = []
        if structure.get("bos_bullish"):
            bos_parts.append("BOS 상승돌파")
        if structure.get("bos_bearish"):
            bos_parts.append("BOS 하락이탈")
        if bos_parts:
            embed.add_field(name="구조돌파", value=" | ".join(bos_parts), inline=True)

        # Run all enabled strategies with context
        strategies = _build_strategy_list(config)
        found_signals = []
        for strat_name, scan_fn in strategies:
            try:
                sig = scan_fn(df, ticker, config, context=ctx)
                if sig:
                    sig = validate_signal_rr(sig)
                if sig:
                    found_signals.append((strat_name, sig))
            except TypeError:
                try:
                    sig = scan_fn(df, ticker, config)
                    if sig:
                        sig = validate_signal_rr(sig)
                    if sig:
                        found_signals.append((strat_name, sig))
                except Exception:
                    pass
            except Exception:
                pass

        if found_signals:
            for strat_name, sig in found_signals:
                sl_pct = abs(sig.stop_loss - sig.entry) / sig.entry * 100
                tp1_pct = abs(sig.take_profits[0] - sig.entry) / sig.entry * 100
                embed.add_field(
                    name=f"{'🟢' if sig.side == 'LONG' else '🔴'} {sig.side} — {strat_name} ({sig.confidence:.0%})",
                    value=(
                        f"진입: {sig.entry:,.0f}원 | SL: {sig.stop_loss:,.0f}원 (-{sl_pct:.1f}%)\n"
                        f"TP1: {sig.take_profits[0]:,.0f}원 (+{tp1_pct:.1f}%)\n"
                        f"{sig.reason}"
                    ),
                    inline=False,
                )
            first_sig = found_signals[0][1]
            chart_data = await loop.run_in_executor(
                None, lambda: generate_chart(df, first_sig, config)
            )
            if chart_data:
                import io as _io
                file = discord.File(fp=_io.BytesIO(chart_data), filename="chart.png")
                embed.set_image(url="attachment://chart.png")
                await interaction.followup.send(embed=embed, file=file)
                return
        else:
            embed.add_field(
                name="시그널",
                value=f"{len(strategies)}개 전략 × 다중컨펌 필터 → 조건 미충족",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    # -- /analyze -----------------------------------------------------------

    @cmd_tree.command(name="analyze", description="코인 다중컨펌 분석 (시장구조/ADX/거래량/BB/캔들/키레벨)")
    @app_commands.describe(symbol="종목 (예: BTC, ETH, SOL)")
    async def cmd_analyze(interaction: discord.Interaction, symbol: str):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import fetch_upbit_ohlcv
        from engine.analysis import build_context, calc_confidence_v2

        ticker = f"KRW-{symbol.upper()}"
        loop = asyncio.get_event_loop()

        df = await loop.run_in_executor(None, lambda: fetch_upbit_ohlcv(ticker))
        if df is None or len(df) < 50:
            await interaction.followup.send(f"`{ticker}` 데이터를 가져올 수 없습니다.")
            return

        ctx = await loop.run_in_executor(None, lambda: build_context(df))
        curr = float(df["close"].iloc[-1])

        s = ctx["structure"]
        a = ctx["adx"]
        v = ctx["volume"]
        b = ctx["bb"]
        c = ctx["candle"]
        k = ctx["key_levels"]
        p = ctx["pullback"]

        # Overall bias
        bull_score = 0
        bear_score = 0
        if s["trend"] == "BULLISH":
            bull_score += 2
        elif s["trend"] == "BEARISH":
            bear_score += 2
        if a["trend_direction"] == "BULLISH":
            bull_score += 1
        elif a["trend_direction"] == "BEARISH":
            bear_score += 1
        if v["obv_trend"] == "RISING":
            bull_score += 1
        elif v["obv_trend"] == "FALLING":
            bear_score += 1
        if s.get("bos_bullish"):
            bull_score += 1
        if s.get("bos_bearish"):
            bear_score += 1

        if bull_score > bear_score + 1:
            bias = "BULLISH"
            bias_color = 0x26a69a
        elif bear_score > bull_score + 1:
            bias = "BEARISH"
            bias_color = 0xef5350
        else:
            bias = "NEUTRAL"
            bias_color = 0x607D8B

        # Confidence for hypothetical LONG/SHORT
        dummy_base = 0.5
        conf_long = calc_confidence_v2(dummy_base, a, v, s, c, k, "LONG")
        conf_short = calc_confidence_v2(dummy_base, a, v, s, c, k, "SHORT")

        # Outlook guidance: "이쯤 좋아질 가능성" 시나리오
        def _build_outlook() -> tuple[str, str]:
            points: list[str] = []
            action = "관망"

            # bullish recovery zone hint
            if k.get("nearest_support", 0) > 0:
                sup = float(k["nearest_support"])
                points.append(f"지지선 {sup:,.0f} 부근 유지 시 반등 확률 증가")
            if k.get("nearest_resistance", 0) > 0:
                res = float(k["nearest_resistance"])
                points.append(f"저항선 {res:,.0f} 돌파 시 추세 개선 가능")

            # volatility regime hint
            if b.get("is_squeeze"):
                points.append("BB 스퀴즈 상태라 변동성 확장 직전일 수 있음")
            elif b.get("is_expansion"):
                points.append("변동성 확장 구간, 추세 지속/가속 체크 필요")

            # trend strength hint
            adx_v = float(a.get("adx", 0.0))
            if adx_v < 18:
                points.append("ADX 약세(횡보)라 방향성 확인 전까지 추격 진입 비권장")
            elif adx_v >= 23:
                points.append("ADX 강세라 방향 맞을 때 신뢰도 상대적 우위")

            # pullback hint
            if p.get("is_pullback_to_ema") and p.get("bounce_confirmed"):
                points.append("EMA 풀백 바운스 확인되어 재상승/재하락 연장 확률 높음")

            # choose actionable bias
            if conf_long >= 0.62 and conf_long > conf_short + 0.08:
                action = "LONG 관점 우세"
            elif conf_short >= 0.62 and conf_short > conf_long + 0.08:
                action = "SHORT 관점 우세"
            elif conf_long >= 0.55 or conf_short >= 0.55:
                action = "조건부 진입 (확인봉 대기)"

            if not points:
                points.append("유의미한 개선 시그널 부족 — 핵심 레벨/거래량 확인 필요")

            return action, "\n".join(f"• {x}" for x in points[:4])

        embed = discord.Embed(
            title=f"📊 {symbol.upper()}/KRW 다중컨펌 분석",
            description=f"**현재가**: {curr:,.0f}원 | **편향**: {bias}",
            color=bias_color,
        )

        # 시장구조
        bos_text = ""
        if s["bos_bullish"]:
            bos_text = " | BOS↑"
        elif s["bos_bearish"]:
            bos_text = " | BOS↓"
        embed.add_field(
            name="🏗️ 시장구조",
            value=(
                f"**{s['trend']}** (HH:{s['hh_count']} HL:{s['hl_count']})\n"
                f"스윙고점: {s['last_swing_high']:,.0f} | 스윙저점: {s['last_swing_low']:,.0f}{bos_text}"
            ),
            inline=False,
        )

        # ADX
        trend_label = "**강한 추세**" if a["is_strong_trend"] else "추세" if a["is_trending"] else "횡보"
        embed.add_field(
            name="📈 ADX 추세강도",
            value=(
                f"ADX: **{a['adx']:.1f}** ({trend_label})\n"
                f"DI+: {a['plus_di']:.1f} | DI-: {a['minus_di']:.1f} → **{a['trend_direction']}**"
            ),
            inline=True,
        )

        # 거래량
        climactic = " **클라이맥스!**" if v["is_climactic"] else ""
        div_warn = " ⚠️다이버전스" if v["vol_price_divergence"] else ""
        embed.add_field(
            name="📊 거래량 프로파일",
            value=(
                f"비율: **{v['vol_ratio']:.1f}x** | 추세: {v['vol_trend']}\n"
                f"OBV: {v['obv_trend']} | MFI: {v['mfi']:.0f}{climactic}{div_warn}"
            ),
            inline=True,
        )

        # BB
        squeeze_label = "**스퀴즈** (폭발 대기)" if b["is_squeeze"] else "**확장**" if b["is_expansion"] else "보통"
        embed.add_field(
            name="📉 볼린저밴드",
            value=(
                f"%B: **{b['pct_b']:.2f}** | 밴드폭: {b['bandwidth']:.2f}\n"
                f"상태: {squeeze_label}"
            ),
            inline=True,
        )

        # 키레벨
        sup_text = f"{k['nearest_support']:,.0f} (터치:{k['support_touches']})" if k["nearest_support"] > 0 else "없음"
        res_text = f"{k['nearest_resistance']:,.0f} (터치:{k['resistance_touches']})" if k["nearest_resistance"] > 0 else "없음"
        proximity = ""
        if k["at_support"]:
            proximity = " ← **지지선 근접**"
        elif k["at_resistance"]:
            proximity = " ← **저항선 근접**"
        round_text = " | 라운드넘버 근접" if k["round_number_near"] else ""
        embed.add_field(
            name="🎯 키레벨",
            value=f"지지: {sup_text}\n저항: {res_text}{proximity}{round_text}",
            inline=True,
        )

        # 캔들
        patterns = []
        if c["bullish_engulfing"]:
            patterns.append("🟢상승장악형")
        if c["bearish_engulfing"]:
            patterns.append("🔴하락장악형")
        if c["bullish_pin_bar"]:
            patterns.append("🟢상승핀바")
        if c["bearish_pin_bar"]:
            patterns.append("🔴하락핀바")
        if c["inside_bar"]:
            patterns.append("⬜내포봉")
        embed.add_field(
            name="🕯️ 캔들패턴",
            value=(", ".join(patterns) if patterns else "패턴 없음") + f" (강도:{c['pattern_strength']:.2f})",
            inline=True,
        )

        # 풀백
        if p["is_pullback_to_ema"]:
            bounce = "바운스확인" if p["bounce_confirmed"] else "대기중"
            pb_text = f"EMA 터치 ({bounce}) | 깊이: {p['pullback_depth_pct']:.1f}%"
        else:
            pb_text = f"되돌림 없음 (고점 대비 {p['pullback_depth_pct']:.1f}%)"
        embed.add_field(name="↩️ EMA 풀백", value=pb_text, inline=True)

        # 신뢰도 점수
        bar_long = "█" * int(conf_long * 10) + "░" * (10 - int(conf_long * 10))
        bar_short = "█" * int(conf_short * 10) + "░" * (10 - int(conf_short * 10))
        embed.add_field(
            name="🎲 신뢰도 v2",
            value=f"LONG:  {bar_long} {conf_long:.0%}\nSHORT: {bar_short} {conf_short:.0%}",
            inline=False,
        )

        outlook_action, outlook_text = _build_outlook()
        embed.add_field(
            name="🧭 분석 전망",
            value=f"**판단**: {outlook_action}\n{outlook_text}",
            inline=False,
        )

        embed.set_footer(text="engine/analysis v2+ — 시장구조 · ADX · 거래량 · BB · 캔들 · 키레벨 · 풀백 · 전망")
        await interaction.followup.send(embed=embed)

    # -- /mtf ---------------------------------------------------------------

    @cmd_tree.command(name="mtf", description="특정 코인 멀티타임프레임 추세 분석")
    @app_commands.describe(symbol="종목 (예: BTC, ETH, SOL)")
    async def cmd_mtf(interaction: discord.Interaction, symbol: str):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import analyze_symbol_mtf

        ticker = f"KRW-{symbol.upper()}"
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: analyze_symbol_mtf(ticker))

        if result is None:
            await interaction.followup.send(f"`{ticker}` MTF 분석 실패 — 데이터 부족")
            return

        dominant = result.get("dominant", "N/A")
        boost = result.get("confidence_boost", 1.0)
        allows_long = result.get("allows_long", True)
        allows_short = result.get("allows_short", True)

        color_map = {"BULLISH": 0x26a69a, "BEARISH": 0xef5350, "NEUTRAL": 0x607D8B}
        embed = discord.Embed(
            title=f"MTF 추세 분석 — {symbol.upper()}/KRW",
            color=color_map.get(dominant, 0x607D8B),
        )
        embed.add_field(name="지배적 추세", value=dominant, inline=True)
        embed.add_field(name="신뢰도 배율", value=f"{boost:.1f}x", inline=True)
        embed.add_field(
            name="진입 허용",
            value=f"LONG: {'O' if allows_long else 'X'} | SHORT: {'O' if allows_short else 'X'}",
            inline=True,
        )

        for tf_key, tf_label in [("15m", "15분봉"), ("1h", "1시간봉")]:
            tf_data = result.get(tf_key)
            if tf_data:
                direction = tf_data.get("direction", "N/A")
                strength = tf_data.get("strength", 0)
                rsi = tf_data.get("rsi", 0)
                detail = tf_data.get("detail", "")
                embed.add_field(
                    name=f"{tf_label} ({direction})",
                    value=f"강도: {strength:.0%} | RSI: {rsi:.0f}\n{detail}",
                    inline=False,
                )
            else:
                embed.add_field(name=tf_label, value="데이터 없음", inline=False)

        await interaction.followup.send(embed=embed)

    # -- /add ---------------------------------------------------------------

    @cmd_tree.command(name="add", description="감시 종목 추가")
    @app_commands.describe(symbol="종목 (예: BTC, ETH)")
    async def cmd_add(interaction: discord.Interaction, symbol: str):
        from engine.strategy.upbit_scanner import get_config, update_config, UpbitScannerConfig

        ticker = f"KRW-{symbol.upper()}"

        # Validate ticker exists on Upbit
        import pyupbit
        try:
            all_tickers = pyupbit.get_tickers(fiat="KRW")
            if all_tickers and ticker not in all_tickers:
                await interaction.response.send_message(f"`{ticker}` — Upbit KRW 마켓에 존재하지 않습니다.")
                return
        except Exception:
            pass

        config = get_config() or UpbitScannerConfig.load()
        current_symbols = list(config.symbols) if config.symbols else []

        if ticker in current_symbols:
            sym_list = ", ".join(s.replace("KRW-", "") for s in current_symbols)
            await interaction.response.send_message(
                f"`{ticker}` 이미 수동 목록에 있습니다.\n"
                f"**수동 추가 ({len(current_symbols)}개)**: {sym_list}\n"
                f"자동(거래량 상위) + 수동 합산으로 스캔됩니다."
            )
            return

        new_syms = current_symbols + [ticker]
        update_config({"symbols": new_syms})

        sym_list = ", ".join(s.replace("KRW-", "") for s in new_syms)
        await interaction.response.send_message(
            f"`{ticker}` 수동 목록에 추가됨\n"
            f"**수동 추가 ({len(new_syms)}개)**: {sym_list}\n"
            f"자동(거래량 상위) + 수동 합산으로 스캔됩니다."
        )

    # -- /remove ------------------------------------------------------------

    @cmd_tree.command(name="remove", description="감시 종목 제거")
    @app_commands.describe(symbol="종목 (예: BTC, ETH)")
    async def cmd_remove(interaction: discord.Interaction, symbol: str):
        from engine.strategy.upbit_scanner import get_config, update_config, UpbitScannerConfig

        ticker = f"KRW-{symbol.upper()}"
        config = get_config() or UpbitScannerConfig.load()
        current_symbols = list(config.symbols) if config.symbols else []

        if not current_symbols:
            await interaction.response.send_message(
                "수동 목록이 비어있습니다.\n"
                "`/add`로 추가 감시 종목을 등록하세요.\n"
                "자동(거래량 상위)은 항상 스캔됩니다."
            )
            return

        if ticker not in current_symbols:
            sym_list = ", ".join(s.replace("KRW-", "") for s in current_symbols)
            await interaction.response.send_message(
                f"`{ticker}` 수동 목록에 없습니다.\n"
                f"**수동 추가 ({len(current_symbols)}개)**: {sym_list}"
            )
            return

        new_syms = [s for s in current_symbols if s != ticker]
        update_config({"symbols": new_syms})

        if new_syms:
            sym_list = ", ".join(s.replace("KRW-", "") for s in new_syms)
            await interaction.response.send_message(
                f"`{ticker}` 수동 목록에서 제거됨\n"
                f"**수동 추가 ({len(new_syms)}개)**: {sym_list}"
            )
        else:
            await interaction.response.send_message(
                f"`{ticker}` 제거됨 — 수동 목록이 비었습니다.\n"
                "자동(거래량 상위) 종목은 계속 스캔됩니다."
            )

    # -- /list --------------------------------------------------------------

    @cmd_tree.command(name="watchlist", description="현재 감시 종목 목록 확인")
    async def cmd_watchlist(interaction: discord.Interaction):
        from engine.strategy.upbit_scanner import get_config, UpbitScannerConfig, _get_active_symbols

        config = get_config() or UpbitScannerConfig.load()
        manual = list(config.symbols) if config.symbols else []

        loop = asyncio.get_event_loop()
        try:
            auto = await loop.run_in_executor(None, _get_active_symbols)
        except Exception:
            auto = []

        # 자동 목록
        lines = [f"**자동 (거래량 상위 {len(auto)}개)**"]
        auto_tickers = [s.replace("KRW-", "") for s in auto]
        if auto_tickers:
            lines.append(", ".join(auto_tickers))
        else:
            lines.append("(없음)")

        # 수동 추가 목록
        lines.append("")
        if manual:
            manual_tickers = [s.replace("KRW-", "") for s in manual]
            # 자동 목록과 중복인지 표시
            manual_lines = []
            for t, full in zip(manual_tickers, manual):
                overlap = " (자동 포함)" if full in auto else ""
                manual_lines.append(f"**{t}**{overlap}")
            lines.append(f"**수동 추가 ({len(manual)}개)**")
            lines.append(", ".join(manual_lines))
        else:
            lines.append("**수동 추가**: 없음")
            lines.append("`/add BTC` 등으로 추가 종목을 등록하세요")

        # 합산
        total = len(set(auto) | set(manual))
        embed = discord.Embed(
            title=f"감시 종목 (총 {total}개 = 자동 {len(auto)} + 수동 {len(manual)})",
            description="\n".join(lines),
            color=0x2196F3,
        )
        embed.set_footer(text="/add 종목추가 | /remove 수동목록에서 제거")
        await interaction.response.send_message(embed=embed)

    # -- /config ------------------------------------------------------------

    @cmd_tree.command(name="config", description="스캐너 설정 확인")
    async def cmd_config(interaction: discord.Interaction):
        from engine.strategy.upbit_scanner import get_config, UpbitScannerConfig

        cfg = get_config() or UpbitScannerConfig.load()

        embed = discord.Embed(title="스캐너 설정", color=0x9C27B0)
        embed.add_field(name="스캔 간격", value=f"{cfg.scan_interval_sec}초", inline=True)
        embed.add_field(name="EMA", value=f"{cfg.ema_fast}/{cfg.ema_slow}", inline=True)
        embed.add_field(name="거래량 배수", value=f"{cfg.vol_mult}x", inline=True)
        embed.add_field(name="쿨다운", value=f"{cfg.cooldown_sec}초", inline=True)
        embed.add_field(name="차트 전송", value="ON" if cfg.send_chart else "OFF", inline=True)
        sym_count = len(cfg.symbols) if cfg.symbols else "전체(자동)"
        embed.add_field(name="종목", value=str(sym_count), inline=True)

        toggles = [
            ("EMA+RSI+VWAP", cfg.enable_ema_rsi_vwap),
            ("Supertrend", cfg.enable_supertrend),
            ("MACD Div", cfg.enable_macd_div),
            ("StochRSI", cfg.enable_stoch_rsi),
            ("Fibonacci", cfg.enable_fibonacci),
            ("Ichimoku", cfg.enable_ichimoku),
            ("Early Pump", cfg.enable_early_pump),
            ("SMC", cfg.enable_smc),
            ("Hidden Div", cfg.enable_hidden_div),
            ("BB+RSI+Stoch", cfg.enable_bb_rsi_stoch),
        ]
        strat_text = "\n".join(f"{'ON' if on else 'OFF'} {name}" for name, on in toggles)
        embed.add_field(name="전략", value=strat_text, inline=False)

        embed.add_field(name="SL 모드", value=cfg.sl_mode, inline=True)
        embed.add_field(name="TP 모드", value=cfg.tp_mode, inline=True)

        # 사이클 필터 상태
        daily_status = "ON" if cfg.enable_daily_filter else "OFF"
        weekly_status = "ON" if cfg.enable_weekly_filter else "OFF"
        embed.add_field(
            name="사이클 필터",
            value=f"일봉필터: {daily_status} | 주봉필터: {weekly_status}",
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    # -- /set ---------------------------------------------------------------

    @cmd_tree.command(name="set", description="설정 변경 (예: interval 60, supertrend on)")
    @app_commands.describe(
        param="변경할 설정 (interval, vol, cooldown, chart, ema_rsi, supertrend, macd, ...)",
        value="새 값",
    )
    async def cmd_set(interaction: discord.Interaction, param: str, value: str):
        from engine.strategy.upbit_scanner import update_config

        _bool = lambda v: v.lower() in ("true", "on", "1", "yes")
        mapping = {
            "interval": ("scan_interval_sec", int),
            "sl": ("sl_pct", lambda v: float(v) / 100),
            "tp1": ("tp1_pct", lambda v: float(v) / 100),
            "tp2": ("tp2_pct", lambda v: float(v) / 100),
            "tp3": ("tp3_pct", lambda v: float(v) / 100),
            "vol": ("vol_mult", float),
            "cooldown": ("cooldown_sec", int),
            "chart": ("send_chart", _bool),
            "ema_fast": ("ema_fast", int),
            "ema_slow": ("ema_slow", int),
            "ema_rsi": ("enable_ema_rsi_vwap", _bool),
            "supertrend": ("enable_supertrend", _bool),
            "macd": ("enable_macd_div", _bool),
            "stochrsi": ("enable_stoch_rsi", _bool),
            "fibonacci": ("enable_fibonacci", _bool),
            "ichimoku": ("enable_ichimoku", _bool),
            "pump": ("enable_early_pump", _bool),
            "smc": ("enable_smc", _bool),
            "hidden_div": ("enable_hidden_div", _bool),
            "bb_rsi_stoch": ("enable_bb_rsi_stoch", _bool),
            "sl_mode": ("sl_mode", lambda v: v if v in ("atr", "structure", "hybrid") else "hybrid"),
            "tp_mode": ("tp_mode", lambda v: v if v in ("fixed", "staged") else "staged"),
            "mtf": ("enable_mtf", _bool),
            "daily_filter": ("enable_daily_filter", _bool),
            "weekly_filter": ("enable_weekly_filter", _bool),
            "websocket": ("ws_enabled", _bool),
            "parallel": ("parallel_fetch", _bool),
            # Timeframe toggles
            "tf_4h": ("enable_tf_4h", _bool),
            "tf_1h": ("enable_tf_1h", _bool),
            "tf_30m": ("enable_tf_30m", _bool),
            "tf_5m": ("enable_tf_5m", _bool),
            # Strategy indicator params
            "bb_period": ("bb_period", int),
            "bb_std": ("bb_std", float),
            "supertrend_period": ("supertrend_period", int),
            "supertrend_mult": ("supertrend_multiplier", float),
            "macd_fast": ("macd_fast", int),
            "macd_slow": ("macd_slow", int),
            "macd_signal": ("macd_signal", int),
            "stoch_period": ("stoch_period", int),
            "stoch_k": ("stoch_k", int),
            "stoch_d": ("stoch_d", int),
            "ichimoku_tenkan": ("ichimoku_tenkan", int),
            "ichimoku_kijun": ("ichimoku_kijun", int),
            "ichimoku_senkou": ("ichimoku_senkou", int),
            "adx_period": ("adx_period", int),
            "atr_period": ("atr_period", int),
            "rsi": ("rsi_period", int),
        }

        if param not in mapping:
            keys = ", ".join(mapping.keys())
            await interaction.response.send_message(f"알 수 없는 설정: `{param}`\n가능: {keys}")
            return

        key, converter = mapping[param]
        try:
            converted = converter(value)
            update_config({key: converted})
            await interaction.response.send_message(f"**{param}** → `{value}` 설정 완료")
        except Exception as e:
            await interaction.response.send_message(f"값 오류: {e}")

    # -- /help --------------------------------------------------------------

    @cmd_tree.command(name="help", description="사용 가능한 명령어 목록")
    async def cmd_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="Trading Bot v2 명령어",
            description=(
                "Upbit KRW 10전략 × 다중컨펌 필터 자동 스캐너\n"
                "**분석 엔진**: 시장구조 · ADX · 거래량(OBV/MFI) · BB · 캔들패턴 · 키레벨 · EMA풀백 · SMC\n"
                "**신뢰도 v2**: 추세정렬(30%) + 거래량(20%) + 기본신호(20%) + 키레벨(15%) + 캔들(15%)"
            ),
            color=0x2196F3,
        )

        embed.add_field(
            name="📊 분석 명령어",
            value=(
                "**/analyze BTC** — 다중컨펌 분석 (구조/ADX/거래량/BB/캔들/키레벨/풀백/신뢰도)\n"
                "**/coin BTC** — 분석 + 10전략 시그널 스캔 (차트 포함)\n"
                "**/mtf BTC** — 15분/1시간/일봉/주봉 멀티타임프레임 추세\n"
                "**/scan** — 전 종목 × 전 전략 즉시 스캔 (다중컨펌)\n"
                "**/backtest BTC** — 전체 10전략 30일 백테스트\n"
                "**/backtest BTC smc 60** — SMC 전략 60일 백테스트\n"
                "**/optimize BTC smc** — SMC 전략 파라미터 최적화\n"
                "**/reoptimize BTC** — 전 전략 자동 재최적화 + config 적용"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚙️ 스캐너 제어",
            value=(
                "**/start** — 스캐너 시작 (WS 이벤트 드리븐)\n"
                "**/stop** — 스캐너 정지\n"
                "**/status** — 봇 상태 (모드, WS, 캐시)\n"
                "**/config** — 현재 설정 + 전략 토글 확인"
            ),
            inline=False,
        )

        embed.add_field(
            name="📋 종목 관리",
            value=(
                "**/watchlist** — 현재 감시 종목 목록 확인\n"
                "**/add SOL** — 감시 종목 추가 (Upbit 존재 검증)\n"
                "**/remove DOGE** — 감시 종목 제거\n"
                "목록이 비면 자동 스캔 모드 (거래량 상위 자동선별)"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 설정 변경 (`/set key value`)",
            value=(
                "**전략 토글**: `ema_rsi` `supertrend` `macd` `stochrsi` `fibonacci` `ichimoku` `pump` `smc` `hidden_div` `bb_rsi_stoch`\n"
                "**SL/TP 모드**: `sl_mode` (atr/structure/hybrid) `tp_mode` (fixed/staged)\n"
                "**시스템**: `mtf` (멀티TF) `websocket` (WS모드) `parallel` (병렬fetch)\n"
                "**매개변수**: `interval` (스캔간격) `vol` (거래량배수) `cooldown` (쿨다운) `chart` (차트전송)"
            ),
            inline=False,
        )

        embed.add_field(
            name="🕐 스윙 스캐너 (`/swing ...`)",
            value=(
                "**/swing start** — 스윙 스캐너 시작 (1시간봉, 6전략)\n"
                "**/swing stop** — 스윙 스캐너 정지\n"
                "**/swing status** — 스윙 스캐너 상태\n"
                "**/swing config** — 스윙 설정 확인\n"
                "**/swing scan** — 전 종목 즉시 스윙 스캔\n"
                "**/swing set key value** — 스윙 설정 변경\n"
                "전략: EMA Cross · Ichimoku · Supertrend · MACD Div · SMC · BB Squeeze"
            ),
            inline=False,
        )

        embed.add_field(
            name="📈 v2 전략 업그레이드",
            value=(
                "**EMA** → EMA 되돌림 + 3봉 추세확립 + ADX/OBV 컨펌\n"
                "**Supertrend** → ADX>18 + 시장구조 + OBV 일치\n"
                "**MACD** → 키레벨에서만 + 매도소진 + 캔들확인\n"
                "**StochRSI** → 지지/저항 필수 + BB스퀴즈/%B\n"
                "**Fibonacci** → 골든존 + BULLISH구조 + EMA21근접\n"
                "**Ichimoku** → 5요소 완전체 (치코+미래구름)\n"
                "**EarlyPump** → BOS돌파 + OBV + MFI + 몸통비율\n"
                "**SMC** → CHoCH/BOS + OB리테스트 + FVG + ADX\n"
                "**Hidden Div** → 가격HL+RSI LL (추세연속) + OBV\n"
                "**BB+RSI+Stoch** → 3중과매도/과매수 + 반전캔들"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎯 SL/TP 고도화",
            value=(
                "**SL 모드**: `atr` (ATR배수) | `structure` (지지/저항) | `hybrid` (둘 중 타이트한 것)\n"
                "**TP 모드**: `fixed` (고정배수) | `staged` (시장상태별 — 추세↑넓게, 횡보↓좁게)"
            ),
            inline=False,
        )

        embed.set_footer(text="engine/analysis v3 — 10전략 + 고도화 SL/TP + 사이클 필터 시스템")
        await interaction.response.send_message(embed=embed)

    # -- /backtest --------------------------------------------------------------

    @cmd_tree.command(name="backtest", description="스캐너 전략 백테스트 (예: /backtest BTC smc 60)")
    @app_commands.describe(
        symbol="코인 심볼 (예: BTC, ETH)",
        strategy="전략 이름 (비워두면 전체), 예: smc, ema, macd ...",
        days="백테스트 기간 (일, 기본 30)",
    )
    async def cmd_backtest(
        interaction: discord.Interaction,
        symbol: str,
        strategy: str = "",
        days: int = 30,
    ):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import (
            scan_ema_rsi_vwap, scan_supertrend, scan_macd_divergence,
            scan_stoch_rsi, scan_fibonacci, scan_ichimoku, scan_early_pump,
            scan_smc, scan_hidden_divergence, scan_bb_rsi_stoch,
            get_cache_manager, UpbitScannerConfig,
        )
        from engine.backtest.scanner_backtest import ScannerBacktester, ScannerBacktestConfig

        cache = get_cache_manager()
        if not cache:
            from engine.data.upbit_cache import OHLCVCacheManager
            cache = OHLCVCacheManager()

        ticker = symbol.upper()
        if not ticker.startswith("KRW-"):
            ticker = f"KRW-{ticker}"

        all_strategies = {
            "ema": ("EMA+RSI+VWAP", scan_ema_rsi_vwap),
            "supertrend": ("Supertrend", scan_supertrend),
            "macd": ("MACD Divergence", scan_macd_divergence),
            "stochrsi": ("StochRSI", scan_stoch_rsi),
            "fibonacci": ("Fibonacci", scan_fibonacci),
            "ichimoku": ("Ichimoku", scan_ichimoku),
            "pump": ("Early Pump", scan_early_pump),
            "smc": ("SMC", scan_smc),
            "hidden_div": ("Hidden Div", scan_hidden_divergence),
            "bb_rsi_stoch": ("BB+RSI+Stoch", scan_bb_rsi_stoch),
        }

        if strategy:
            key = strategy.lower().replace(" ", "_").replace("+", "_")
            match = all_strategies.get(key)
            if not match:
                await interaction.followup.send(
                    f"알 수 없는 전략: `{strategy}`\n가능: {', '.join(all_strategies.keys())}"
                )
                return
            run_list = [match]
        else:
            run_list = list(all_strategies.values())

        backtester = ScannerBacktester(cache)
        results = []

        for name, fn in run_list:
            config = ScannerBacktestConfig(
                strategy_fn=fn,
                strategy_name=name,
                symbol=ticker,
                days=days,
            )
            try:
                report = await backtester.run(config)
                results.append(report)
            except Exception as e:
                logger.warning("Backtest error %s: %s", name, e)

        if not results:
            await interaction.followup.send("백테스트 결과 없음 (데이터 부족)")
            return

        embed = discord.Embed(
            title=f"백테스트 결과 — {ticker} ({days}일)",
            color=0x4CAF50,
        )

        for r in results:
            pf = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "∞"
            sharpe_str = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio else "N/A"
            val = (
                f"거래: {r.total_trades} | 승률: {r.win_rate:.1%} | PF: {pf}\n"
                f"수익: {r.total_return_pct:+.2f}% | MDD: {r.max_drawdown_pct:.1f}% | Sharpe: {sharpe_str}"
            )
            embed.add_field(name=r.strategy_name, value=val, inline=False)

        embed.set_footer(text=f"기간: {results[0].period if results else 'N/A'}")
        await interaction.followup.send(embed=embed)

    # -- /optimize --------------------------------------------------------------

    @cmd_tree.command(name="optimize", description="전략 파라미터 최적화 (예: /optimize BTC smc)")
    @app_commands.describe(
        symbol="코인 심볼 (예: BTC, ETH)",
        strategy="전략 이름 (예: smc, ema, macd ...)",
        days="최적화 기간 (일, 기본 30)",
    )
    async def cmd_optimize(
        interaction: discord.Interaction,
        symbol: str,
        strategy: str,
        days: int = 30,
    ):
        await interaction.response.defer(thinking=True)

        from engine.strategy.upbit_scanner import (
            scan_ema_rsi_vwap, scan_supertrend, scan_macd_divergence,
            scan_stoch_rsi, scan_fibonacci, scan_ichimoku, scan_early_pump,
            scan_smc, scan_hidden_divergence, scan_bb_rsi_stoch,
            get_cache_manager,
        )
        from engine.backtest.scanner_backtest import ScannerBacktester
        from engine.backtest.scanner_optimizer import ScannerOptimizer, DEFAULT_PARAM_RANGES

        cache = get_cache_manager()
        if not cache:
            from engine.data.upbit_cache import OHLCVCacheManager
            cache = OHLCVCacheManager()

        ticker = symbol.upper()
        if not ticker.startswith("KRW-"):
            ticker = f"KRW-{ticker}"

        all_strategies = {
            "ema": ("EMA+RSI+VWAP", scan_ema_rsi_vwap),
            "supertrend": ("Supertrend", scan_supertrend),
            "macd": ("MACD Divergence", scan_macd_divergence),
            "stochrsi": ("StochRSI", scan_stoch_rsi),
            "fibonacci": ("Fibonacci", scan_fibonacci),
            "ichimoku": ("Ichimoku", scan_ichimoku),
            "pump": ("Early Pump", scan_early_pump),
            "smc": ("SMC", scan_smc),
            "hidden_div": ("Hidden Div", scan_hidden_divergence),
            "bb_rsi_stoch": ("BB+RSI+Stoch", scan_bb_rsi_stoch),
        }

        key = strategy.lower().replace(" ", "_").replace("+", "_")
        match = all_strategies.get(key)
        if not match:
            await interaction.followup.send(
                f"알 수 없는 전략: `{strategy}`\n가능: {', '.join(all_strategies.keys())}"
            )
            return

        strat_name, strat_fn = match

        # 파라미터 범위 조회
        param_ranges = DEFAULT_PARAM_RANGES.get(strat_name, [])
        if not param_ranges:
            await interaction.followup.send(f"`{strat_name}` 전략의 파라미터 범위가 정의되지 않았습니다.")
            return

        backtester = ScannerBacktester(cache)
        optimizer = ScannerOptimizer(backtester)

        try:
            result = await optimizer.grid_search(
                strategy_fn=strat_fn,
                strategy_name=strat_name,
                symbol=ticker,
                param_ranges=param_ranges,
                days=days,
            )
        except Exception as e:
            await interaction.followup.send(f"최적화 오류: {e}")
            return

        if not result.best_params:
            await interaction.followup.send("최적화 결과 없음 (유효한 조합 없음)")
            return

        embed = discord.Embed(
            title=f"파라미터 최적화 — {strat_name} | {ticker}",
            color=0xFF9800,
        )

        # 최적 파라미터
        params_str = "\n".join(f"  {k}: {v}" for k, v in result.best_params.items())
        embed.add_field(name="최적 파라미터", value=f"```\n{params_str}\n```", inline=False)

        # Train 성능
        pf = f"{result.best_profit_factor:.2f}" if result.best_profit_factor != float("inf") else "∞"
        embed.add_field(
            name="Train 성능",
            value=f"Sharpe: {result.best_sharpe:.2f} | 승률: {result.best_win_rate:.1%} | PF: {pf}",
            inline=False,
        )

        # Test 성능 (과적합 확인)
        if result.test_sharpe is not None:
            test_pf = f"{result.test_profit_factor:.2f}" if result.test_profit_factor and result.test_profit_factor != float("inf") else "N/A"
            embed.add_field(
                name="Test 성능 (검증)",
                value=f"Sharpe: {result.test_sharpe:.2f} | 승률: {result.test_win_rate:.1%} | PF: {test_pf}",
                inline=False,
            )

        embed.add_field(
            name="탐색",
            value=f"{len(result.grid_results)}개 조합 탐색 ({days}일, train 70% / test 30%)",
            inline=False,
        )

        # Top 3 조합
        if len(result.grid_results) >= 2:
            top3_lines = []
            for i, r in enumerate(result.grid_results[:3], 1):
                s = r.get("sharpe")
                wr = r.get("win_rate", 0)
                sharpe_str = f"{s:.2f}" if s else "N/A"
                top3_lines.append(f"{i}. {r['params']} — Sharpe: {sharpe_str}, WR: {wr:.1%}")
            embed.add_field(name="Top 3", value="\n".join(top3_lines), inline=False)

        await interaction.followup.send(embed=embed)

    # -- /reoptimize ------------------------------------------------------------

    @cmd_tree.command(name="reoptimize", description="전략 파라미터 자동 재최적화 (예: /reoptimize BTC 30)")
    @app_commands.describe(
        symbol="코인 심볼 (예: BTC, ETH). 비워두면 BTC/ETH/XRP 전체",
        days="최적화 기간 (일, 기본 30)",
    )
    async def cmd_reoptimize(
        interaction: discord.Interaction,
        symbol: str = "",
        days: int = 30,
    ):
        await interaction.response.defer(thinking=True)

        from engine.backtest.auto_reoptimize import reoptimize_symbol

        if symbol:
            ticker = symbol.upper()
            if not ticker.startswith("KRW-"):
                ticker = f"KRW-{ticker}"
            symbols = [ticker]
        else:
            symbols = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]

        all_results = {}
        for sym in symbols:
            try:
                results = await reoptimize_symbol(sym, days=days, apply_to_config=True)
                all_results[sym] = results
            except Exception as e:
                logger.warning("Reoptimize error %s: %s", sym, e)

        if not all_results:
            await interaction.followup.send("재최적화 결과 없음")
            return

        embed = discord.Embed(
            title=f"재최적화 완료 ({days}일 기반)",
            color=0xFF5722,
        )

        for sym, strats in all_results.items():
            if not strats:
                continue
            lines = []
            for name, data in strats.items():
                params_short = ", ".join(f"{k}={v}" for k, v in data["params"].items())
                sharpe = data.get("train_sharpe", 0)
                wr = data.get("train_win_rate", 0)
                lines.append(f"**{name}**: {params_short}\n  Sharpe={sharpe:.2f} WR={wr:.1%}")

            ticker_short = sym.replace("KRW-", "")
            embed.add_field(
                name=f"{ticker_short} ({len(strats)}전략)",
                value="\n".join(lines[:5]) if lines else "N/A",
                inline=False,
            )

        embed.set_footer(text="최적 파라미터가 config에 자동 적용되었습니다")
        await interaction.followup.send(embed=embed)

    # ===================================================================
    # Swing Scanner Commands
    # ===================================================================

    swing_group = app_commands.Group(name="swing", description="스윙 트레이딩 스캐너 (1시간봉)")

    @swing_group.command(name="start", description="스윙 스캐너 시작 (1시간봉, 6전략)")
    async def swing_start(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            from engine.strategy.swing_scanner import start, status, is_running, SwingScannerConfig
            from engine.strategy.swing_scanner import _build_swing_strategy_list

            if is_running():
                s = status()
                await interaction.followup.send(
                    f"스윙 스캐너 이미 실행 중입니다.\n"
                    f"스캔 #{s['scan_count']} | {s['symbols_count']}종목 | 간격 {s['scan_interval_sec']}초"
                )
                return

            start()
            s = status()
            cfg = SwingScannerConfig.load()
            strats = _build_swing_strategy_list(cfg)
            names = ", ".join(n for n, _ in strats)
            await interaction.followup.send(
                f"**스윙 스캐너 시작됨** (1시간봉)\n"
                f"전략: {names}\n"
                f"종목: KRW 전체 (거래량 상위 자동 선별)\n"
                f"간격: {s['scan_interval_sec']}초 | Discord 채널: `{cfg.discord_channel}`"
            )
        except Exception as e:
            logger.exception("swing start error")
            await interaction.followup.send(f"스윙 시작 오류: {e}")

    @swing_group.command(name="stop", description="스윙 스캐너 정지")
    async def swing_stop(interaction: discord.Interaction):
        try:
            from engine.strategy.swing_scanner import stop, is_running

            if not is_running():
                await interaction.response.send_message("스윙 스캐너가 실행 중이 아닙니다.")
                return

            stop()
            await interaction.response.send_message("**스윙 스캐너 정지됨**")
        except Exception as e:
            logger.exception("swing stop error")
            await interaction.response.send_message(f"스윙 정지 오류: {e}")

    @swing_group.command(name="status", description="스윙 스캐너 상태 확인")
    async def swing_status(interaction: discord.Interaction):
        try:
            from engine.strategy.swing_scanner import status

            s = status()
            running = "Running" if s["running"] else "Stopped"

            embed = discord.Embed(
                title=f"Swing Scanner {running}",
                description="1시간봉 기반 중기 스윙 트레이딩 (EMA 20/50)",
                color=0x26a69a if s["running"] else 0xef5350,
            )
            embed.add_field(name="스캔 횟수", value=str(s["scan_count"]), inline=True)
            embed.add_field(name="감시 종목", value=f"{s['symbols_count']}개", inline=True)
            embed.add_field(name="최근 알림", value=f"{s['recent_alerts']}건", inline=True)
            embed.add_field(name="간격", value=f"{s['scan_interval_sec']}초", inline=True)
            embed.add_field(name="MTF 필터", value="ON" if s.get("enable_mtf") else "OFF", inline=True)
            embed.add_field(name="Discord 채널", value=s.get("discord_channel", "swing"), inline=True)

            if s.get("last_scan"):
                embed.add_field(name="마지막 스캔", value=s["last_scan"], inline=False)

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.exception("swing status error")
            await interaction.response.send_message(f"스윙 상태 오류: {e}")

    @swing_group.command(name="config", description="스윙 스캐너 설정 확인")
    async def swing_config(interaction: discord.Interaction):
        try:
            from engine.strategy.swing_scanner import get_config, SwingScannerConfig
            from engine.strategy.swing_scanner import _build_swing_strategy_list

            cfg = get_config() or SwingScannerConfig.load()
            strats = _build_swing_strategy_list(cfg)
            strat_status = []
            toggle_map = {
                "EMA Cross": cfg.enable_ema_cross,
                "Ichimoku": cfg.enable_ichimoku,
                "Supertrend": cfg.enable_supertrend,
                "MACD Div": cfg.enable_macd_div,
                "SMC": cfg.enable_smc,
                "BB Squeeze": cfg.enable_bb_squeeze,
            }
            for name, enabled in toggle_map.items():
                strat_status.append(f"{'ON' if enabled else 'OFF'} {name}")

            embed = discord.Embed(
                title="Swing Scanner Config",
                color=0x2196F3,
            )
            embed.add_field(
                name="지표 파라미터",
                value=(
                    f"EMA: {cfg.ema_fast}/{cfg.ema_slow} | RSI: {cfg.rsi_period}\n"
                    f"BB: {cfg.bb_period}/{cfg.bb_std} | Supertrend: {cfg.supertrend_period}/{cfg.supertrend_multiplier}\n"
                    f"ADX: {cfg.adx_period} | ATR: {cfg.atr_period}"
                ),
                inline=False,
            )
            embed.add_field(
                name="SL/TP",
                value=(
                    f"SL: ATR x{cfg.sl_atr_mult} ({cfg.sl_mode})\n"
                    f"TP: x{cfg.tp1_atr_mult} / x{cfg.tp2_atr_mult} / x{cfg.tp3_atr_mult} ({cfg.tp_mode})"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"전략 ({len(strats)}개 활성)",
                value="\n".join(strat_status),
                inline=False,
            )
            embed.add_field(
                name="시스템",
                value=(
                    f"간격: {cfg.scan_interval_sec}초 | 쿨다운: {cfg.cooldown_sec}초\n"
                    f"MTF: {'ON' if cfg.enable_mtf else 'OFF'} | 차트: {'ON' if cfg.send_chart else 'OFF'}\n"
                    f"Discord: `{cfg.discord_channel}` | 레버리지: {cfg.leverage}x"
                ),
                inline=False,
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.exception("swing config error")
            await interaction.response.send_message(f"스윙 설정 오류: {e}")

    @swing_group.command(name="scan", description="스윙 전 종목 즉시 스캔 (1시간봉, 6전략)")
    async def swing_scan(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            from engine.strategy.swing_scanner import (
                SwingScannerConfig, _build_swing_strategy_list,
                _ensure_deps,
            )

            try:
                _ensure_deps()
            except ImportError as e:
                await interaction.followup.send(f"의존성 오류: {e}")
                return

            from engine.strategy.swing_scanner import (
                SwingSignalDedup, generate_swing_chart, get_config,
            )
            from engine.strategy.upbit_scanner import (
                fetch_upbit_ohlcv, _get_active_symbols,
                send_upbit_alert, validate_signal_rr,
            )
            from engine.analysis import build_context

            cfg = get_config() or SwingScannerConfig.load()
            strategies = _build_swing_strategy_list(cfg)
            dedup = SwingSignalDedup()
            loop = asyncio.get_event_loop()

            auto_syms = await loop.run_in_executor(None, _get_active_symbols)
            manual_syms = list(cfg.symbols) if cfg.symbols else []
            seen = set(auto_syms)
            symbols = list(auto_syms)
            for s in manual_syms:
                if s not in seen:
                    symbols.append(s)
                    seen.add(s)

            found = []
            errors = 0
            for sym in symbols:
                try:
                    df = await loop.run_in_executor(None, fetch_upbit_ohlcv, sym, "1h", 200)
                    if df is None or len(df) < 60:
                        continue

                    ctx = build_context(df)

                    for strat_name, strat_fn in strategies:
                        try:
                            sig = strat_fn(df, sym, cfg, context=ctx)
                            if sig is None:
                                continue
                            if not validate_signal_rr(sig):
                                continue
                            if not dedup.is_new(sig):
                                continue

                            found.append((sym, strat_name, sig))
                            dedup.mark_sent(sig)

                            # Send alert to swing channel
                            chart_path = generate_swing_chart(df, sig, cfg)
                            await loop.run_in_executor(
                                None, send_upbit_alert, sig, chart_path, cfg.discord_channel,
                            )
                        except Exception:
                            pass
                except Exception:
                    errors += 1

            embed = discord.Embed(
                title=f"스윙 스캔 완료 — {len(symbols)}종목 × {len(strategies)}전략",
                color=0x4CAF50 if found else 0x9E9E9E,
            )

            if found:
                for sym, strat_name, sig in found[:10]:
                    ticker = sym.replace("KRW-", "")
                    embed.add_field(
                        name=f"{ticker} — {strat_name}",
                        value=(
                            f"{sig.side} | 진입: {sig.entry:,.0f}\n"
                            f"SL: {sig.stop_loss:,.0f} | TP: {', '.join(f'{t:,.0f}' for t in sig.take_profits)}\n"
                            f"신뢰도: {sig.confidence:.0%} | TF: {sig.timeframe}"
                        ),
                        inline=False,
                    )
                if len(found) > 10:
                    embed.set_footer(text=f"외 {len(found) - 10}건 (swing 채널에서 확인)")
            else:
                embed.description = "현재 조건 충족 시그널 없음"

            if errors:
                embed.add_field(name="오류", value=f"{errors}종목 데이터 실패", inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.exception("swing scan error")
            await interaction.followup.send(f"스윙 스캔 오류: {e}")

    @swing_group.command(name="set", description="스윙 스캐너 설정 변경 (예: /swing set ema_cross off)")
    @app_commands.describe(
        param="설정 키 (ema_cross, ichimoku, supertrend, macd, smc, bb_squeeze, mtf, chart, interval, cooldown)",
        value="설정 값 (on/off, 숫자)",
    )
    async def swing_set(interaction: discord.Interaction, param: str, value: str):
        from engine.strategy.swing_scanner import update_config, get_config, SwingScannerConfig

        key = param.lower().strip()
        val = value.lower().strip()

        toggle_keys = {
            "ema_cross": "enable_ema_cross",
            "ichimoku": "enable_ichimoku",
            "supertrend": "enable_supertrend",
            "macd": "enable_macd_div",
            "smc": "enable_smc",
            "bb_squeeze": "enable_bb_squeeze",
            "mtf": "enable_mtf",
            "chart": "send_chart",
        }

        int_keys = {
            "interval": "scan_interval_sec",
            "cooldown": "cooldown_sec",
        }

        try:
            if key in toggle_keys:
                bool_val = val in ("on", "true", "1", "yes")
                cfg = update_config({toggle_keys[key]: bool_val})
                state = "ON" if bool_val else "OFF"
                await interaction.response.send_message(f"스윙 `{key}` → **{state}**")
            elif key in int_keys:
                int_val = int(val)
                cfg = update_config({int_keys[key]: int_val})
                await interaction.response.send_message(f"스윙 `{key}` → **{int_val}**")
            else:
                available = ", ".join(list(toggle_keys.keys()) + list(int_keys.keys()))
                await interaction.response.send_message(f"알 수 없는 키: `{key}`\n가능: {available}")
        except Exception as e:
            await interaction.response.send_message(f"설정 오류: {e}")

    cmd_tree.add_command(swing_group)

    _bot = client
    return client


# ---------------------------------------------------------------------------
# Run / Stop
# ---------------------------------------------------------------------------

def run_bot_background() -> bool:
    """Start the bot in a background thread. Creates a fresh client each time."""
    global _bot, _bot_thread, _bot_running

    if _bot_running:
        return True

    token = _load_token()
    if not token:
        logger.error("Bot token not configured")
        return False

    # Always create a fresh client (avoids stale aiohttp session after stop)
    client = _create_bot()

    def _run():
        global _bot_running
        _bot_running = True
        try:
            asyncio.run(client.start(token))
        except Exception as e:
            logger.error("Discord bot error: %s", e)
        finally:
            _bot_running = False

    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()
    logger.info("Discord bot starting in thread")
    return True


def stop_bot() -> bool:
    """Stop the Discord bot."""
    global _bot, _bot_running

    if not _bot_running or _bot is None:
        _bot_running = False
        return True

    _bot_running = False

    # Schedule close on the bot's own event loop
    try:
        if _bot.loop and _bot.loop.is_running():
            asyncio.run_coroutine_threadsafe(_bot.close(), _bot.loop)
    except Exception as e:
        logger.warning("Error closing bot: %s", e)

    return True
