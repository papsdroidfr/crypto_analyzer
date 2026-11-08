import json
from types import SimpleNamespace

import polars as pl
import pytest

from src.engine import runner
from src.engine.runner import _print_simulation_results


def test_print_simulation_results_separates_weekly_and_daily(capsys):
    result = pl.DataFrame({
        "date": [None, None],
        "symbol": ["BTCUSDC", "ETHUSDC"],
        "alert_id": ["WTEST", "DTEST"],
    })

    _print_simulation_results(result)

    output = capsys.readouterr().out
    weekly_section, daily_section = output.split(
        "Alertes quotidiennes (daily) :"
    )
    assert "Alertes hebdomadaires (weekly) :" in weekly_section
    assert "WTEST" in weekly_section
    assert "DTEST" not in weekly_section
    assert "DTEST" in daily_section
    assert "WTEST" not in daily_section


@pytest.mark.parametrize("command", ["daily", "hourly", "weekly"])
def test_build_engine_uses_command_specific_webhook(monkeypatch, command):
    webhook_urls = {
        "daily": "https://example/daily",
        "hourly": "https://example/hourly",
        "weekly": "https://example/weekly",
    }
    config = {"discord": {"webhook_urls": webhook_urls}}

    monkeypatch.setattr(
        "src.config_loader.JsonConfigLoader.load",
        lambda self: config,
    )
    monkeypatch.setattr(
        "src.notifiers.discord_notifier.DiscordNotifier",
        lambda webhook_url, username: type(
            "Notifier", (), {"webhook_url": webhook_url}
        )(),
    )
    monkeypatch.setattr(
        "src.alerts.alert_engine.AlertEngine",
        lambda **dependencies: dependencies,
    )
    monkeypatch.setattr(
        "src.fetchers.binance_fetcher.BinanceFetcher", lambda: None
    )
    monkeypatch.setattr(
        "src.indicators.technical_indicators.TechnicalIndicatorCalculator",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.charts.chart_generator.MatplotlibChartGenerator", lambda: None
    )

    engine_dependencies = runner._build_engine(command=command)

    assert engine_dependencies["notifier"].webhook_url == webhook_urls[command]


def test_build_engine_no_notifier_ignores_invalid_discord_settings(
    monkeypatch, tmp_path
):
    config = {
        "symbols": ["BTCUSDC"],
        "timeframes": [],
        "discord": {"channel_ids": {"daily": "not-a-channel-id"}},
        "alert_daily": [],
    }
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setattr(
        "src.alerts.alert_engine.AlertEngine",
        lambda **dependencies: dependencies,
    )
    monkeypatch.setattr(
        "src.fetchers.binance_fetcher.BinanceFetcher", lambda: None
    )
    monkeypatch.setattr(
        "src.indicators.technical_indicators.TechnicalIndicatorCalculator",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.charts.chart_generator.MatplotlibChartGenerator", lambda: None
    )
    monkeypatch.setattr(
        "src.notifiers.discord_notifier.DiscordNotifier",
        lambda **kwargs: pytest.fail("DiscordNotifier must not be constructed"),
    )

    engine_dependencies = runner._build_engine(
        str(config_path), no_notifier=True, command="daily"
    )

    assert isinstance(engine_dependencies["notifier"], runner.NullNotifier)


def test_cmd_simulate_ignores_invalid_discord_settings(monkeypatch, tmp_path):
    config = {
        "symbols": ["BTCUSDC"],
        "timeframes": [],
        "discord": {"channel_ids": {"daily": "not-a-channel-id"}},
        "alert_daily": [],
        "alert_weekly": [],
    }
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    class FakeSimulator:
        def __init__(self, *, config, **dependencies):
            self.config = config

        def simulate(self):
            return pl.DataFrame(
                schema={
                    "date": pl.Date,
                    "symbol": pl.String,
                    "alert_id": pl.String,
                }
            )

    monkeypatch.setattr(
        "src.alerts.alert_simulator.AlertSimulator", FakeSimulator
    )
    monkeypatch.setattr(
        "src.fetchers.binance_fetcher.BinanceFetcher", lambda: None
    )
    monkeypatch.setattr(
        "src.indicators.technical_indicators.TechnicalIndicatorCalculator",
        lambda: None,
    )

    result = runner.cmd_simulate(SimpleNamespace(config=str(config_path)))

    assert result.is_empty()
