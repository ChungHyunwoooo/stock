"""자동 패턴 스캐너 + 디스코드 알림 서비스.

매 1시간(1H 봉 마감) 마다:
  1. 심볼별 멀티 타임프레임(30m, 1h, 4h) 동시 분석
  2. pred_multi 방향 예측 + 패턴 감지
  3. 시나리오 차트 생성 (KRW 환산)
  4. 디스코드 웹훅 전송

설정: config/pattern_alert.json
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict, fields as dc_fields
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
import requests

from engine.backtest.direction_predictor import (
    predict_ema_cross,
    predict_momentum,
    predict_multi,
    predict_structure,
)
from engine.data.base import get_provider
from engine.strategy.pattern_detector import (
    confirmed_before,
    find_local_extrema,
    scan_patterns,
)
from engine.strategy.candle_patterns import CandleSignal, scan_candle_patterns, format_candle_signals, get_candle_bias
from engine.strategy.pullback_detector import detect_pullback
from engine.strategy.risk_manager import RiskConfig, RiskManager

logger = logging.getLogger(__name__)

from engine.config_path import config_file

CONFIG_PATH = config_file("pattern_alert.json")
SENT_STATE_PATH = config_file("pattern_alert_sent.json")

_running = False
_thread: threading.Thread | None = None
_config: PatternAlertConfig | None = None
_risk_manager: RiskManager | None = None
_scan_count = 0
_last_scan_at = ""
_sent_state: dict[str, str] = {}  # "symbol:tf:pattern" → last_sent_time


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

@dataclass
class PatternAlertConfig:
    enabled: bool = True
    symbols: list[str] = field(default_factory=lambda: [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    ])
    exchange: str = "binance"
    timeframes: list[str] = field(default_factory=lambda: ["5m", "15m", "30m", "1h", "4h"])
    scan_interval_sec: int = 30  # 30초 (시그널 발생 시 빠른 추적)
    lookback_bars: int = 300
    send_chart: bool = True
    cooldown_sec: int = 14400  # 같은 신호 재발송 방지 (4시간)
    discord_webhook: str = ""
    # Upbit 동적 순위
    use_upbit_ranking: bool = True  # Upbit 거래대금 상위 N개 자동 사용
    ranking_count: int = 20  # 상위 N개
    ranking_refresh_sec: int = 300  # 순위 갱신 주기 (5분)
    krw_fallback_rate: float = 1450.0  # KRW/USDT 환율 조회 실패 시 폴백
    # 리스크 관리 — RiskConfig 기본값과 동일하게 유지
    # 변경 시 risk_manager.RiskConfig도 함께 확인
    max_positions_per_symbol: int = RiskConfig.max_positions_per_symbol
    max_total_positions: int = RiskConfig.max_total_positions
    max_daily_loss_pct: float = RiskConfig.max_daily_loss_pct
    max_consecutive_sl: int = RiskConfig.max_consecutive_sl

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> PatternAlertConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                logger.warning("설정 로드 실패, 기본값 사용: %s", e)
        return cls()


# ---------------------------------------------------------------------------
# KRW 환율
# ---------------------------------------------------------------------------

def _get_krw_rate(exchange: str = "binance") -> float:
    """BTC 기준 USDT/KRW 환율 추정."""
    try:
        p_bn = get_provider("crypto_spot", exchange=exchange)
        p_up = get_provider("crypto_spot", exchange="upbit")
        end = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        df_usdt = p_bn.fetch_ohlcv("BTC/USDT", start, end, "1h")
        df_krw = p_up.fetch_ohlcv("BTC/KRW", start, end, "1h")
        if len(df_usdt) > 0 and len(df_krw) > 0:
            return df_krw["close"].iloc[-1] / df_usdt["close"].iloc[-1]
    except Exception as e:
        logger.warning("환율 추정 실패: %s", e)
    return _config.krw_fallback_rate if _config else 1450.0


# ---------------------------------------------------------------------------
# 단일 심볼 멀티TF 분석
# ---------------------------------------------------------------------------

@dataclass
class TFResult:
    tf: str
    direction: str
    momentum: str
    ema_cross: str
    structure: str
    pattern: str
    ema_state: str
    current_price: float
    resistances: list[float]
    supports: list[float]
    high_trend: str  # "HH" | "LH"
    low_trend: str   # "HL" | "LL"
    signals: list = field(default_factory=list)  # list[PatternSignal]
    candles: list = field(default_factory=list)  # list[CandleSignal]
    candle_bias: str = "NEUTRAL"  # 캔들 패턴 종합 방향


def _analyze_tf(symbol: str, tf: str, exchange: str, lookback_days: int) -> TFResult | None:
    """단일 타임프레임 분석."""
    try:
        provider = get_provider("crypto_spot", exchange=exchange, realtime=True)
        # KST 기준 (Upbit 서버 시간)
        now_kst = pd.Timestamp.now(tz="Asia/Seoul")
        end = now_kst.strftime("%Y-%m-%d %H:%M:%S")
        start = (now_kst - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        df = provider.fetch_ohlcv(symbol, start, end, tf)

        if df.empty or len(df) < 100:
            return None

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        i = len(close) - 1

        ema21 = pd.Series(close).ewm(span=21, adjust=False).mean().values
        ema55 = pd.Series(close).ewm(span=55, adjust=False).mean().values
        ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().values

        mom = predict_momentum(close, i)
        ema = predict_ema_cross(close, i, ema21, ema55)
        struct = predict_structure(high, low, i)
        direction = predict_multi(close, high, low, i, ema21, ema55)

        # 극값 + 패턴
        low_mins, low_maxs = find_local_extrema(low, order=5)
        high_mins, high_maxs = find_local_extrema(high, order=5)
        pattern_signals = scan_patterns(close, high, low, i, direction,
                                       low_mins, low_maxs, high_mins, high_maxs)

        pattern_name = pattern_signals[0].pattern if pattern_signals else "없음"

        # 구조 판정
        rh = confirmed_before(high_maxs, i, 200, 5)
        rl = confirmed_before(low_mins, i, 200, 5)
        h_vals = [float(high[m]) for m in rh[-4:]]
        l_vals = [float(low[m]) for m in rl[-4:]]

        high_trend = "HH" if len(h_vals) >= 2 and h_vals[-1] > h_vals[-2] else "LH"
        low_trend = "HL" if len(l_vals) >= 2 and l_vals[-1] > l_vals[-2] else "LL"

        # EMA 배열
        if ema21[i] > ema55[i] > ema200[i]:
            ema_state = "정배열"
        elif ema55[i] > ema200[i]:
            ema_state = "부분정배열"
        else:
            ema_state = "역배열"

        resistances = sorted([v for v in h_vals if v > close[i]])[:3]
        supports = sorted([v for v in l_vals if v < close[i]], reverse=True)[:3]

        # TA-Lib 캔들 패턴
        opn = df["open"].values.astype(np.float64)
        candle_signals = scan_candle_patterns(opn, high, low, close, lookback=3)
        candle_dir, _ = get_candle_bias(candle_signals)

        # 눌림목 패턴
        pb_sig = detect_pullback(opn, high, low, close, i,
                                 ema21, ema55, low_mins, high_maxs,
                                 require_candle=True)
        if pb_sig:
            pattern_signals.append(pb_sig)
            if pattern_name == "없음":
                pattern_name = "눌림목"

        return TFResult(
            tf=tf, direction=direction,
            momentum=mom, ema_cross=ema, structure=struct,
            pattern=pattern_name, ema_state=ema_state,
            current_price=float(close[i]),
            resistances=resistances, supports=supports,
            high_trend=high_trend, low_trend=low_trend,
            signals=pattern_signals,
            candles=candle_signals,
            candle_bias=candle_dir,
        )
    except Exception as e:
        logger.error("%s %s 분석 실패: %s", symbol, tf, e)
        return None


def analyze_symbol(symbol: str, config: PatternAlertConfig) -> list[TFResult]:
    """심볼의 멀티 타임프레임 분석."""
    tf_days = {"5m": 5, "15m": 10, "30m": 15, "1h": 30, "4h": 90}
    results = []
    for tf in config.timeframes:
        days = tf_days.get(tf, 30)
        result = _analyze_tf(symbol, tf, config.exchange, days)
        if result:
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# 차트 생성
# ---------------------------------------------------------------------------

def _generate_chart(symbol: str, results: list[TFResult], krw_rate: float) -> bytes | None:
    """멀티TF 시나리오 차트 생성 → PNG bytes."""
    try:
        font_path = fm.findfont(fm.FontProperties(family="UnDotum"))
        plt.rcParams["font.family"] = fm.FontProperties(fname=font_path).get_name()
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

    # KRW 심볼이면 upbit, 아니면 binance
    if "/KRW" in symbol or symbol.startswith("KRW-"):
        chart_exchange = "upbit"
    else:
        chart_exchange = "binance"
    provider = get_provider("crypto_spot", exchange=chart_exchange)
    n = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(14, 5 * n), facecolor="#1a1a2e")
    if n == 1:
        axes = [axes]

    tf_days = {"5m": 3, "15m": 7, "30m": 10, "1h": 20, "4h": 60}

    for idx, (ax, r) in enumerate(zip(axes, results)):
        ax.set_facecolor("#1a1a2e")

        days = tf_days.get(r.tf, 20)
        now_kst = pd.Timestamp.now(tz="Asia/Seoul")
        end = now_kst.strftime("%Y-%m-%d %H:%M:%S")
        start = (now_kst - pd.Timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            df = provider.fetch_ohlcv(symbol, start, end, r.tf)
        except Exception:
            continue

        close = df["close"].values * krw_rate
        high = df["high"].values * krw_rate
        low = df["low"].values * krw_rate
        opn = df["open"].values * krw_rate
        dates = df.index

        ema21 = pd.Series(close).ewm(span=21, adjust=False).mean().values
        ema55 = pd.Series(close).ewm(span=55, adjust=False).mean().values

        for j in range(len(dates)):
            c = "#00d4aa" if close[j] >= opn[j] else "#ff4757"
            ax.plot([dates[j], dates[j]], [low[j], high[j]], color=c, linewidth=0.6)
            w = 2.5 if r.tf == "4h" else 1.5 if r.tf == "1h" else 0.8
            ax.plot([dates[j], dates[j]],
                    [min(opn[j], close[j]), max(opn[j], close[j])],
                    color=c, linewidth=w)

        ax.plot(dates, ema21, color="#ffd700", linewidth=1.2, alpha=0.8, label="EMA21")
        ax.plot(dates, ema55, color="#ff6b35", linewidth=1.2, alpha=0.8, label="EMA55")

        # 저항/지지
        for v in r.resistances[:2]:
            ax.axhline(y=v * krw_rate, color="#ff4757", linestyle="--", linewidth=1, alpha=0.7)
            ax.text(dates[-1], v * krw_rate, f"  {v * krw_rate:.0f}", color="#ff4757", fontsize=8, va="center")
        for v in r.supports[:2]:
            ax.axhline(y=v * krw_rate, color="#00d4aa", linestyle="--", linewidth=1, alpha=0.7)
            ax.text(dates[-1], v * krw_rate, f"  {v * krw_rate:.0f}", color="#00d4aa", fontsize=8, va="center")

        dir_color = "#00d4aa" if r.direction == "LONG" else "#ff4757" if r.direction == "SHORT" else "#888"
        tf_label = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}.get(r.tf, r.tf)
        title = f"{tf_label} | {r.direction} | {r.ema_state} | {r.high_trend}+{r.low_trend} | 패턴: {r.pattern}"
        ax.set_title(title, color=dir_color, fontsize=12, fontweight="bold", pad=8)
        ax.set_ylabel("KRW", color="white", fontsize=9)
        ax.tick_params(colors="white")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        for spine in ax.spines.values():
            spine.set_color("#333")
        ax.legend(loc="upper left", facecolor="#2d3436", edgecolor="#555", labelcolor="white", fontsize=8)
        ax.grid(True, alpha=0.1, color="#555")

    base = symbol.split("/")[0]
    fig.suptitle(f"{base} 멀티 타임프레임 분석 (KRW)", color="white", fontsize=15, fontweight="bold", y=0.99)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# 디스코드 전송
# ---------------------------------------------------------------------------

def _build_message(symbol: str, results: list[TFResult], krw_rate: float) -> str:
    """멀티TF 분석 결과 → 디스코드 메시지."""
    base = symbol.split("/")[0]
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")

    # 방향 합산
    directions = [r.direction for r in results]
    long_count = directions.count("LONG")
    short_count = directions.count("SHORT")
    if long_count > short_count:
        overall = "LONG"
    elif short_count > long_count:
        overall = "SHORT"
    else:
        overall = "NEUTRAL"

    # 종합 방향 이모지
    dir_emoji = {"LONG": "🟢", "SHORT": "🔴", "NEUTRAL": "⚪"}

    ref = next((r for r in results if r.tf == "1h"), results[0])
    price_str = _fmt_krw(ref.current_price * krw_rate)

    lines = [
        f"## {dir_emoji.get(overall, '⚪')} {base}  {price_str}  ({now})",
        f"**{overall}** — LONG {long_count} / SHORT {short_count} / NEUTRAL {directions.count('NEUTRAL')}",
    ]

    # ── 멀티TF 요약 (코드 블록으로 정렬)
    lines.append("```")
    lines.append(f"{'TF':>4}  {'방향':>7}  {'EMA':>6}  {'구조':>5}  패턴")
    lines.append("─" * 48)
    for r in results:
        tf_label = {"30m": "30분", "1h": " 1시간", "4h": " 4시간"}.get(r.tf, r.tf)
        pname = {
            "DOUBLE_BOTTOM": "쌍바닥", "DOUBLE_TOP": "쌍봉",
            "ASC_TRIANGLE": "상승삼각", "DESC_TRIANGLE": "하강삼각",
            "PULLBACK": "눌림목", "없음": "·",
        }.get(r.pattern, r.pattern)
        lines.append(f"{tf_label}  {r.direction:>7}  {r.ema_state:>6}  {r.high_trend}+{r.low_trend}  {pname}")
    lines.append("```")

    # ── 캔들 패턴 (별도 섹션, 간결하게)
    candle_lines = []
    for r in results:
        if not r.candles:
            continue
        tf_label = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}.get(r.tf, r.tf)
        tags = []
        for c in r.candles[:4]:
            icon = "▲" if c.direction == "BULL" else "▼"
            tags.append(f"{icon}{c.kr_name}")
        candle_lines.append(f"  {tf_label}: {' · '.join(tags)}")

    if candle_lines:
        lines.append("**캔들 시그널:**")
        lines.append("```")
        lines.extend(candle_lines)
        lines.append("```")

    # ── 전략 신호 (진입/손절/TP)
    all_signals = []
    for r in results:
        for s in r.signals:
            all_signals.append((r.tf, s))

    lines.append("**전략 신호:**")
    if all_signals:
        lines.append("```")
        for tf, s in all_signals:
            tf_label = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}.get(tf, tf)
            pname = {
                "DOUBLE_BOTTOM": "쌍바닥", "DOUBLE_TOP": "쌍봉",
                "ASC_TRIANGLE": "상승삼각형", "DESC_TRIANGLE": "하강삼각형",
                "PULLBACK": "눌림목",
            }.get(s.pattern, s.pattern)
            entry_krw = s.entry_price * krw_rate
            sl_krw = s.stop_loss * krw_rate
            tp_krw = s.take_profit * krw_rate
            sl_pct = abs(s.stop_loss - s.entry_price) / s.entry_price * 100
            tp_pct = abs(s.take_profit - s.entry_price) / s.entry_price * 100
            rr = round(tp_pct / sl_pct, 1) if sl_pct > 0 else 0
            lines.append(f"[{tf_label}] {pname} ({s.side})")
            lines.append(f"  진입  {_fmt_krw(entry_krw)}")
            lines.append(f"  손절  {_fmt_krw(sl_krw)}  ({sl_pct:.1f}%)")
            lines.append(f"  목표  {_fmt_krw(tp_krw)}  ({tp_pct:.1f}%)  R:R 1:{rr}")
            lines.append("")
        lines.append("```")
    else:
        lines.append("> 현재 감지된 매매 신호 없음")

    # ── 핵심 레벨
    lines.append("**핵심 레벨:**")
    lines.append("```")
    for v in reversed(ref.resistances[:3]):
        lines.append(f"  저항  {_fmt_krw(v * krw_rate):>14}  +{(v - ref.current_price) / ref.current_price * 100:.1f}%")
    lines.append(f"  ───  {_fmt_krw(ref.current_price * krw_rate):>14}  현재가")
    for v in ref.supports[:3]:
        lines.append(f"  지지  {_fmt_krw(v * krw_rate):>14}  {(v - ref.current_price) / ref.current_price * 100:.1f}%")
    lines.append("```")

    return "\n".join(lines)


def _fmt_krw(value: float) -> str:
    """가격대별 KRW 포맷. 고가: 정수, 저가: 소수점 유지."""
    if value >= 1000:
        return f"{round(value):,}원"
    elif value >= 10:
        return f"{value:,.1f}원"
    elif value >= 1:
        return f"{value:,.2f}원"
    else:
        return f"{value:,.4f}원"


def _send_discord(webhook_url: str, message: str, chart_bytes: bytes | None = None) -> bool:
    """디스코드 웹훅 전송."""
    try:
        if chart_bytes:
            resp = requests.post(
                webhook_url,
                data={"content": message},
                files={"file": ("analysis.png", chart_bytes, "image/png")},
                timeout=30,
            )
        else:
            resp = requests.post(
                webhook_url,
                json={"content": message},
                timeout=30,
            )
        if resp.status_code in (200, 204):
            return True
        logger.warning("디스코드 전송 실패: %d %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("디스코드 전송 에러: %s", e)
    return False


# ---------------------------------------------------------------------------
# 중복 방지
# ---------------------------------------------------------------------------

def _load_sent_state() -> None:
    global _sent_state
    if SENT_STATE_PATH.exists():
        try:
            _sent_state = json.loads(SENT_STATE_PATH.read_text())
        except Exception:
            _sent_state = {}


def _save_sent_state() -> None:
    SENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_STATE_PATH.write_text(json.dumps(_sent_state, indent=2))


def _should_send(symbol: str, results: list[TFResult], cooldown_sec: int) -> bool:
    """쿨다운 내 동일 신호 중복 방지."""
    sig_key = f"{symbol}:" + "|".join(f"{r.tf}:{r.direction}:{r.pattern}" for r in results)
    last = _sent_state.get(sig_key, "")
    if last:
        try:
            elapsed = time.time() - float(last)
            if elapsed < cooldown_sec:
                return False
        except ValueError:
            pass
    _sent_state[sig_key] = str(time.time())
    return True


# ---------------------------------------------------------------------------
# 알림 조건 판단
# ---------------------------------------------------------------------------

def _is_alertable(results: list[TFResult]) -> bool:
    """알림 발송 조건: 패턴이 1개 이상 감지되었거나, 전 TF 방향 일치."""
    has_pattern = any(r.pattern != "없음" for r in results)
    if has_pattern:
        return True

    directions = [r.direction for r in results if r.direction != "NEUTRAL"]
    if len(directions) >= 2 and len(set(directions)) == 1:
        return True

    return False


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------

def _resolve_symbols(config: PatternAlertConfig) -> tuple[list[str], str]:
    """설정에 따라 심볼 목록과 거래소 결정.

    Returns:
        (symbols, exchange)
    """
    if config.use_upbit_ranking:
        from engine.data.upbit_ranking import get_top_symbols
        symbols = get_top_symbols(config.ranking_count)
        return symbols, "upbit"
    return config.symbols, config.exchange


def _scan_once(config: PatternAlertConfig) -> list[dict]:
    """전체 심볼 1회 스캔. 알림 발송된 결과 목록 반환."""
    global _scan_count, _last_scan_at

    _scan_count += 1
    _last_scan_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    symbols, exchange = _resolve_symbols(config)
    logger.info("패턴 스캔 #%d 시작 (%d 심볼, %s)", _scan_count, len(symbols), exchange)

    # KRW 심볼이면 환율 변환 불필요
    is_krw = any("/KRW" in s for s in symbols)
    krw_rate = 1.0 if is_krw else _get_krw_rate(exchange)

    # 스캔용 config 복사 (exchange 오버라이드)
    scan_config = PatternAlertConfig(**{
        **{k: getattr(config, k) for k in config.__dataclass_fields__},
        "exchange": exchange,
        "symbols": symbols,
    })

    webhook = config.discord_webhook
    if not webhook:
        discord_path = config_file("discord.json")
        if discord_path.exists():
            dc = json.loads(discord_path.read_text())
            webhook = dc.get("webhooks", {}).get("tf_1h", dc.get("webhook_url", ""))

    sent_results = []
    for symbol in symbols:
        try:
            results = analyze_symbol(symbol, scan_config)
            if not results:
                continue

            if not _is_alertable(results):
                logger.debug("%s: 알림 조건 미충족", symbol)
                continue

            if not _should_send(symbol, results, config.cooldown_sec):
                logger.debug("%s: 쿨다운 중", symbol)
                continue

            message = _build_message(symbol, results, krw_rate)

            chart_bytes = None
            if config.send_chart:
                chart_bytes = _generate_chart(symbol, results, krw_rate)

            if webhook:
                ok = _send_discord(webhook, message, chart_bytes)
                logger.info("%s: 디스코드 전송 %s", symbol, "성공" if ok else "실패")
            else:
                logger.warning("디스코드 웹훅 미설정")

            sent_results.append({
                "symbol": symbol, "direction": results[0].direction if results else "NEUTRAL",
                "patterns": [r.pattern for r in results if r.pattern != "없음"],
            })

        except Exception as e:
            logger.error("%s 스캔 에러: %s", symbol, e, exc_info=True)

    _save_sent_state()
    logger.info("패턴 스캔 #%d 완료 (%d 알림)", _scan_count, len(sent_results))
    return sent_results


def _loop() -> None:
    """데몬 루프."""
    global _running, _config
    _load_sent_state()

    while _running:
        config = _config or PatternAlertConfig.load()
        if config.enabled:
            try:
                _scan_once(config)
            except Exception as e:
                logger.error("스캔 루프 에러: %s", e, exc_info=True)

        # 다음 스캔까지 대기 (1초 단위로 체크해서 stop 반응성 확보)
        wait = config.scan_interval_sec
        for _ in range(wait):
            if not _running:
                break
            time.sleep(1)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def start(config: PatternAlertConfig | None = None) -> None:
    """스캐너 시작."""
    global _running, _thread, _config, _risk_manager
    if _running:
        logger.warning("이미 실행 중")
        return

    _config = config or PatternAlertConfig.load()
    _risk_manager = RiskManager(RiskConfig(
        max_positions_per_symbol=_config.max_positions_per_symbol,
        max_total_positions=_config.max_total_positions,
        max_daily_loss_pct=_config.max_daily_loss_pct,
        max_consecutive_sl=_config.max_consecutive_sl,
    ))

    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="pattern-alert")
    _thread.start()
    logger.info("패턴 스캐너 시작: %d 심볼, %ds 간격", len(_config.symbols), _config.scan_interval_sec)


def stop() -> None:
    """스캐너 중지."""
    global _running, _thread
    _running = False
    if _thread:
        _thread.join(timeout=5)
        _thread = None
    logger.info("패턴 스캐너 중지")


def scan_now(config: PatternAlertConfig | None = None) -> list[dict]:
    """즉시 1회 스캔. 알림된 결과 반환."""
    cfg = config or _config or PatternAlertConfig.load()
    return _scan_once(cfg)


def analyze_single(symbol: str, config: PatternAlertConfig | None = None) -> tuple[list[TFResult], str, float]:
    """단일 심볼 분석 (Discord 메뉴얼 스캔용).

    Returns:
        (results, message, krw_rate)
    """
    cfg = config or _config or PatternAlertConfig.load()

    # 심볼에 따라 거래소 자동 결정
    if "/KRW" in symbol or symbol.startswith("KRW-"):
        exchange = "upbit"
        krw_rate = 1.0
    else:
        exchange = cfg.exchange
        krw_rate = _get_krw_rate(exchange)

    scan_cfg = PatternAlertConfig(**{
        **{k: getattr(cfg, k) for k in cfg.__dataclass_fields__},
        "exchange": exchange,
    })

    results = analyze_symbol(symbol, scan_cfg)
    message = _build_message(symbol, results, krw_rate) if results else f"{symbol}: 분석 데이터 없음"
    return results, message, krw_rate


def generate_chart_for_symbol(symbol: str, results: list[TFResult], krw_rate: float) -> bytes | None:
    """외부에서 차트 생성 호출용 래퍼."""
    return _generate_chart(symbol, results, krw_rate)


def status() -> dict:
    """현재 상태."""
    return {
        "running": _running,
        "scan_count": _scan_count,
        "last_scan_at": _last_scan_at,
        "config": asdict(_config) if _config else None,
    }


def update_config(**kwargs) -> PatternAlertConfig:
    """설정 업데이트."""
    global _config
    cfg = _config or PatternAlertConfig.load()
    for k, v in kwargs.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    cfg.save()
    _config = cfg
    return cfg
