"""
binance_fetcher.py — Récupération OHLCV via l'API publique Binance.

API : https://api.binance.com/api/v3/klines
  - 100% gratuite, sans authentification
  - Limites : 1200 requêtes/minute
  - Intervalles supportés : 1h, 1d, 1w

Les symboles sont passés tels quels depuis settings.json (BTCUSDC, ETHUSDC…).

Principe S : cette classe ne fait QUE fetcher, elle ne calcule rien.
Principe O : pour ajouter une autre source, créer un nouveau fetcher sans
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

# Mapping timeframe interne → intervalle Binance
_INTERVAL_MAP: dict[str, str] = {
    "1h": "1h",
    "1d": "1d",
    "1w": "1w",
}

# Binance limite à 1000 bougies par requête
_MAX_LIMIT = 1000

_BASE_URL = "https://api.binance.com/api/v3/klines"


class BinanceFetcher(IDataFetcher):
    """
    Fetcher OHLCV s'appuyant sur l'API publique Binance (sans clé API).

    Pour les demandes > 1000 bougies, effectue plusieurs appels paginés
    et concatène les résultats avec Polars.
    """

    def __init__(self, timeout: int = 15, retry: int = 3) -> None:
        self._timeout = timeout
        self._retry   = retry
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def fetch(self, symbol: Symbol, timeframe: Timeframe, limit: int) -> OHLCVData:
        interval = self._resolve_interval(timeframe)
        logger.info("Fetch Binance %s [%s] limit=%d", symbol, interval, limit)

        df = self._fetch_paginated(symbol.value.upper(), interval, limit)

        # Exclure la bougie en cours (non clôturée)
        now_ms = int(time.time() * 1000)
        df = df.filter(pl.col("close_time") < now_ms).tail(limit).drop("close_time")

        return OHLCVData(symbol=symbol, timeframe=timeframe, df=df)

    # ------------------------------------------------------------------
    # Résolution de l'intervalle
    # ------------------------------------------------------------------

    def _resolve_interval(self, timeframe: Timeframe) -> str:
        interval = _INTERVAL_MAP.get(timeframe.value)
        if interval is None:
            raise ValueError(
                f"Timeframe '{timeframe.value}' non supportée. "
                f"Valeurs acceptées : {list(_INTERVAL_MAP.keys())}"
            )
        return interval

    # ------------------------------------------------------------------
    # Pagination (> 1000 bougies)
    # ------------------------------------------------------------------

    def _fetch_paginated(self, symbol: str, interval: str, limit: int) -> pl.DataFrame:
        if limit <= _MAX_LIMIT:
            return self._fetch_single(symbol, interval, limit)

        frames: list[pl.DataFrame] = []
        remaining = limit
        end_time_ms: Optional[int] = None

        while remaining > 0:
            batch    = min(remaining, _MAX_LIMIT)
            df_batch = self._fetch_single(symbol, interval, batch, end_time_ms)
            if df_batch.is_empty():
                break

            frames.append(df_batch)
            remaining  -= len(df_batch)
            end_time_ms = int(df_batch["timestamp"][0].timestamp() * 1000) - 1

            if len(df_batch) < batch:
                break

        if not frames:
            raise RuntimeError(f"Aucune donnée reçue de Binance pour {symbol} [{interval}]")

        return (
            pl.concat(list(reversed(frames)))
            .unique(subset=["timestamp"])
            .sort("timestamp")
        )

    # ------------------------------------------------------------------
    # Appel HTTP unique
    # ------------------------------------------------------------------

    def _fetch_single(
        self,
        symbol: str,
        interval: str,
        limit: int,
        end_time_ms: Optional[int] = None,
    ) -> pl.DataFrame:
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        raw = self._get_with_retry(params)

        if not raw:
            return pl.DataFrame(schema={
                "timestamp":  pl.Datetime("us", "UTC"),
                "open":       pl.Float64,
                "high":       pl.Float64,
                "low":        pl.Float64,
                "close":      pl.Float64,
                "volume":     pl.Float64,
                "close_time": pl.Int64,
            })

        # Format Binance : [open_time, open, high, low, close, volume, close_time, ...]
        return pl.DataFrame({
            "timestamp":  [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc) for k in raw],
            "open":       [float(k[1]) for k in raw],
            "high":       [float(k[2]) for k in raw],
            "low":        [float(k[3]) for k in raw],
            "close":      [float(k[4]) for k in raw],
            "volume":     [float(k[5]) for k in raw],
            "close_time": [int(k[6])   for k in raw],
        })

    # ------------------------------------------------------------------
    # HTTP avec retry + backoff exponentiel
    # ------------------------------------------------------------------

    def _get_with_retry(self, params: dict) -> list:
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._retry + 1):
            try:
                resp = self._session.get(_BASE_URL, params=params, timeout=self._timeout)

                if resp.status_code in (429, 418):
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning("Rate-limit Binance — attente %ds", retry_after)
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "[%s] Tentative %d/%d échouée (%s) — attente %ds",
                    params.get("symbol", "?"), attempt, self._retry, exc, wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"Impossible de fetcher {params.get('symbol')} après {self._retry} tentatives"
        ) from last_exc
