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


def test_build_timeframes_filters_hourly():
    fetcher = FakeFetcher(pl.DataFrame({"close": [1, 2, 3, 4]}))
    calc = FakeCalculator(pl.DataFrame({"close": [1, 2, 3, 4]}))
    notifier = FakeNotifier()
    charts = FakeChartGen()
    config = {"symbols": ["X"], "timeframes": [{"value": "1h", "label": "1h"}, {"value": "1d", "label": "1d"}]}
    engine = AlertEngine(fetcher, calc, notifier, charts, build_default_registry(), config)
    tfs = engine._build_timeframes(daily=True)
    # daily=True should skip 1h
    assert all(tf.value != "1h" for tf in tfs)
