"""디스코드 스캐너 커맨드 — 자동/수동 패턴 분석 제어.

슬래시 커맨드:
  /스캔 [심볼]  — 수동 분석 (단일 또는 전체)
  /자동시작      — 자동 스캐너 시작
  /자동중지      — 자동 스캐너 중지
  /스캐너       — 스캐너 상태 조회
  /순위         — Upbit 거래대금 상위 20개
  /설정         — 스캐너 설정 변경
"""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import Interaction, app_commands

from engine.interfaces.discord.context import DiscordBotContext

logger = logging.getLogger(__name__)

class ScannerCommandPlugin:
    name = "scanner"

    def register(self, tree: app_commands.CommandTree, context: DiscordBotContext) -> None:

        @tree.command(name="스캔", description="수동 패턴 분석 (심볼 지정 또는 전체 상위 20개)")
        @app_commands.describe(symbol="분석할 심볼 (예: BTC, DOGE) — 미입력 시 상위 20개 전체")
        async def scan_manual(interaction: Interaction, symbol: str = "") -> None:
            await interaction.response.defer(thinking=True)

            from engine.strategy.pattern_alert import (
                PatternAlertConfig,
                analyze_single,
                generate_chart_for_symbol,
            )

            config = PatternAlertConfig.load()

            if symbol.strip():
                # 단일 심볼 분석
                sym = _normalize_symbol(symbol.strip())
                results, message, krw_rate = await asyncio.to_thread(
                    analyze_single, sym, config,
                )

                files = []
                if results:
                    chart_bytes = await asyncio.to_thread(
                        generate_chart_for_symbol, sym, results, krw_rate,
                    )
                    if chart_bytes:
                        files.append(discord.File(io.BytesIO(chart_bytes), filename="analysis.png"))

                # 2000자 제한 분할
                for chunk in _split_message(message):
                    await interaction.followup.send(content=chunk, files=files if files else [])
                    files = []  # 첫 메시지에만 파일 첨부
            else:
                # 전체 상위 20개 스캔
                from engine.data.upbit_ranking import get_top_symbols, format_ranking_table

                symbols = await asyncio.to_thread(get_top_symbols, config.ranking_count)
                await interaction.followup.send(
                    content=f"상위 {len(symbols)}개 스캔 시작... (완료 시 알림 발송)",
                )

                from engine.strategy.pattern_alert import scan_now
                sent = await asyncio.to_thread(scan_now, config)

                summary = f"스캔 완료: {len(symbols)}개 분석, {len(sent)}개 알림 발송"
                if sent:
                    details = "\n".join(
                        f"  • {s['symbol']} → {s['direction']} ({', '.join(s['patterns']) or '방향합의'})"
                        for s in sent
                    )
                    summary += f"\n```\n{details}\n```"
                await interaction.followup.send(content=summary)

        @tree.command(name="자동시작", description="자동 패턴 스캐너 시작 (30초 주기)")
        async def auto_start(interaction: Interaction) -> None:
            await interaction.response.defer(thinking=True)

            from engine.strategy.pattern_alert import start, status, PatternAlertConfig

            st = status()
            if st["running"]:
                await interaction.followup.send("이미 실행 중입니다.")
                return

            config = PatternAlertConfig.load()
            config.use_upbit_ranking = True
            config.save()

            await asyncio.to_thread(start, config)

            st = status()
            symbols_info = f"Upbit 거래대금 상위 {config.ranking_count}개"
            await interaction.followup.send(
                f"자동 스캐너 시작\n"
                f"• 대상: {symbols_info}\n"
                f"• 주기: {config.scan_interval_sec}초\n"
                f"• TF: {', '.join(config.timeframes)}\n"
                f"• 쿨다운: {config.cooldown_sec // 3600}시간"
            )

        @tree.command(name="자동중지", description="자동 패턴 스캐너 중지")
        async def auto_stop(interaction: Interaction) -> None:
            from engine.strategy.pattern_alert import stop, status

            st = status()
            if not st["running"]:
                await interaction.response.send_message("실행 중이 아닙니다.")
                return

            await asyncio.to_thread(stop)
            await interaction.response.send_message(
                f"자동 스캐너 중지 (총 {st['scan_count']}회 스캔)"
            )

        @tree.command(name="스캐너", description="스캐너 상태 조회")
        async def scanner_status(interaction: Interaction) -> None:
            from engine.strategy.pattern_alert import status, PatternAlertConfig

            st = status()
            config = PatternAlertConfig.load()

            state = "실행 중" if st["running"] else "중지"
            symbols_info = (
                f"Upbit 상위 {config.ranking_count}개"
                if config.use_upbit_ranking
                else f"{len(config.symbols)}개 고정"
            )

            msg = (
                f"**패턴 스캐너 상태**\n"
                f"• 상태: {state}\n"
                f"• 스캔 횟수: {st['scan_count']}\n"
                f"• 마지막 스캔: {st['last_scan_at'] or 'N/A'}\n"
                f"• 대상: {symbols_info}\n"
                f"• 주기: {config.scan_interval_sec}초\n"
                f"• TF: {', '.join(config.timeframes)}\n"
                f"• 쿨다운: {config.cooldown_sec // 3600}시간"
            )
            await interaction.response.send_message(msg)

        @tree.command(name="순위", description="Upbit 거래대금 상위 20개 조회")
        @app_commands.describe(count="조회 개수 (기본 20)")
        async def ranking(interaction: Interaction, count: int = 20) -> None:
            await interaction.response.defer(thinking=True)
            from engine.data.upbit_ranking import format_ranking_table
            table = await asyncio.to_thread(format_ranking_table, min(count, 50))
            await interaction.followup.send(content=table)

        @tree.command(name="패턴", description="패턴·용어 설명 (예: /패턴 장악형, /패턴 정배열)")
        @app_commands.describe(검색="패턴 또는 용어 이름 (미입력 시 전체 목록)")
        async def pattern_help(interaction: Interaction, 검색: str = "") -> None:
            query = 검색.strip()

            if not query:
                # 전체 목록
                lines = ["**📖 패턴 사전**", ""]
                lines.append("__구조적 패턴 (전략 신호 생성)__")
                for name in list(_PATTERN_HELP.keys())[:4]:
                    lines.append(f"• **{name}**")
                lines.append("")
                lines.append("__캔들 패턴 (보조 시그널)__")
                for name in list(_PATTERN_HELP.keys())[4:]:
                    short = name.split("(")[0].strip()
                    lines.append(f"• {short}")
                lines.append("")
                lines.append("__용어__")
                for term in _TERM_HELP:
                    lines.append(f"• {term}")
                lines.append("")
                lines.append("> `/패턴 장악형` 으로 상세 설명 조회")
                await interaction.response.send_message("\n".join(lines))
                return

            # 검색
            found = []
            for name, desc in {**_PATTERN_HELP, **_TERM_HELP}.items():
                if query in name:
                    found.append((name, desc))

            if not found:
                await interaction.response.send_message(f"`{query}` 관련 항목을 찾을 수 없습니다.")
                return

            lines = []
            for name, desc in found:
                lines.append(f"**{name}**")
                lines.append(f"> {desc}")
                lines.append("")

            await interaction.response.send_message("\n".join(lines))

        @tree.command(name="설정", description="스캐너 설정 변경")
        @app_commands.describe(
            주기="스캔 주기 (초, 예: 30)",
            개수="Upbit 상위 N개 (예: 20)",
            쿨다운="동일 신호 재발송 방지 (초, 예: 14400)",
            차트="차트 첨부 여부 (true/false)",
        )
        async def config_cmd(
            interaction: Interaction,
            주기: int | None = None,
            개수: int | None = None,
            쿨다운: int | None = None,
            차트: str | None = None,
        ) -> None:
            from engine.strategy.pattern_alert import update_config

            kwargs = {}
            if 주기 is not None:
                kwargs["scan_interval_sec"] = max(10, 주기)
            if 개수 is not None:
                kwargs["ranking_count"] = max(5, min(50, 개수))
                kwargs["use_upbit_ranking"] = True
            if 쿨다운 is not None:
                kwargs["cooldown_sec"] = max(60, 쿨다운)
            if 차트 is not None:
                kwargs["send_chart"] = 차트.lower() in ("true", "1", "yes", "on")

            if not kwargs:
                await interaction.response.send_message("변경할 설정을 지정하세요.")
                return

            cfg = update_config(**kwargs)
            changes = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            await interaction.response.send_message(f"설정 변경: {changes}")

