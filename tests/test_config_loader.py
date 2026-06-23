import json

import pytest

from src.config_loader import JsonConfigLoader


def test_load_valid_config(tmp_path):
    cfg = {
        "symbols": ["BTCUSDC"],
        "timeframes": [{"value": "1d", "label": "1d", "candles_chart": 7}],
        "discord": {"webhook": "https://example"},
        "alerts": [],
    }
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    loader = JsonConfigLoader(str(p))
    loaded = loader.load()
    assert isinstance(loaded, dict)
    assert loaded["symbols"] == ["BTCUSDC"]


def test_missing_file_raises():
    loader = JsonConfigLoader("/non/existent/config.json")
    with pytest.raises(FileNotFoundError):
        loader.load()


def test_missing_required_key_raises(tmp_path):
    cfg = {"timeframes": [], "discord": {}, "alerts": []}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    loader = JsonConfigLoader(str(p))
    with pytest.raises(ValueError):
        loader.load()


def test_invalid_symbols_or_alerts_types(tmp_path):
    cfg = {"symbols": "BTC", "timeframes": [], "discord": {}, "alerts": []}
    p = tmp_path / "bad2.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    loader = JsonConfigLoader(str(p))
    with pytest.raises(ValueError):
        loader.load()

    cfg2 = {"symbols": ["X"], "timeframes": [], "discord": {}, "alerts": {}}
    p2 = tmp_path / "bad3.json"
    p2.write_text(json.dumps(cfg2), encoding="utf-8")
    loader2 = JsonConfigLoader(str(p2))
    with pytest.raises(ValueError):
        loader2.load()
