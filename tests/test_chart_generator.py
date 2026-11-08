from datetime import date, datetime, timezone

import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl

from src.charts.chart_generator import MatplotlibChartGenerator
from src.interfaces import OHLCVData, Symbol, Timeframe


def test_plot_alert_flags_uses_direction_and_weekly_size():
    chart_generator = MatplotlibChartGenerator()
    frame = pd.DataFrame({
        "timestamp": [datetime(2026, 1, 1)],
        "open": [100.0],
        "high": [105.0],
        "low": [95.0],
        "close": [100.0],
    })
    dates = mdates.date2num(frame["timestamp"].values)
    figure, axis = plt.subplots()
    try:
        chart_generator._plot_alert_flags(
            axis,
            frame,
            dates,
            [
                (date(2026, 1, 1), "DLTEST"),
                (date(2026, 1, 1), "WLTEST"),
                (date(2026, 1, 1), "DSTEST"),
                (date(2026, 1, 1), "WSTEST"),
            ],
        )

        assert [collection.get_sizes()[0] for collection in axis.collections] == [
            55,
            220,
            55,
            220,
        ]
        assert [
            tuple(collection.get_facecolors()[0])
            for collection in axis.collections
        ] == [
            mcolors.to_rgba("#00BFFF"),
            mcolors.to_rgba("#FFD700"),
            mcolors.to_rgba("#E040FB"),
            mcolors.to_rgba("#FF8C00"),
        ]
        y_positions = [
            collection.get_offsets()[0][1] for collection in axis.collections
        ]
        assert y_positions[0] < 95
        assert y_positions[1] < y_positions[0]
        assert y_positions[2] > 105
        assert y_positions[3] > y_positions[2]
        assert len(axis.get_legend_handles_labels()[1]) == 4
    finally:
        plt.close(figure)


def test_plot_ohlcv_includes_sma_50():
    chart_generator = MatplotlibChartGenerator()
    frame = pd.DataFrame({
        "timestamp": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "sma_50": [99.0, 100.0],
    })
    figure, axis = plt.subplots()
    try:
        chart_generator._plot_ohlcv(axis, frame, [])

        assert "SMA 50" in axis.get_legend_handles_labels()[1]
    finally:
        plt.close(figure)


def test_generate_writes_chart_with_alert_flags(tmp_path):
    timestamps = [
        datetime(2026, 1, day, tzinfo=timezone.utc)
        for day in (1, 2, 3)
    ]
    frame = pl.DataFrame({
        "timestamp": timestamps,
        "open": [100.0, 101.0, 102.0],
        "high": [102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0],
        "volume": [10.0, 11.0, 12.0],
        "sma_7": [100.0, 100.5, 101.0],
        "sma_50": [99.0, 99.5, 100.0],
        "sma_200": [98.0, 98.5, 99.0],
        "rsi_7": [40.0, 50.0, 60.0],
        "rsi_14": [45.0, 55.0, 65.0],
    })
    data = OHLCVData(
        symbol=Symbol("BTCUSDC"),
        timeframe=Timeframe("1d", "1 jour", 3),
        df=frame,
    )
    output_path = tmp_path / "BTCUSDC_1d_simulation.png"

    generated_path = MatplotlibChartGenerator().generate(
        data,
        frame,
        str(output_path),
        alert_flags=[(date(2026, 1, 2), "DLTEST")],
    )

    assert generated_path == str(output_path)
    assert output_path.is_file()
    assert output_path.stat().st_size > 0

    image = plt.imread(output_path)
    assert image.size > 0
