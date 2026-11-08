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
