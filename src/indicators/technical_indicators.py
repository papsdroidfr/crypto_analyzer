"""
technical_indicators.py — Calcul des indicateurs techniques avec Polars.

Indicateurs implémentés :
  - Moyennes mobiles simples  : SMA_7, SMA_30, SMA_200
  - RSI                       : RSI_7, RSI_14
  - MACD                      : macd_line, macd_signal, macd_hist
  - Bandes de Bollinger       : bb_upper, bb_middle, bb_lower, bb_width, bb_%b

Principe S  : une seule responsabilité, calculer des indicateurs.
Principe O  : chaque indicateur est une méthode privée → facile d'en ajouter.
Principe D  : dépend de IIndicatorCalculator (abstraction), pas d'un df concret.
"""

import logging

import polars as pl

from src.interfaces import IIndicatorCalculator, OHLCVData

logger = logging.getLogger(__name__)


class TechnicalIndicatorCalculator(IIndicatorCalculator):
    """
    Calcule l'ensemble des indicateurs techniques et retourne un nouveau
    DataFrame enrichi (les données originales ne sont pas mutées).
    """

    def calculate(self, data: OHLCVData) -> pl.DataFrame:
        df = data.df.clone()
        df = self._add_sma(df, 7)
        df = self._add_sma(df, 30)
        df = self._add_sma(df, 200)
        df = self._add_rsi(df, 7)
        df = self._add_rsi(df, 14)
        df = self._add_macd(df)
        df = self._add_bollinger(df)
        logger.debug(
            "Indicateurs calculés pour %d bougies (%d colonnes)",
            len(df), len(df.columns)
        )
        return df

    # ------------------------------------------------------------------
    # Moyennes mobiles simples
    # ------------------------------------------------------------------

    def _add_sma(self, df: pl.DataFrame, period: int) -> pl.DataFrame:
        col_name = f"sma_{period}"
        return df.with_columns(
            pl.col("close")
              .rolling_mean(window_size=period)
              .alias(col_name)
        )

    # ------------------------------------------------------------------
    # RSI — Relative Strength Index (méthode Wilder / EMA lissée)
    # ------------------------------------------------------------------

    def _add_rsi(self, df: pl.DataFrame, period: int) -> pl.DataFrame:
        col_name = f"rsi_{period}"
        close = df["close"].to_list()
        n = len(close)
        rsi_values: list[float | None] = [None] * n

        if n < period + 1:
            return df.with_columns(
                pl.lit(None).cast(pl.Float64).alias(col_name)
            )

        # Variations journalières
        deltas = [close[i] - close[i - 1] for i in range(1, n)]
        gains  = [max(d, 0.0) for d in deltas]
        losses = [abs(min(d, 0.0)) for d in deltas]

        # Moyennes initiales (SMA sur `period` premières valeurs)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        def _rsi(ag: float, al: float) -> float:
            if al == 0:
                return 100.0
            rs = ag / al
            return 100.0 - (100.0 / (1.0 + rs))

        rsi_values[period] = _rsi(avg_gain, avg_loss)

        # Lissage Wilder
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rsi_values[i + 1] = _rsi(avg_gain, avg_loss)

        return df.with_columns(
            pl.Series(name=col_name, values=rsi_values)
        )

    # ------------------------------------------------------------------
    # MACD (12, 26, 9)
    # ------------------------------------------------------------------

    def _add_macd(
        self,
        df: pl.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pl.DataFrame:
        close = df["close"]

        ema_fast   = self._ema_series(close, fast)
        ema_slow   = self._ema_series(close, slow)
        macd_line  = [
            (f - s) if f is not None and s is not None else None
            for f, s in zip(ema_fast, ema_slow)
        ]
        macd_signal = self._ema_series(pl.Series(macd_line), signal)
        macd_hist   = [
            (m - s) if m is not None and s is not None else None
            for m, s in zip(macd_line, macd_signal)
        ]

        return df.with_columns([
            pl.Series(name="macd_line",   values=macd_line),
            pl.Series(name="macd_signal", values=macd_signal),
            pl.Series(name="macd_hist",   values=macd_hist),
        ])

    @staticmethod
    def _ema_series(
        series: pl.Series,
        period: int,
    ) -> list[float | None]:
        """EMA récursive. Retourne une list Python (compatible pl.Series)."""
        values = series.to_list()
        result: list[float | None] = [None] * len(values)
        k = 2.0 / (period + 1)
        # Cherche le premier index non-None pour initialiser
        start = next((i for i, v in enumerate(values) if v is not None), None)
        if start is None or start + period > len(values):
            return result

        # Valeur initiale = SMA des `period` premières valeurs non-None
        valid_start = [v for v in values[start:start + period] if v is not None]
        if len(valid_start) < period:
            return result

        ema = sum(valid_start) / period
        result[start + period - 1] = ema

        for i in range(start + period, len(values)):
            if values[i] is not None:
                ema = values[i] * k + ema * (1 - k)
                result[i] = ema

        return result

    # ------------------------------------------------------------------
    # Bandes de Bollinger (20, 2σ)
    # ------------------------------------------------------------------

    def _add_bollinger(
        self,
        df: pl.DataFrame,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> pl.DataFrame:
        middle = pl.col("close").rolling_mean(window_size=period).alias("bb_middle")
        std    = pl.col("close").rolling_std(window_size=period)

        df = df.with_columns([
            middle,
            (pl.col("close").rolling_mean(window_size=period) + std_dev * std)
              .alias("bb_upper"),
            (pl.col("close").rolling_mean(window_size=period) - std_dev * std)
              .alias("bb_lower"),
        ])

        # Largeur et %B
        df = df.with_columns([
            ((pl.col("bb_upper") - pl.col("bb_lower")) / pl.col("bb_middle"))
              .alias("bb_width"),
            ((pl.col("close") - pl.col("bb_lower")) /
             (pl.col("bb_upper") - pl.col("bb_lower")))
              .alias("bb_pct_b"),
        ])

        return df
