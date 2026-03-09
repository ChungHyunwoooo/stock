"""Config-first alert runtime (v2) with shadow/canary/live modes.

Phases covered:
- phase2: runtime config externalization
- phase3: detector registry usage
- phase4: exchange adapter abstraction (upbit/binance)
- phase5: cross-exchange metrics in reports
- phase6: canary/live rollout switch
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import io

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

from engine.analysis import build_context
from engine.analysis.exchange_dominance import analyze_exchange_dominance, fetch_exchange_ohlcv
from engine.alerts.discord import load_webhook_url_for
from engine.strategy.detector_registry import resolve_detectors
from engine.strategy.exchange_adapters import get_exchange_adapter
from engine.strategy import upbit_scanner as scanner

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "alert_v2.json"
SENT_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "alert_v2_sent.json"
PERF_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "alert_v2_perf.json"
LOOP_INTERVAL_SEC = 30

_running = False
_thread: threading.Thread | None = None
_config = None
_reports: list[dict] = []
_scan_count = 0
_last_scan_at = ""
_sent_state: dict[str, dict] = {}
_perf: dict = {"open": [], "closed": []}


@dataclass
class AlertV2Config:
    enabled: bool = False
    mode: str = "shadow"  # shadow | canary | live
    exchange: str = "upbit"  # upbit | binance
    scan_interval_sec: int = LOOP_INTERVAL_SEC
    interval: str = "5m"  # legacy field (unused in multi-tf mode)
    bar_count: int = 200
    max_symbols: int = 20
    symbols: list[str] = field(default_factory=list)
    compare_window_sec: int = 600
    rollout_pct: int = 20
    min_confidence: float = 0.5
    send_chart: bool = False
    usdkrw: float = 1350.0
    sample_size: int = 10
    track_pnl: bool = True
    close_after_sec: int = 3600
    enable_tf_5m: bool = True
    enable_tf_30m: bool = True
    enable_tf_1h: bool = True
    enable_tf_4h: bool = True
    enable_regime_filter: bool = True

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.scan_interval_sec = LOOP_INTERVAL_SEC
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls) -> AlertV2Config:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                known = {f.name for f in cls.__dataclass_fields__.values()}
                return cls(**{k: v for k, v in data.items() if k in known})
            except Exception as e:
                logger.warning("Failed to load alert_v2 config: %s", e)
        return cls()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _signal_key(sig) -> str:
    return f"{sig.symbol}|{sig.strategy}|{sig.side}|{sig.timeframe}"


def _parse_utc(ts: str) -> float:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _choose_symbols(cfg: AlertV2Config, adapter) -> list[str]:
    base = adapter.get_active_symbols(max_symbols=max(1, cfg.max_symbols))
    seen = set(base)
    merged = list(base)
    for s in cfg.symbols:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    return merged[: max(1, cfg.max_symbols)]


def _detector_label(scan_fn) -> str:
    return getattr(scan_fn, "__name__", "detector")


def _maybe_send(sig, cfg: AlertV2Config, webhook_url: str | None = None) -> bool:
    if cfg.mode == "shadow":
        return False
    if cfg.mode == "canary":
        if random.randint(1, 100) > max(0, min(100, cfg.rollout_pct)):
            return False
    chart_data = None
    if cfg.send_chart:
        chart_data = _generate_combined_candle_chart(
            base=sig.symbol.replace("KRW-", "").replace("/USDT", ""),
            tf=sig.timeframe,
            bars=min(cfg.bar_count, 300),
            dominance=getattr(sig, "_dominance", None),  # type: ignore[attr-defined]
            sig=sig,
        )
        if chart_data is None:
            # fallback: upbit-only chart
            chart_data = scanner.generate_chart(sig._source_df, sig, scanner.UpbitScannerConfig.load())  # type: ignore[attr-defined]
    return scanner.send_upbit_alert(sig, chart_data=chart_data, webhook_url=webhook_url)


def _plot_candles(ax, df: pd.DataFrame, title: str) -> None:
    _plot_candles_with_overlays(ax, df, title, None, add_levels=False)


def _plot_candles_with_overlays(
    ax,
    df: pd.DataFrame,
    title: str,
    sig=None,
    add_levels: bool = False,
) -> None:
    if df is None or df.empty:
        return
    data = df.tail(120)
    x = mdates.date2num(data.index.to_pydatetime())
    width = (x[-1] - x[0]) / max(120, len(x)) * 0.8 if len(x) > 1 else 0.0005
    for xi, (_, row) in zip(x, data.iterrows()):
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        color = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(xi, l, h, color=color, linewidth=0.8)
        body_low = min(o, c)
        body_h = max(abs(c - o), 1e-8)
        ax.add_patch(Rectangle((xi - width / 2, body_low), width, body_h, facecolor=color, edgecolor=color, linewidth=0.6))

    # Dark chart styling
    ax.set_facecolor("#0f111a")
    for spine in ax.spines.values():
        spine.set_color("#39414f")

    # EMA 5/20/60 overlays
    close = data["close"]
    ema5 = close.ewm(span=5, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema60 = close.ewm(span=60, adjust=False).mean()
    ax.plot(data.index, ema5, color="#ffd54f", linewidth=0.9, label="EMA5")
    ax.plot(data.index, ema20, color="#42a5f5", linewidth=0.9, label="EMA20")
    ax.plot(data.index, ema60, color="#ab47bc", linewidth=0.9, label="EMA60")

    # Entry/SL/TP lines on Upbit panel only
    if add_levels and sig is not None:
        entry = float(getattr(sig, "entry", 0.0))
        sl = float(getattr(sig, "stop_loss", 0.0))
        tps = list(getattr(sig, "take_profits", []) or [])
        x0 = data.index[0]
        x1 = data.index[-1]
        if entry > 0:
            ax.axhline(entry, color="#00e676", linestyle="-", linewidth=1.2, alpha=0.95, label=f"Entry {entry:,.2f}")
        if sl > 0:
            ax.axhline(sl, color="#ff5252", linestyle="-", linewidth=1.2, alpha=0.95, label=f"SL {sl:,.2f}")
        for i, tp in enumerate(tps[:3], 1):
            tpv = float(tp)
            ax.axhline(tpv, color="#40c4ff", linestyle="-", linewidth=1.1, alpha=0.95, label=f"TP{i} {tpv:,.2f}")

        # TradingView-like position zones (risk/reward rectangles)
        if entry > 0 and sl > 0 and tps:
            tp_zone = float(tps[0])
            side = str(getattr(sig, "side", "LONG")).upper()
            if side == "LONG":
                risk_low, risk_high = min(sl, entry), max(sl, entry)
                rew_low, rew_high = min(entry, tp_zone), max(entry, tp_zone)
                ax.fill_between([x0, x1], risk_low, risk_high, color="#ff5252", alpha=0.14, zorder=0)
                ax.fill_between([x0, x1], rew_low, rew_high, color="#00e676", alpha=0.12, zorder=0)
            else:
                risk_low, risk_high = min(entry, sl), max(entry, sl)
                rew_low, rew_high = min(tp_zone, entry), max(tp_zone, entry)
                ax.fill_between([x0, x1], risk_low, risk_high, color="#ff5252", alpha=0.14, zorder=0)
                ax.fill_between([x0, x1], rew_low, rew_high, color="#00e676", alpha=0.12, zorder=0)

            ax.text(x1, entry, f" Entry {entry:,.2f}", color="#00e676", fontsize=8, va="bottom", ha="right")
            ax.text(x1, sl, f" SL {sl:,.2f}", color="#ff8a80", fontsize=8, va="bottom", ha="right")
            ax.text(x1, tp_zone, f" TP1 {tp_zone:,.2f}", color="#80d8ff", fontsize=8, va="bottom", ha="right")

    ax.set_title(title, fontsize=10)
    ax.grid(alpha=0.18, color="#2a3140")
    ax.xaxis_date()
    ax.tick_params(axis="x", labelsize=8, colors="#c9d1d9")
    ax.tick_params(axis="y", labelsize=8, colors="#c9d1d9")
    ax.title.set_color("#e6edf3")
    leg = ax.legend(loc="upper left", fontsize=7, facecolor="#0f111a", edgecolor="#39414f")
    for text in leg.get_texts():
        text.set_color("#c9d1d9")


def _tf_minutes(tf: str) -> int:
    return {"5m": 5, "30m": 30, "1h": 60, "4h": 240}.get(tf, 5)


def _add_projection_scenario(ax, df: pd.DataFrame, sig, tf: str) -> None:
    """Add TV-style projection path with ETA to TP1 zone."""
    if df is None or df.empty or sig is None:
        return
    data = df.tail(120)
    if len(data) < 20:
        return

    entry = float(getattr(sig, "entry", 0.0))
    tps = list(getattr(sig, "take_profits", []) or [])
    side = str(getattr(sig, "side", "LONG")).upper()
    if entry <= 0 or not tps:
        return
    tp1 = float(tps[0])

    atr_like = float((data["high"] - data["low"]).rolling(14).mean().iloc[-1])
    if atr_like <= 0:
        return
    step = max(atr_like * 0.7, abs(float(data["close"].iloc[-1]) - float(data["close"].iloc[-2])))
    dist = abs(tp1 - entry)
    est_bars = int(max(3, min(48, dist / max(step, 1e-8))))

    last_ts = data.index[-1]
    delta = pd.Timedelta(minutes=_tf_minutes(tf))
    eta_ts = last_ts + delta * est_bars
    eta_min = _tf_minutes(tf) * est_bars

    y0 = float(data["close"].iloc[-1])
    y1 = tp1
    path_color = "#64b5f6" if side == "LONG" else "#ffab91"
    ax.plot([last_ts, eta_ts], [y0, y1], color=path_color, linewidth=1.3, linestyle="--", alpha=0.95, label="Scenario")
    ax.scatter([eta_ts], [y1], color=path_color, s=28, zorder=5)

    zone_h = max(atr_like * 0.25, abs(tp1) * 0.0015)
    z0, z1 = (tp1 - zone_h, tp1 + zone_h)
    zone_color = "#00c853" if side == "LONG" else "#ff5252"
    ax.fill_between([last_ts, eta_ts], z0, z1, color=zone_color, alpha=0.10, zorder=0)
    ax.text(
        eta_ts,
        tp1,
        f"ETA ~{eta_min}m\nTP1 zone",
        fontsize=8,
        color="#e6edf3",
        ha="left",
        va="bottom",
        bbox={"facecolor": "#111827", "edgecolor": "#334155", "alpha": 0.85, "pad": 2},
    )


def _generate_combined_candle_chart(base: str, tf: str, bars: int, dominance: dict | None, sig=None) -> bytes | None:
    """Generate a single image containing two candle charts:
    1) Upbit KRW
    2) Top1 exchange BASE/USDT
    """
    try:
        import pyupbit

        if not dominance:
            dominance = analyze_exchange_dominance(base)
        ref = dominance.get("reference_exchange", {}) if isinstance(dominance, dict) else {}
        top1 = dominance.get("dominant_exchange", {}) if isinstance(dominance, dict) else {}
        ref_ex = str(ref.get("exchange", top1.get("exchange", "binance")))
        refs = dominance.get("upbit_trading_refs", {}) if isinstance(dominance, dict) else {}
        kimp = float(refs.get("kimchi_premium_pct", 0.0))

        upbit_interval = {"5m": "minute5", "30m": "minute30", "1h": "minute60", "4h": "minute240"}.get(tf, "minute5")
        df_up = pyupbit.get_ohlcv(f"KRW-{base}", interval=upbit_interval, count=bars)
        df_top = fetch_exchange_ohlcv(ref_ex, base, interval=tf, count=bars)
        if df_up is None or df_up.empty or df_top is None or df_top.empty:
            return None

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=False, facecolor="#0b0f17")
        _plot_candles_with_overlays(axes[0], df_up, f"UPBIT KRW-{base} ({tf})", sig=sig, add_levels=True)
        _add_projection_scenario(axes[0], df_up, sig, tf)
        _plot_candles_with_overlays(axes[1], df_top, f"REF {ref_ex.upper()} {base}/USDT ({tf})", sig=None, add_levels=False)
        st = fig.suptitle(
            f"{base} | Dominant={top1.get('exchange','?')} last={top1.get('last')} | Ref={ref_ex.upper()} last={ref.get('last')} | Upbit last={refs.get('upbit_last_krw')} | KIMP={kimp:+.3f}%",
            fontsize=11,
        )
        st.set_color("#e6edf3")
        fig.tight_layout()
        bio = io.BytesIO()
        fig.savefig(bio, format="png", dpi=150)
        plt.close(fig)
        return bio.getvalue()
    except Exception:
        return None


def _load_sent_state() -> None:
    global _sent_state
    if SENT_STATE_PATH.exists():
        try:
            _sent_state = json.loads(SENT_STATE_PATH.read_text())
            return
        except Exception:
            pass
    _sent_state = {}


def _save_sent_state() -> None:
    SENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep recent-ish states only.
    now = time.time()
    pruned = {}
    for k, v in _sent_state.items():
        if (now - float(v.get("timestamp", 0))) <= 86400:
            pruned[k] = v
    _sent_state.clear()
    _sent_state.update(pruned)
    SENT_STATE_PATH.write_text(json.dumps(_sent_state, indent=2, ensure_ascii=False))


def _load_perf() -> None:
    global _perf
    if PERF_PATH.exists():
        try:
            data = json.loads(PERF_PATH.read_text())
            if isinstance(data, dict):
                _perf = {
                    "open": list(data.get("open", [])),
                    "closed": list(data.get("closed", [])),
                }
                return
        except Exception:
            pass
    _perf = {"open": [], "closed": []}


def _save_perf() -> None:
    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    # bound history
    if len(_perf["closed"]) > 2000:
        _perf["closed"] = _perf["closed"][:2000]
    PERF_PATH.write_text(json.dumps(_perf, indent=2, ensure_ascii=False))


def _enabled_timeframes(cfg: AlertV2Config) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if cfg.enable_tf_5m:
        out.append(("5m", "tf_5m"))
    if cfg.enable_tf_30m:
        out.append(("30m", "tf_30m"))
    if cfg.enable_tf_1h:
        out.append(("1h", "tf_1h"))
    if cfg.enable_tf_4h:
        out.append(("4h", "tf_4h"))
    return out


def _ox_summary(detectors: list, results: dict[str, object]) -> str:
    parts = []
    for fn in detectors:
        name = _detector_label(fn).replace("scan_", "").upper()
        parts.append(f"{name}={'O' if results.get(name) else 'X'}")
    # Discord markdown table is not rendered reliably in embeds.
    # Use monospace block-friendly rows instead.
    lines = []
    row = []
    for i, p in enumerate(parts, 1):
        row.append(p)
        if i % 3 == 0:
            lines.append("  ".join(row))
            row = []
    if row:
        lines.append("  ".join(row))
    return "\n".join(lines)


def _dedup_key(symbol: str, tf: str) -> str:
    return f"{symbol}:{tf}"


def _should_send_symbol_summary(symbol: str, tf: str, candle_id: str, signature: str) -> bool:
    key = _dedup_key(symbol, tf)
    prev = _sent_state.get(key, {})
    # Same candle: never resend.
    if prev.get("candle_id") == candle_id:
        return False
    # Same signature: skip to avoid identical repeats across candles.
    if prev.get("signature") == signature:
        return False
    return True


def _mark_sent_symbol_summary(symbol: str, tf: str, candle_id: str, signature: str) -> None:
    _sent_state[_dedup_key(symbol, tf)] = {
        "candle_id": candle_id,
        "signature": signature,
        "timestamp": time.time(),
    }


def _classify_regime(ctx: dict) -> str:
    adx = float((ctx.get("adx") or {}).get("adx", 0.0))
    bb = ctx.get("bb") or {}
    is_squeeze = bool(bb.get("is_squeeze", False))
    is_expansion = bool(bb.get("is_expansion", False))
    if is_expansion and adx >= 18:
        return "EXPANSION"
    if adx < 18 or is_squeeze:
        return "RANGE"
    if adx >= 23:
        return "TREND"
    return "MIXED"


def _detector_group(label: str) -> str:
    # label example: scan_supertrend
    if label in ("scan_stoch_rsi", "scan_bb_rsi_stoch"):
        return "RANGE"
    if label in ("scan_early_pump", "scan_macd_divergence"):
        return "EXPANSION"
    return "TREND"


def _regime_allows(regime: str, detector_label: str) -> bool:
    g = _detector_group(detector_label)
    if regime == "RANGE":
        return g == "RANGE"
    if regime == "TREND":
        return g in ("TREND", "EXPANSION")
    if regime == "EXPANSION":
        return g in ("EXPANSION", "TREND")
    return True


def _record_alert_open(sig, tf: str) -> None:
    now = time.time()
    rec = {
        "id": f"{sig.symbol}:{tf}:{int(now)}",
        "symbol": sig.symbol,
        "timeframe": tf,
        "side": sig.side,
        "entry": float(sig.entry),
        "created_at": now,
        "last_price": float(sig.entry),
        "pnl_pct": 0.0,
        "max_pnl_pct": 0.0,
        "min_pnl_pct": 0.0,
    }
    _perf["open"].insert(0, rec)
    if len(_perf["open"]) > 1000:
        _perf["open"] = _perf["open"][:1000]


def _calc_pnl(side: str, entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    if side == "SHORT":
        return (entry / price - 1.0) * 100.0 if price > 0 else 0.0
    return (price / entry - 1.0) * 100.0


def _update_pnl(symbol: str, tf: str, last_close: float, cfg: AlertV2Config) -> None:
    now = time.time()
    kept = []
    closed_new = []
    for rec in _perf["open"]:
        if rec.get("symbol") != symbol or rec.get("timeframe") != tf:
            kept.append(rec)
            continue
        pnl = _calc_pnl(rec.get("side", "LONG"), float(rec.get("entry", 0)), float(last_close))
        rec["last_price"] = float(last_close)
        rec["pnl_pct"] = round(float(pnl), 4)
        rec["max_pnl_pct"] = round(max(float(rec.get("max_pnl_pct", 0.0)), float(pnl)), 4)
        rec["min_pnl_pct"] = round(min(float(rec.get("min_pnl_pct", 0.0)), float(pnl)), 4)

        age = now - float(rec.get("created_at", now))
        if age >= max(60, cfg.close_after_sec):
            rec["closed_at"] = now
            rec["close_reason"] = "TIMEOUT"
            closed_new.append(rec)
        else:
            kept.append(rec)
    _perf["open"] = kept
    if closed_new:
        _perf["closed"] = closed_new + _perf["closed"]


def _run_once(cfg: AlertV2Config) -> dict:
    adapter = get_exchange_adapter(cfg.exchange)
    symbols = _choose_symbols(cfg, adapter)
    detectors = resolve_detectors()
    prod_cfg = scanner.UpbitScannerConfig.load()

    generated = 0
    sent = 0
    errors = 0
    by_detector: dict[str, int] = {}
    keys: set[str] = set()
    kp_vals: list[float] = []

    per_tf_generated: dict[str, int] = {}
    blocked_by_regime = 0
    tfs = _enabled_timeframes(cfg)

    for tf_label, channel in tfs:
        webhook_url = load_webhook_url_for(channel)
        for symbol in symbols:
            try:
                df = adapter.fetch_ohlcv(symbol, interval=tf_label, count=cfg.bar_count)
                if df is None or df.empty:
                    continue
                try:
                    ctx = build_context(df)
                except Exception:
                    ctx = {}
                regime = _classify_regime(ctx)
                if cfg.track_pnl:
                    _update_pnl(symbol, tf_label, float(df["close"].iloc[-1]), cfg)

                results: dict[str, object] = {}
                valid_sigs = []
                for fn in detectors:
                    label = _detector_label(fn)
                    ox_key = label.replace("scan_", "").upper()
                    if cfg.enable_regime_filter and (not _regime_allows(regime, label)):
                        blocked_by_regime += 1
                        results[ox_key] = None
                        continue
                    try:
                        sig = fn(df, symbol, prod_cfg, context=ctx)
                    except TypeError:
                        try:
                            sig = fn(df, symbol, prod_cfg)
                        except Exception:
                            sig = None
                    except Exception:
                        sig = None

                    if sig is not None:
                        sig = scanner.validate_signal_rr(sig)
                    if sig is not None and sig.confidence >= cfg.min_confidence:
                        sig.timeframe = tf_label
                        valid_sigs.append(sig)
                        generated += 1
                        per_tf_generated[tf_label] = per_tf_generated.get(tf_label, 0) + 1
                        by_detector[label] = by_detector.get(label, 0) + 1
                        keys.add(_signal_key(sig))
                        results[ox_key] = sig
                    else:
                        results[ox_key] = None

                # Coin-level summary alert: one message per symbol/timeframe.
                if not valid_sigs:
                    continue

                # Representative signal for chart/levels.
                rep = sorted(valid_sigs, key=lambda s: float(s.confidence), reverse=True)[0]
                ox = _ox_summary(detectors, results)
                candle_id = str(df.index[-1])
                signature = f"{tf_label}|{symbol}|{ox}|{rep.side}"
                if not _should_send_symbol_summary(symbol, tf_label, candle_id, signature):
                    continue

                base = symbol.replace("KRW-", "").replace("/USDT", "")
                dominance = analyze_exchange_dominance(base=base, usdkrw=cfg.usdkrw)
                refs = dominance.get("upbit_trading_refs", {}) if isinstance(dominance, dict) else {}
                top1 = dominance.get("dominant_exchange", {}) if isinstance(dominance, dict) else {}
                top3 = dominance.get("top3_exchanges", []) if isinstance(dominance, dict) else []
                kp = float(refs.get("kimchi_premium_pct", 0.0))
                kp_vals.append(kp)

                rep.strategy = "ALERT_V2_SYMBOL"
                rep.reason = (
                    f"[{tf_label}] {adapter.display_symbol(symbol)}\n"
                    f"Regime: {regime}\n"
                    f"Top3 비율: "
                    + ", ".join([f"{x.get('exchange')} {x.get('ratio_pct')}%" for x in top3[:3]])
                    + "\n"
                    f"last: ref={dominance.get('reference_exchange',{}).get('exchange','?')} {dominance.get('reference_exchange',{}).get('last')} | upbit={refs.get('upbit_last_krw')}\n"
                    f"김프: {kp:+.3f}%\n"
                    f"전략 상태\n```text\n{ox}\n```\n"
                )
                # attach source df for chart generation in _maybe_send
                rep._source_df = df  # type: ignore[attr-defined]
                rep._dominance = dominance  # type: ignore[attr-defined]

                if _maybe_send(rep, cfg, webhook_url=webhook_url):
                    sent += 1
                    _mark_sent_symbol_summary(symbol, tf_label, candle_id, signature)
                    if cfg.track_pnl:
                        _record_alert_open(rep, tf_label)
            except Exception:
                errors += 1

    now_ts = time.time()
    prod_hist = scanner.get_alert_history()
    prod_recent = []
    for item in prod_hist:
        ts = _parse_utc(item.get("timestamp", ""))
        if ts > 0 and (now_ts - ts) <= cfg.compare_window_sec:
            prod_recent.append(
                f"{item.get('symbol')}|{item.get('strategy')}|{item.get('side')}|{item.get('timeframe')}"
            )
    prod_keys = set(prod_recent)

    overlap = keys & prod_keys
    report = {
        "timestamp": _utc_now(),
        "mode": cfg.mode,
        "exchange": cfg.exchange,
        "symbols": len(symbols),
        "timeframes": [t[0] for t in tfs],
        "detectors": len(detectors),
        "generated": generated,
        "per_tf_generated": per_tf_generated,
        "blocked_by_regime": blocked_by_regime,
        "sent": sent,
        "errors": errors,
        "prod_recent": len(prod_keys),
        "overlap": len(overlap),
        "shadow_only": len(keys - prod_keys),
        "prod_only": len(prod_keys - keys),
        "by_detector": by_detector,
        "avg_kimchi_premium_pct": round(float(pd.Series(kp_vals).mean()), 4) if kp_vals else 0.0,
        "open_alerts": len(_perf["open"]),
        "closed_alerts": len(_perf["closed"]),
    }
    if _perf["closed"]:
        closed = _perf["closed"][:200]
        pnls = [float(x.get("pnl_pct", 0.0)) for x in closed]
        wins = sum(1 for p in pnls if p > 0)
        report["closed_win_rate"] = round(wins / max(1, len(pnls)) * 100.0, 2)
        report["closed_avg_pnl_pct"] = round(float(pd.Series(pnls).mean()), 4)
    else:
        report["closed_win_rate"] = 0.0
        report["closed_avg_pnl_pct"] = 0.0
    return report


def _loop() -> None:
    global _scan_count, _last_scan_at
    while _running:
        try:
            report = _run_once(_config)
            _scan_count += 1
            _last_scan_at = report["timestamp"]
            _reports.insert(0, report)
            if len(_reports) > 200:
                _reports.pop()
            logger.info(
                "alert_v2 #%d %s/%s generated=%d sent=%d overlap=%d",
                _scan_count,
                report["mode"],
                report["exchange"],
                report["generated"],
                report["sent"],
                report["overlap"],
            )
        except Exception as e:
            logger.error("alert_v2 loop error: %s", e)
        _save_sent_state()
        _save_perf()
        time.sleep(LOOP_INTERVAL_SEC)


def start() -> bool:
    global _running, _thread, _config
    if _running:
        return False
    _config = AlertV2Config.load()
    _config.scan_interval_sec = LOOP_INTERVAL_SEC
    _load_sent_state()
    _load_perf()
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="alert-v2-loop")
    _thread.start()
    logger.info("alert_v2 started (mode=%s exchange=%s)", _config.mode, _config.exchange)
    return True


def stop() -> bool:
    global _running, _thread
    if not _running:
        return False
    _running = False
    if _thread:
        _thread.join(timeout=1.0)
        _thread = None
    logger.info("alert_v2 stopped")
    return True


def status() -> dict:
    return {
        "running": _running,
        "mode": _config.mode if _config else "shadow",
        "exchange": _config.exchange if _config else "upbit",
        "scan_interval_sec": LOOP_INTERVAL_SEC,
        "scan_count": _scan_count,
        "last_scan_at": _last_scan_at,
        "recent_reports": len(_reports),
    }


def get_config() -> AlertV2Config:
    return _config or AlertV2Config.load()


def update_config(data: dict) -> AlertV2Config:
    global _config
    if _config is None:
        _config = AlertV2Config.load()
    for k, v in data.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
    _config.scan_interval_sec = LOOP_INTERVAL_SEC
    _config.save()
    return _config


def get_reports() -> list[dict]:
    return list(_reports)


def get_performance() -> dict:
    open_items = list(_perf.get("open", []))
    closed_items = list(_perf.get("closed", []))
    pnls = [float(x.get("pnl_pct", 0.0)) for x in closed_items[:500]]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "open_count": len(open_items),
        "closed_count": len(closed_items),
        "closed_win_rate_pct": round(wins / max(1, len(pnls)) * 100.0, 2) if pnls else 0.0,
        "closed_avg_pnl_pct": round(float(pd.Series(pnls).mean()), 4) if pnls else 0.0,
        "open": open_items[:100],
        "closed": closed_items[:200],
    }
