
import json
import time
from unittest.mock import patch

from engine.data import provider_crypto

def test_load_exchange_symbols_reads_fresh_file_cache(tmp_path):
    cache_dir = tmp_path / 'exchange_symbol_cache'
    cache_dir.mkdir(parents=True)
    path = cache_dir / 'binance.json'
    path.write_text(json.dumps({'cached_at': time.time(), 'symbols': ['BTC/USDT', 'ETH/USDT']}))

    with patch.object(provider_crypto, '_SYMBOL_CACHE_DIR', cache_dir):
        symbols = provider_crypto.load_exchange_symbols('binance')

    assert symbols == ['BTC/USDT', 'ETH/USDT']