_PATTERN_HELP = {
    # 구조적 패턴 (우리 전략)
    "쌍바닥 (Double Bottom)": "저점 2개가 유사 → 넥라인 돌파 시 LONG. 상승 반전 신호.",
    "쌍봉 (Double Top)": "고점 2개가 유사 → 넥라인 이탈 시 SHORT. 하락 반전 신호.",
    "상승삼각형 (Asc Triangle)": "수평 저항 + 상승 지지선 → 상방 돌파 시 LONG.",
    "하강삼각형 (Desc Triangle)": "수평 지지 + 하강 저항선 → 하방 이탈 시 SHORT.",
    "눌림목 (Pullback)": "추세 중 EMA21까지 되돌림 → 반전 캔들 확인 후 재진입. 승률 54%, R:R 1:1.5+.",
    # 캔들 패턴 (TA-Lib)
    "장악형 (Engulfing)": "이전 봉을 완전히 감싸는 봉. ▲BULL=상승반전, ▼BEAR=하락반전. 신뢰도 높음.",
    "망치형 (Hammer)": "긴 아래꼬리 + 짧은 몸통. 하락 후 나오면 상승 반전. 지지대에서 유효.",
    "유성형 (Shooting Star)": "긴 위꼬리 + 짧은 몸통. 상승 후 나오면 하락 반전. 저항대에서 유효.",
    "샛별형 (Morning Star)": "3봉 패턴: 음봉→작은봉→양봉. 강한 상승 반전 신호.",
    "석별형 (Evening Star)": "3봉 패턴: 양봉→작은봉→음봉. 강한 하락 반전 신호.",
    "삼백병 (3 White Soldiers)": "연속 3개 양봉(점진 상승). 강한 상승 추세 시작.",
    "삼흑병 (3 Black Crows)": "연속 3개 음봉(점진 하락). 강한 하락 추세 시작.",
    "잉태형 (Harami)": "큰 봉 안에 작은 봉 포함. 추세 전환 가능성. 단독 신뢰도 낮음.",
    "관통형 (Piercing)": "음봉 → 양봉이 50% 이상 회복. 상승 반전.",
    "먹구름 (Dark Cloud)": "양봉 → 음봉이 50% 이상 하락. 하락 반전.",
    "마루보즈 (Marubozu)": "꼬리 없는 봉. 한 방향 강한 힘. 방향 확인 보조.",
    "벨트홀드 (Belt Hold)": "시가에서 한 방향으로만 움직인 봉. 보조 신호.",
    "교수형 (Hanging Man)": "망치형과 동일 모양이나 상승 후 출현 시 하락 경고.",
    "역망치 (Inverted Hammer)": "하락 후 긴 위꼬리. 매수세 유입 가능성.",
    "키킹 (Kicking)": "갭을 동반한 반전. 매우 강한 방향 전환 신호.",
    "도지샛별 (Doji Morning Star)": "샛별형의 도지 버전. 더 강한 반전 신호.",
    "도지석별 (Doji Evening Star)": "석별형의 도지 버전. 더 강한 반전 신호.",
    "버림받은아기 (Abandoned Baby)": "갭 + 도지 + 갭. 매우 희귀하지만 강력한 반전.",
}

