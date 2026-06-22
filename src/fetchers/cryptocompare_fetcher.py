"""
cryptocompare_fetcher.py — Récupération OHLCV via l'API gratuite CryptoCompare.

API choisie : CryptoCompare (https://min-api.cryptocompare.com)
  - Gratuite, sans clé pour les endpoints historiques de base
  - Supporte BTCUSDC, ETHUSDC, SOLUSD, TAOUSDC
  - Endpoints : /data/v2/histoday  /data/v2/histohour  /data/v2/histominute

Principe S : cette classe ne fait QUE fetcher, elle ne calcule rien.
Principe O : pour ajouter une autre source, on crée un nouveau fetcher sans
             modifier celui-ci.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import polars as pl
import requests

from src.interfaces import IDataFetcher, OHLCVData, Symbol, Timeframe

logger = logging.getLogger(__name__)

# Mapping timeframe.value → endpoint CryptoCompare
_ENDPOINT_MAP: dict[str, str] = {
    "1h":  "https://min-api.cryptocompare.com/data/v2/histohour",
    "1d":  "https://min-api.cryptocompare.com/data/v2/histoday",
    "1w":  "https://min-api.cryptocompare.com/data/v2/histoday",   # agrégé côté client
}

# Toutes les paires sont XXX/USDC ou XXX/USD
_QUOTE_OVERRIDE: dict[str, str] = {
    "SOLUSD":  "USD",
    "TAOUSDC": "USDC",
    "BTCUSDC": "USDC",
    "ETHUSDC": "USDC",
}


def _split_symbol(symbol: Symbol) -> tuple[str, str]:
    """Extrait (base, quote) depuis un symbole comme BTCUSDC."""
    raw = symbol.value.upper()
    quote = _QUOTE_OVERRIDE.get(raw)
    if quote:
        base = raw[: len(raw) - len(quote)]
        return base, quote
    # Heuristique générique : 3 ou 4 lettres pour la base
    for q in ("USDC", "USDT", "USD", "BTC", "ETH"):
        if raw.endswith(q):
            return raw[: -len(q)], q
    raise ValueError(f"Impossible de décomposer le symbole : {raw}")


class CryptoCompareFetcher(IDataFetcher):
    """
    Fetcher OHLCV s'appuyant sur l'API publique CryptoCompare.

    Pour la timeframe '1w', on récupère des bougies journalières puis on les
    resample en bougies hebdomadaires via Polars (évite la dépendance à un
    endpoint spécifique).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 15,
        retry: int = 3,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._retry = retry
        self._session = requests.Session()
        if api_key:
            self._session.headers["authorization"] = f"Apikey {api_key}"

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def fetch(self, symbol: Symbol, timeframe: Timeframe, limit: int) -> OHLCVData:
        logger.info("Fetch %s [%s] limit=%d", symbol, timeframe, limit)

        if timeframe.value == "1w":
            # On récupère limit * 7 + 6 jours pour couvrir limit semaines pleines
            raw_df = self._fetch_raw(symbol, "1d", limit * 7 + 6)
            df = self._resample_weekly(raw_df)
            # On garde exactement `limit` semaines
            df = df.tail(limit)
        else:
            raw_df = self._fetch_raw(symbol, timeframe.value, limit)
            df = raw_df.tail(limit)

        return OHLCVData(symbol=symbol, timeframe=timeframe, df=df)

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _fetch_raw(self, symbol: Symbol, tf_value: str, limit: int) -> pl.DataFrame:
        base, quote = _split_symbol(symbol)
        endpoint = _ENDPOINT_MAP[tf_value]
        params = {
            "fsym":  base,
            "tsym":  quote,
            "limit": min(limit, 2000),   # CryptoCompare max = 2000
        }

        data = self._get_with_retry(endpoint, params)
        candles = data["Data"]["Data"]

        df = pl.DataFrame({
            "timestamp": [datetime.fromtimestamp(c["time"], tz=timezone.utc) for c in candles],
            "open":      [float(c["open"])             for c in candles],
            "high":      [float(c["high"])             for c in candles],
            "low":       [float(c["low"])              for c in candles],
            "close":     [float(c["close"])            for c in candles],
            "volume":    [float(c["volumefrom"])       for c in candles],
        })

        # Supprime les bougies à volume 0 en début d'historique (actif jeune)
        df = df.filter(
            (pl.col("close") > 0) | (pl.col("volume") > 0)
        )
        return df

    def _resample_weekly(self, daily_df: pl.DataFrame) -> pl.DataFrame:
        """
        Regroupe des bougies journalières en bougies hebdomadaires (lundi→dimanche).
        Utilise le group_by_dynamic de Polars.
        """
        weekly = (
            daily_df
            .sort("timestamp")
            .group_by_dynamic("timestamp", every="1w", start_by="monday")
            .agg([
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
            ])
            .sort("timestamp")
        )
        return weekly

    def _get_with_retry(self, url: str, params: dict) -> dict:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._retry + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("Response") == "Error":
                    raise ValueError(f"API error : {payload.get('Message')}")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("Tentative %d/%d échouée (%s) — attente %ds",
                               attempt, self._retry, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Impossible de fetcher après {self._retry} tentatives") from last_exc
