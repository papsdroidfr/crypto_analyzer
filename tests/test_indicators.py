import polars as pl

from src.indicators.technical_indicators import TechnicalIndicatorCalculator
from src.interfaces import OHLCVData, Symbol, Timeframe


def make_ohlcv(n=40):
    # Simple increasing close series
    close = [float(i + 1) for i in range(n)]
    df = pl.DataFrame({
        "timestamp": list(range(n)),
        "open": close,
        "high": [c + 0.5 for c in close],
        "low": [c - 0.5 for c in close],
        "close": close,
        "volume": [100.0] * n,
    })
    return df


def test_calculate_adds_columns():
    df = make_ohlcv(60)
    data = OHLCVData(symbol=Symbol("BTCUSDC"), timeframe=Timeframe("1d", "1d", 7), df=df)
    calc = TechnicalIndicatorCalculator()
    enriched = calc.calculate(data)
    # Expect indicator columns to exist
    for col in ["sma_7", "sma_30", "rsi_14", "macd_line", "bb_upper", "bb_pct_b"]:
        assert col in enriched.columns
    assert len(enriched) == len(df)
