"""
interfaces.py — Contrats abstraits du système (principes I et D de SOLID).
Toutes les dépendances pointent vers ces abstractions, jamais vers des concrets.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
import polars as pl


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Symbol:
    """Paire de cryptomonnaies (ex: BTCUSDC)."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Timeframe:
    """Période OHLCV (ex: '1d', '1h', '1w')."""
    value: str
    label: str          # Libellé lisible, ex: "24h", "7 jours"
    candles_chart: int  # Nombre de bougies à afficher sur le graphique

    def __str__(self) -> str:
        return self.value


@dataclass
class OHLCVData:
    """Conteneur de données OHLCV brutes."""
    symbol: Symbol
    timeframe: Timeframe
    df: pl.DataFrame    # colonnes: timestamp, open, high, low, close, volume


@dataclass
class Alert:
    """Alerte générée par le moteur."""
    symbol: Symbol
    timeframe: Timeframe
    rule_name: str
    message: str
    triggered_at: datetime
    severity: str = "INFO"   # INFO | WARNING | CRITICAL
    chart_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------

class IDataFetcher(ABC):
    """Responsabilité : récupérer les données OHLCV depuis une source externe."""

    @abstractmethod
    def fetch(self, symbol: Symbol, timeframe: Timeframe, limit: int) -> OHLCVData:
        """Retourne un OHLCVData avec au moins `limit` bougies."""
        ...


class IIndicatorCalculator(ABC):
    """Responsabilité : enrichir un DataFrame avec des indicateurs techniques."""

    @abstractmethod
    def calculate(self, data: OHLCVData) -> pl.DataFrame:
        """
        Retourne le DataFrame enrichi avec les colonnes d'indicateurs.
        Ne modifie pas le DataFrame original (immutabilité Polars).
        """
        ...


class IAlertRule(ABC):
    """Responsabilité : évaluer une règle d'alerte sur un snapshot enrichi."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifiant unique de la règle."""
        ...

    @abstractmethod
    def evaluate(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        enriched_df: pl.DataFrame,
        params: dict[str, Any],
    ) -> Optional[Alert]:
        """Retourne une Alert si la règle est déclenchée, None sinon."""
        ...


class INotifier(ABC):
    """Responsabilité : publier une alerte vers un canal externe."""

    @abstractmethod
    def send(self, alert: Alert) -> None:
        """Envoie l'alerte. Lève une exception en cas d'échec critique."""
        ...

    @abstractmethod
    def send_chart(self, alert: Alert, chart_path: str) -> None:
        """Envoie une alerte accompagnée d'un fichier graphique."""
        ...


class IChartGenerator(ABC):
    """Responsabilité : produire un fichier image à partir de données enrichies."""

    @abstractmethod
    def generate(
        self,
        data: OHLCVData,
        enriched_df: pl.DataFrame,
        output_path: str,
    ) -> str:
        """Génère le graphique et retourne le chemin du fichier produit."""
        ...


class IConfigLoader(ABC):
    """Responsabilité : charger et valider la configuration."""

    @abstractmethod
    def load(self) -> dict[str, Any]:
        ...