# 용어 설명
_TERM_HELP = {
    "정배열": "EMA21 > EMA55 > EMA200. 강한 상승 추세.",
    "부분정배열": "EMA55 > EMA200이나 EMA21이 아직 위가 아님. 추세 전환 초기.",
    "역배열": "EMA가 역순. 하락 추세 또는 횡보.",
    "HH": "Higher High — 고점이 이전보다 높음 (상승 구조).",
    "HL": "Higher Low — 저점이 이전보다 높음 (상승 구조).",
    "LH": "Lower High — 고점이 이전보다 낮음 (하락 구조).",
    "LL": "Lower Low — 저점이 이전보다 낮음 (하락 구조).",
    "R:R": "Risk:Reward 비율. 1:2 = 손절 1 대비 수익 2.",
    "pred_multi": "3개 지표 투표: Momentum + EMA Cross + Structure. 2개 이상 동의 시 방향 결정.",
}

def _normalize_symbol(raw: str) -> str:
    """사용자 입력 → 표준 심볼 형태.

    BTC → BTC/KRW (기본 Upbit)
    BTC/USDT → BTC/USDT
    KRW-BTC → BTC/KRW
    """
    raw = raw.upper().strip()
    if "/" in raw:
        return raw
    if raw.startswith("KRW-"):
        base = raw.split("-", 1)[1]
        return f"{base}/KRW"
    # 기본: Upbit KRW 마켓
    return f"{raw}/KRW"

def _split_message(text: str, limit: int = 1900) -> list[str]:
    """디스코드 2000자 제한 분할."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
