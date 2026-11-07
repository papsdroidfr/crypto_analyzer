import polars as pl

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
