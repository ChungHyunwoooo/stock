"""트레이딩 대시보드 자동 검증 — API, HTML, JS, 에러 시나리오.

브라우저 없이 대부분의 문제를 잡음.
실행: .venv/bin/python -m pytest tests/test_trading_dashboard.py -v
"""

import re

import pytest
from fastapi.testclient import TestClient

from engine.interfaces.trading_dashboard.app import app

client = TestClient(app)


class TestHTMLIntegrity:
    """HTML 템플릿 완결성."""

    def test_index_returns_200(self):
        r = client.get("/")
        assert r.status_code == 200

    def test_html_complete(self):
        html = client.get("/").text
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_html_has_chart_div(self):
        assert 'id="chart"' in client.get("/").text

    def test_html_has_rsi_chart(self):
        assert 'id="rsi-chart"' in client.get("/").text

    def test_html_has_symbol_search(self):
        assert 'id="symbol-search"' in client.get("/").text

    def test_html_has_history_panel(self):
        assert 'id="history-panel"' in client.get("/").text

    def test_lightweight_charts_loaded(self):
        assert "lightweight-charts" in client.get("/").text

    def test_favicon_inline(self):
        assert "data:image/svg+xml" in client.get("/").text


class TestJSSyntax:
    """JS 코드 문법 검증."""

    @pytest.fixture
    def js_code(self):
        html = client.get("/").text
        start = html.find("<script>")
        end = html.rfind("</script>")
        return html[start + 8:end]

    def test_braces_balanced(self, js_code):
        assert js_code.count("{") == js_code.count("}")

    def test_parens_balanced(self, js_code):
        assert js_code.count("(") == js_code.count(")")

    def test_brackets_balanced(self, js_code):
        assert js_code.count("[") == js_code.count("]")

    def test_no_inline_onclick_with_quotes(self, js_code):
        """onclick에 JSON.stringify 충돌 없어야 (data 속성 방식 사용)."""
        assert 'onclick="jumpToTrade(' not in js_code
        assert 'onclick="switchToSymbol(' not in js_code

    def test_currentTF_initialized(self, js_code):
        assert "currentTF = '1h'" in js_code or 'currentTF = "1h"' in js_code

    def test_currentSymbol_initialized(self, js_code):
        assert "currentSymbol = 'BTC/USDT'" in js_code or 'currentSymbol = "BTC/USDT"' in js_code

    def test_tf_buttons_scoped(self, js_code):
        """TF 버튼이 .tf-buttons로 범위 제한."""
        assert ".tf-buttons .tf-btn" in js_code

    def test_functions_defined(self, js_code):
        required = [
            "loadCandles", "connectWS", "renderCandles",
            "loadState", "loadAltState", "loadHistory",
            "switchToSymbol", "jumpToTrade", "toggleHistory",
            "filterHistory", "updateSyncTime",
        ]
        for fn in required:
            assert f"function {fn}" in js_code or f"{fn} =" in js_code, \
                f"함수 미정의: {fn}"

    def test_event_delegation_history(self, js_code):
        """히스토리 테이블에 이벤트 위임 사용."""
        assert "history-tbody" in js_code
        assert "addEventListener" in js_code

    def test_no_hardcoded_api_undefined(self, js_code):
        """API 호출에 리터럴 undefined 없어야."""
        api_patterns = re.findall(r"/api/candles/['\"]?(\w+)", js_code)
        for p in api_patterns:
            assert p != "undefined", f"API URL에 undefined 하드코딩"


class TestAPIEndpoints:
    """모든 API 엔드포인트."""

    def test_candles_1h(self):
        r = client.get("/api/candles/1h?limit=3&symbol=BTC/USDT")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            c = data[0]
            for key in ["time", "open", "high", "low", "close", "volume", "ema20", "rsi"]:
                assert key in c, f"캔들에 {key} 없음"

    def test_candles_invalid_tf_fallback(self):
        r = client.get("/api/candles/undefined?limit=2&symbol=BTC/USDT")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_candles_all_timeframes(self):
        for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            r = client.get(f"/api/candles/{tf}?limit=2&symbol=BTC/USDT")
            assert r.status_code == 200, f"TF {tf} 실패"

    def test_state(self):
        r = client.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        for key in ["position", "fr_zscore", "last_updated", "trade_log", "fr_history_len"]:
            assert key in data, f"state에 {key} 없음"

    def test_alt_state(self):
        r = client.get("/api/alt_state")
        assert r.status_code == 200
        data = r.json()
        for key in ["positions", "position_count", "trade_log", "total_trades"]:
            assert key in data, f"alt_state에 {key} 없음"

    def test_symbols(self):
        r = client.get("/api/symbols")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "BTC/USDT" in data
        assert len(data) > 1

    def test_history(self):
        r = client.get("/api/history")
        assert r.status_code == 200
        data = r.json()
        assert "trades" in data
        assert "stats" in data
        for key in ["total", "wins", "losses", "win_rate", "cumulative"]:
            assert key in data["stats"], f"stats에 {key} 없음"


class TestAPIEdgeCases:
    """에러 시나리오."""

    def test_candles_large_limit(self):
        r = client.get("/api/candles/1h?limit=1000&symbol=BTC/USDT")
        assert r.status_code == 200

    def test_candles_different_symbols(self):
        for sym in ["ETH/USDT", "SOL/USDT", "SUI/USDT"]:
            r = client.get(f"/api/candles/1h?limit=2&symbol={sym}")
            assert r.status_code == 200, f"{sym} 실패"

    def test_ema_precision_small_coin(self):
        """소형 코인 EMA가 round(2)되지 않아야."""
        r = client.get("/api/candles/1h?limit=5&symbol=PARTI/USDT")
        if r.status_code == 200:
            data = r.json()
            for c in data:
                if c.get("ema20") is not None:
                    ema_str = str(c["ema20"])
                    # 소수점 3자리 이상이어야 (round(2) 아님)
                    if "." in ema_str:
                        decimals = len(ema_str.split(".")[1])
                        assert decimals > 2, f"EMA 정밀도 부족: {c['ema20']}"
                    break
