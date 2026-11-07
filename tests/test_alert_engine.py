import polars as pl
from src.alerts.alert_engine import AlertEngine
from src.alerts.alert_rules import build_default_registry
from src.interfaces import OHLCVData, Symbol, Timeframe


class FakeFetcher:
    def __init__(self, df):
        self._df = df

    def fetch(self, symbol, timeframe, limit=0):
        return OHLCVData(symbol=symbol, timeframe=timeframe, df=self._df)


class FakeCalculator:
    def __init__(self, enriched_df):
        self._enriched = enriched_df

    def calculate(self, data):
        return self._enriched


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.sent_charts = []

    def send(self, alert):
        self.sent.append(alert)

    def send_chart(self, alert, chart_path):
        self.sent_charts.append((alert, chart_path))


class FakeChartGen:
    def generate(self, data, enriched, output_path):
        return output_path


def test_run_daily_uses_alert_daily_config():
    enriched = pl.DataFrame({"close": [100.0, 104.0]})
    fetcher = FakeFetcher(enriched)
    calc = FakeCalculator(enriched)
    notifier = FakeNotifier()
    charts = FakeChartGen()
    config = {
        "symbols": ["BTCUSDC"],
        "timeframes": [{"value": "1d", "label": "1 jour", "candles_chart": 60}],
        "alerts": [],
        "alert_daily": [{
            "name": "daily_close_threshold",
            "type": "threshold",
            "timeframes": ["1d"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 102,
            }],
            "severity": "WARNING",
        }],
    }

    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)

    alerts = engine.run_daily()

    assert len(alerts) == 1
    assert alerts[0].rule_name == "daily_close_threshold"


def test_run_hourly_triggers_and_sends_chart():
    # create enriched df with two close values causing >3% variation
    enriched = pl.DataFrame({"close": [100.0, 104.0]})
    fetch_df = pl.DataFrame({"close": [100.0, 104.0, 105.0]})

    fetcher = FakeFetcher(fetch_df)
    calc = FakeCalculator(enriched)
    notifier = FakeNotifier()
    charts = FakeChartGen()

    config = {"symbols": ["BTCUSDC"]}
    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)
    alerts = engine.run_hourly()
    assert len(alerts) >= 1
    assert len(notifier.sent_charts) >= 1


def test_run_hourly_uses_configured_alert_rules():
    enriched = pl.DataFrame({"close": [100.0, 104.0]})
    fetcher = FakeFetcher(enriched)
    calc = FakeCalculator(enriched)
    notifier = FakeNotifier()
    charts = FakeChartGen()
    config = {
        "symbols": ["BTCUSDC"],
        "timeframes": [{"value": "1h", "label": "1 heure", "candles_chart": 48}],
        "alert_hourly": [{
            "name": "hourly_close_threshold",
            "type": "threshold",
            "timeframes": ["1h"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 102,
            }],
            "severity": "CRITICAL",
        }],
    }

    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)

    alerts = engine.run_hourly()

    assert len(alerts) == 1
    assert alerts[0].rule_name == "hourly_close_threshold"
    assert alerts[0].severity == "CRITICAL"
    assert len(notifier.sent_charts) == 1


def test_run_weekly_alert_checks_previous_macd_and_current_bullish_candle():
    enriched = pl.DataFrame({
        "macd_line": [1.5, 1.0],
        "open": [100.0, 100.0],
        "close": [99.0, 101.0],
    })
    fetcher = FakeFetcher(enriched)
    calc = FakeCalculator(enriched)
    notifier = FakeNotifier()
    charts = FakeChartGen()
    weekly_alert = {
        "name": "weekly_macd_bullish_candle",
        "type": "threshold",
        "timeframes": ["1w"],
        "severity": "WARNING",
        "message_tpl": "MACD précédent={macd_line_1}, MACD={macd_line}",
        "conditions": [
            {
                "left": {"indicator": "macd_line", "offset": 1},
                "operator": ">",
                "right": {"indicator": "macd_line", "offset": 0},
            },
            {
                "left": {"indicator": "close", "offset": 0},
                "operator": ">",
                "right": {"indicator": "open", "offset": 0},
            },
        ],
    }
    config = {
        "symbols": ["BTCUSDC"],
        "timeframes": [{"value": "1w", "label": "1 semaine", "candles_chart": 26}],
        "alert_weekly": [weekly_alert],
    }
    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)

    alerts = engine.run_weekly()

    assert len(alerts) == 1
    assert alerts[0].rule_name == "weekly_macd_bullish_candle"
    assert "1.5000" in alerts[0].message
    assert len(notifier.sent_charts) == 1


def test_run_weekly_does_not_trigger_when_either_condition_fails():
    alert_config = {
        "name": "weekly_macd_bullish_candle",
        "type": "threshold",
        "timeframes": ["1w"],
        "conditions": [
            {
                "left": {"indicator": "macd_line", "offset": 1},
                "operator": ">",
                "right": {"indicator": "macd_line", "offset": 0},
            },
            {
                "left": {"indicator": "close", "offset": 0},
                "operator": ">",
                "right": {"indicator": "open", "offset": 0},
            },
        ],
    }
    for enriched in (
        pl.DataFrame({"macd_line": [1.0, 1.5], "open": [100.0, 100.0], "close": [99.0, 101.0]}),
        pl.DataFrame({"macd_line": [1.5, 1.0], "open": [100.0, 102.0], "close": [99.0, 101.0]}),
    ):
        engine = AlertEngine(
            FakeFetcher(enriched),
            FakeCalculator(enriched),
            FakeNotifier(),
            FakeChartGen(),
            build_default_registry(),
            {
                "symbols": ["BTCUSDC"],
                "timeframes": [{"value": "1w", "label": "1 semaine"}],
                "alert_weekly": [alert_config],
            },
        )

        assert engine.run_weekly() == []


def test_build_timeframes_filters_hourly():
    fetcher = FakeFetcher(pl.DataFrame({"close": [1, 2, 3, 4]}))
    calc = FakeCalculator(pl.DataFrame({"close": [1, 2, 3, 4]}))
    notifier = FakeNotifier()
    charts = FakeChartGen()
    config = {
        "symbols": ["X"],
        "timeframes": [
            {"value": "1h", "label": "1h"},
            {"value": "1d", "label": "1d"},
            {"value": "1w", "label": "1w"},
        ],
    }
    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)
    tfs = engine._build_timeframes(daily=True)
    # The daily engine should leave hourly and weekly timeframes to their engines.
    assert all(tf.value != "1h" for tf in tfs)
    assert all(tf.value != "1w" for tf in tfs)
