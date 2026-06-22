import polars as pl
from datetime import timezone

from src.alerts.alert_rules import (
    ThresholdAlertRule,
    HourlyVariationRule,
    build_default_registry,
)
from src.interfaces import Symbol, Timeframe


def make_df(values, columns=None):
    if columns is None:
        columns = ["close"]
    data = {columns[0]: values}
    return pl.DataFrame(data)


def test_threshold_alert_triggers():
    df = make_df([10, 20, 80], columns=["rsi_14"])  # last = 80
    rule = ThresholdAlertRule("rsi_high")
    symbol = Symbol("BTCUSDC")
    tf = Timeframe(value="1d", label="1d", candles_chart=7)

    params = {
        "conditions": [{"indicator": "rsi_14", "operator": ">", "value": 70}],
        "severity": "CRITICAL",
    }
    alert = rule.evaluate(symbol, tf, df, params)
    assert alert is not None
    assert alert.severity == "CRITICAL"


def test_threshold_no_conditions_returns_none():
    df = make_df([1, 2, 3], columns=["rsi_14"]) 
    rule = ThresholdAlertRule("empty")
    symbol = Symbol("X")
    tf = Timeframe(value="1d", label="1d", candles_chart=7)
    alert = rule.evaluate(symbol, tf, df, {"conditions": []})
    assert alert is None


def test_hourly_variation_triggers():
    df = pl.DataFrame({"close": [100.0, 104.0]})
    rule = HourlyVariationRule()
    symbol = Symbol("ETHUSDC")
    tf = Timeframe(value="1h", label="1h", candles_chart=48)
    params = {"threshold_pct": 3.0, "severity": "WARNING"}
    alert = rule.evaluate(symbol, tf, df, params)
    assert alert is not None
    assert "Variation horaire" in alert.message or "%" in alert.message


def test_registry_build_default():
    registry = build_default_registry()
    r = registry.build("threshold")
    assert isinstance(r, ThresholdAlertRule)
