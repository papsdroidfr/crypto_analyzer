"""
chart_generator.py — Génération de graphiques OHLCV + indicateurs techniques.

Layout multi-panneaux :
  [1] Cours OHLCV (chandeliers) + SMA_7 / SMA_30 / SMA_200 + Bollinger
  [2] Volume
  [3] MACD (ligne + signal + histogramme)
  [4] RSI_7 et RSI_14

Principe S : responsabilité unique de production de fichier image.
Principe D : dépend de IChartGenerator, pas d'un concret.
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # Backend non-interactif obligatoire sur Raspberry Pi headless

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection

from src.interfaces import IChartGenerator, OHLCVData

logger = logging.getLogger(__name__)


class MatplotlibChartGenerator(IChartGenerator):
    """
    Génère un graphique PNG multi-panneaux lisible sur le nombre de bougies
    adapté à la période choisie (défini dans candles_chart du Timeframe).
    """

    def __init__(self, dpi: int = 150, figsize: tuple = (16, 12)) -> None:
        self._dpi     = dpi
        self._figsize = figsize

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def generate(
        self,
        data: OHLCVData,
        enriched_df: pl.DataFrame,
        output_path: str,
    ) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Nombre de bougies à afficher
        n_candles = data.timeframe.candles_chart
        df = enriched_df.tail(n_candles).to_pandas()
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)   # matplotlib ne gère pas tz

        title = (
            f"{data.symbol} — {data.timeframe.label} "
            f"| {len(df)} bougies | "
            f"Cours actuel : {df['close'].iloc[-1]:.4f}"
        )

        fig, axes = self._create_figure(title)
        self._plot_ohlcv(axes[0], df)
        self._plot_volume(axes[1], df)
        self._plot_macd(axes[2], df)
        self._plot_rsi(axes[3], df)

        # Synchronisation des axes X
        for ax in axes[:-1]:
            ax.set_xticklabels([])

        self._format_xaxis(axes[-1], df)

        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(output_path, dpi=self._dpi, bbox_inches="tight")
        plt.close(fig)

        logger.info("Graphique généré : %s (%d bougies)", output_path, len(df))
        return output_path

    # ------------------------------------------------------------------
    # Création de la figure
    # ------------------------------------------------------------------

    def _create_figure(self, title: str):
        fig, axes = plt.subplots(
            nrows=4,
            ncols=1,
            figsize=self._figsize,
            gridspec_kw={"height_ratios": [4, 1, 2, 1.5]},
            sharex=True,
        )
        fig.patch.set_facecolor("#1a1a2e")
        fig.suptitle(title, color="white", fontsize=13, fontweight="bold", y=0.99)

        for ax in axes:
            ax.set_facecolor("#16213e")
            ax.tick_params(colors="white", which="both")
            ax.spines["bottom"].set_color("#444")
            ax.spines["top"].set_color("#444")
            ax.spines["left"].set_color("#444")
            ax.spines["right"].set_color("#444")
            ax.yaxis.label.set_color("white")
            ax.xaxis.label.set_color("white")
            ax.grid(True, color="#2a2a4a", linewidth=0.5, linestyle="--")

        return fig, axes

    # ------------------------------------------------------------------
    # Panneau 1 : OHLCV + SMA + Bollinger
    # ------------------------------------------------------------------

    def _plot_ohlcv(self, ax, df) -> None:
        ax.set_ylabel("Prix", color="white")
        ax.set_title("OHLCV + Moyennes mobiles + Bollinger", color="#aaaacc", fontsize=9)

        dates = mdates.date2num(df["timestamp"].values)
        width  = (dates[1] - dates[0]) * 0.6 if len(dates) > 1 else 0.4
        width2 = width * 0.1

        for i, row in df.iterrows():
            color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
            # Corps de la bougie
            ax.add_patch(Rectangle(
                (dates[i] - width / 2, min(row["open"], row["close"])),
                width,
                abs(row["close"] - row["open"]),
                color=color,
                zorder=2,
            ))
            # Mèches
            ax.plot(
                [dates[i], dates[i]],
                [row["low"], row["high"]],
                color=color, linewidth=0.8, zorder=1,
            )

        # Moyennes mobiles
        for col, color, lw, label in [
            ("sma_7",   "#FFD700", 1.2, "SMA 7"),
            ("sma_30",  "#FF8C00", 1.2, "SMA 30"),
            ("sma_200", "#FF4500", 1.5, "SMA 200"),
        ]:
            if col in df.columns:
                mask = df[col].notna()
                ax.plot(
                    dates[mask], df[col][mask],
                    color=color, linewidth=lw, label=label, zorder=3,
                )

        # Bandes de Bollinger
        if "bb_upper" in df.columns:
            mask = df["bb_upper"].notna()
            ax.plot(dates[mask], df["bb_upper"][mask],
                    color="#7B68EE", linewidth=0.9, linestyle="--", label="BB upper", zorder=3)
            ax.plot(dates[mask], df["bb_middle"][mask],
                    color="#9370DB", linewidth=0.8, linestyle=":", label="BB mid", zorder=3)
            ax.plot(dates[mask], df["bb_lower"][mask],
                    color="#7B68EE", linewidth=0.9, linestyle="--", label="BB lower", zorder=3)
            ax.fill_between(
                dates[mask],
                df["bb_upper"][mask], df["bb_lower"][mask],
                alpha=0.07, color="#7B68EE",
            )

        ax.legend(
            loc="upper left", fontsize=7, framealpha=0.4,
            facecolor="#1a1a2e", labelcolor="white",
        )
        ax.set_xlim(dates[0] - width, dates[-1] + width)
        ax.xaxis_date()

    # ------------------------------------------------------------------
    # Panneau 2 : Volume
    # ------------------------------------------------------------------

    def _plot_volume(self, ax, df) -> None:
        ax.set_ylabel("Volume", color="white")
        dates = mdates.date2num(df["timestamp"].values)
        width = (dates[1] - dates[0]) * 0.6 if len(dates) > 1 else 0.4

        colors = ["#26a69a" if r["close"] >= r["open"] else "#ef5350"
                  for _, r in df.iterrows()]
        ax.bar(dates, df["volume"], width=width, color=colors, alpha=0.7)
        ax.set_xlim(dates[0] - width, dates[-1] + width)
        ax.xaxis_date()

    # ------------------------------------------------------------------
    # Panneau 3 : MACD
    # ------------------------------------------------------------------

    def _plot_macd(self, ax, df) -> None:
        ax.set_ylabel("MACD", color="white")
        if "macd_line" not in df.columns:
            return

        dates = mdates.date2num(df["timestamp"].values)
        mask  = df["macd_line"].notna()

        # Histogramme
        if "macd_hist" in df.columns:
            hist = df["macd_hist"][mask]
            colors = ["#26a69a" if v >= 0 else "#ef5350" for v in hist]
            width = (dates[1] - dates[0]) * 0.5 if len(dates) > 1 else 0.4
            ax.bar(dates[mask], hist, width=width, color=colors, alpha=0.7, label="Hist")

        ax.plot(dates[mask], df["macd_line"][mask],
                color="#0db8d9", linewidth=1.2, label="MACD")
        if "macd_signal" in df.columns:
            mask_s = df["macd_signal"].notna()
            ax.plot(dates[mask_s], df["macd_signal"][mask_s],
                    color="#ff6b6b", linewidth=1.0, label="Signal")

        ax.axhline(0, color="#555", linewidth=0.6, linestyle="-")
        ax.legend(loc="upper left", fontsize=7, framealpha=0.4,
                  facecolor="#1a1a2e", labelcolor="white")
        ax.xaxis_date()

    # ------------------------------------------------------------------
    # Panneau 4 : RSI
    # ------------------------------------------------------------------

    def _plot_rsi(self, ax, df) -> None:
        ax.set_ylabel("RSI", color="white")
        ax.set_ylim(0, 100)
        dates = mdates.date2num(df["timestamp"].values)

        for col, color, label in [
            ("rsi_7",  "#FFA500", "RSI 7"),
            ("rsi_14", "#00BFFF", "RSI 14"),
        ]:
            if col in df.columns:
                mask = df[col].notna()
                ax.plot(dates[mask], df[col][mask],
                        color=color, linewidth=1.0, label=label)

        # Zones de surachat / survente
        ax.axhline(70, color="#ef5350", linewidth=0.7, linestyle="--", alpha=0.7)
        ax.axhline(30, color="#26a69a", linewidth=0.7, linestyle="--", alpha=0.7)
        ax.fill_between(dates, 70, 100, alpha=0.07, color="#ef5350")
        ax.fill_between(dates, 0,  30,  alpha=0.07, color="#26a69a")
        ax.text(dates[-1], 72, "Surachat", color="#ef5350", fontsize=6, ha="right")
        ax.text(dates[-1], 25, "Survente",  color="#26a69a",  fontsize=6, ha="right")

        ax.legend(loc="upper left", fontsize=7, framealpha=0.4,
                  facecolor="#1a1a2e", labelcolor="white")
        ax.xaxis_date()

    # ------------------------------------------------------------------
    # Format axe X
    # ------------------------------------------------------------------

    def _format_xaxis(self, ax, df) -> None:
        n = len(df)
        if n <= 30:
            locator  = mdates.DayLocator(interval=1)
            fmt_str  = "%d/%m"
        elif n <= 90:
            locator  = mdates.WeekdayLocator(byweekday=0)
            fmt_str  = "%d/%m"
        elif n <= 365:
            locator  = mdates.MonthLocator()
            fmt_str  = "%b %Y"
        else:
            locator  = mdates.MonthLocator(interval=3)
            fmt_str  = "%b %Y"

        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt_str))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right",
                 color="white", fontsize=8)
