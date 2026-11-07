from datetime import datetime, timedelta, timezone

import polars as pl

from src.alerts.alert_rules import build_default_registry
from src.alerts.alert_simulator import AlertSimulator
from src.indicators.technical_indicators import TechnicalIndicatorCalculator
from src.interfaces import OHLCVData


class FakeFetcher:
    def __init__(self, daily_df: pl.DataFrame, weekly_df: pl.DataFrame):
        self._frames = {"1d": daily_df, "1w": weekly_df}
        self.calls = []

    def fetch(self, symbol, timeframe, limit):
        self.calls.append((symbol.value, timeframe.value, limit))
        return OHLCVData(
            symbol=symbol,
            timeframe=timeframe,
            df=self._frames[timeframe.value],
        )


def make_ohlcv(timestamps: list[datetime]) -> pl.DataFrame:
    return pl.DataFrame({
        "timestamp": timestamps,
        "open": [100.0] * len(timestamps),
        "high": [101.0] * len(timestamps),
        "low": [99.0] * len(timestamps),
        "close": [100.0] * len(timestamps),
        "volume": [1.0] * len(timestamps),
    })


def test_simulate_returns_daily_and_weekly_alerts_without_notifications(capsys):
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    daily_timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
        for day in range(32)
    ]
    weekly_timestamps = [
        datetime(2026, 1, 5, tzinfo=timezone.utc) + timedelta(weeks=week)
        for week in range(4)
    ]
    fetcher = FakeFetcher(
        make_ohlcv(daily_timestamps),
        make_ohlcv(weekly_timestamps),
    )
    config = {
        "symbols": ["BTCUSDC", "ETHUSDC"],
        "timeframes": [
            {"value": "1d", "label": "1 jour", "candles_chart": 30},
            {"value": "1w", "label": "1 semaine", "candles_chart": 10},
        ],
        "alert_daily": [{
            "id": "DTEST",
            "name": "daily_positive_close",
            "type": "threshold",
            "timeframes": ["1d"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 0,
            }],
        }],
        "alert_weekly": [{
            "id": "WTEST",
            "name": "weekly_positive_close",
            "type": "threshold",
            "timeframes": ["1w"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 0,
            }],
        }],
    }

    simulator = AlertSimulator(
        fetcher=fetcher,
        calculator=TechnicalIndicatorCalculator(),
        rule_registry=build_default_registry(),
        config=config,
    )

    result = simulator.simulate(now=now)

    assert result.columns == ["date", "symbol", "alert_id"]
    assert result.schema == {
        "date": pl.Date,
        "symbol": pl.String,
        "alert_id": pl.String,
    }
    daily_results = result.filter(pl.col("alert_id") == "DTEST")
    weekly_results = result.filter(pl.col("alert_id") == "WTEST")
    assert len(daily_results) == 60
    assert daily_results["date"].min() == datetime(2026, 1, 2).date()
    assert daily_results["date"].max() == datetime(2026, 1, 31).date()
    assert len(weekly_results) == 6
    assert set(weekly_results["date"].to_list()) == {
        datetime(2026, 1, 11).date(),
        datetime(2026, 1, 18).date(),
        datetime(2026, 1, 25).date(),
    }
    assert fetcher.calls == [
        (symbol, timeframe, 250)
        for symbol in ("BTCUSDC", "ETHUSDC")
        for timeframe in ("1d", "1w")
    ]
    assert "Simulation terminée : 66 alerte(s) trouvée(s)." in capsys.readouterr().out


def test_simulate_returns_typed_empty_dataframe():
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    empty_daily = make_ohlcv([])
    empty_weekly = make_ohlcv([])
    fetcher = FakeFetcher(empty_daily, empty_weekly)
    config = {
        "symbols": ["BTCUSDC"],
        "alert_daily": [],
        "alert_weekly": [],
    }

    # No data is needed when no alert rules are configured.
    result = AlertSimulator(
        fetcher=fetcher,
        calculator=TechnicalIndicatorCalculator(),
        rule_registry=build_default_registry(),
        config=config,
    ).simulate(now=now)

    assert result.is_empty()
    assert result.schema == {
        "date": pl.Date,
        "symbol": pl.String,
        "alert_id": pl.String,
    }


def test_simulate_includes_last_closed_weekly_candle_before_period():
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    daily_timestamps = [
        datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(days=day)
        for day in range(30)
    ]
    weekly_timestamps = [
        datetime(2025, 12, 22, tzinfo=timezone.utc),
        datetime(2025, 12, 29, tzinfo=timezone.utc),
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        datetime(2026, 1, 12, tzinfo=timezone.utc),
    ]
    config = {
        "symbols": ["BTCUSDC"],
        "alert_daily": [{
            "id": "DTEST",
            "type": "threshold",
            "timeframes": ["1d"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 0,
            }],
        }],
        "alert_weekly": [{
            "id": "WTEST",
            "type": "threshold",
            "timeframes": ["1w"],
            "conditions": [{
                "indicator": "close",
                "operator": ">",
                "value": 0,
            }],
        }],
    }

    result = AlertSimulator(
        fetcher=FakeFetcher(
            make_ohlcv(daily_timestamps),
            make_ohlcv(weekly_timestamps),
        ),
        calculator=TechnicalIndicatorCalculator(),
        rule_registry=build_default_registry(),
        config=config,
    ).simulate(now=now)

    assert result.filter(pl.col("alert_id") == "WTEST")["date"].to_list() == [
        datetime(2025, 12, 28).date(),
        datetime(2026, 1, 4).date(),
        datetime(2026, 1, 11).date(),
        datetime(2026, 1, 18).date(),
    ]
    assert result.row(0, named=True) == {
        "date": datetime(2025, 12, 28).date(),
        "symbol": "BTCUSDC",
        "alert_id": "WTEST",
    }
