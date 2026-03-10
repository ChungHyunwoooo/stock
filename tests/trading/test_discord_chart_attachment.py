
import json
from unittest.mock import MagicMock, patch

from engine.core import SignalAction, TradeSide, TradingSignal
from engine.notifications.discord_webhook import DiscordWebhookNotifier

def test_notifier_attaches_chart_when_available(tmp_path):
    config_path = tmp_path / 'discord.json'
    config_path.write_text(json.dumps({'webhook_url': 'https://discord.com/api/webhooks/default/token'}))
    notifier = DiscordWebhookNotifier(config_path)
    signal = TradingSignal(
        strategy_id='test:1.0',
        symbol='BTC/USDT',
        timeframe='15m',
        action=SignalAction.entry,
        side=TradeSide.long,
        entry_price=100.0,
        stop_loss=98.0,
        take_profits=[104.0],
    )

    with patch('engine.notifications.discord_webhook.build_signal_chart', return_value=b'png-bytes'), \
         patch('urllib.request.urlopen') as mock_urlopen:
        response = MagicMock()
        response.status = 204
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = response

        assert notifier.send_signal(signal, mode_label='alert_only') is True
        request = mock_urlopen.call_args[0][0]
        assert request.get_header('Content-type').startswith('multipart/form-data; boundary=')
        assert b'attachment://chart.png' in request.data
        assert b'files[0]' in request.data
