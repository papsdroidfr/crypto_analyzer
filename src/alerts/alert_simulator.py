"""Simulation historique des alertes quotidiennes et hebdomadaires."""

from datetime import datetime, timedelta, timezone
from typing import Any

import polars as pl

from src.alerts.alert_rules import AlertRuleRegistry
from src.interfaces import IDataFetcher, IIndicatorCalculator, Symbol, Timeframe

_SIMULATED_TIMEFRAMES = (
    ("1d", "alert_daily", "D", 1),
    ("1w", "alert_weekly", "W", 7),
)
_LOOKBACK_DAYS = 30
_INDICATOR_WARMUP_CANDLES = 250


class AlertSimulator:
    """Évalue les règles quotidiennes et hebdomadaires sur les 30 derniers jours."""

    def __init__(
        self,
        fetcher: IDataFetcher,
        calculator: IIndicatorCalculator,
        rule_registry: AlertRuleRegistry,
        config: dict[str, Any],
    ) -> None:
        self._fetcher = fetcher
        self._calculator = calculator
        self._registry = rule_registry
        self._config = config

    def simulate(self, now: datetime | None = None) -> pl.DataFrame:
        """Retourne une ligne par règle déclenchée et par bougie clôturée."""
        end = self._as_utc(now or datetime.now(timezone.utc))
        start = end - timedelta(days=_LOOKBACK_DAYS)
        tasks = [
            (symbol, timeframe)
            for symbol in self._config["symbols"]
            for timeframe, _, _, _ in _SIMULATED_TIMEFRAMES
        ]
        self._validate_alert_ids()

        print(
            f"Simulation des alertes quotidiennes et hebdomadaires "
            f"du {start.date()} au {end.date()} (UTC), "
            f"{len(tasks)} analyses à effectuer.",
            flush=True,
        )

        rows: list[dict[str, Any]] = []
        for task_number, (symbol_value, timeframe_value) in enumerate(tasks, start=1):
            timeframe, alert_configs, prefix, candle_days = self._task_config(
                timeframe_value
            )
            symbol = Symbol(symbol_value)
            print(
                f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                f"— récupération de {_INDICATOR_WARMUP_CANDLES} bougies OHLCV...",
                flush=True,
            )
            if not alert_configs:
                print(
                    f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                    "— aucune règle configurée, analyse ignorée.",
                    flush=True,
                )
                continue
            data = self._fetcher.fetch(
                symbol, timeframe, limit=_INDICATOR_WARMUP_CANDLES
            )
            if data.df.is_empty():
                raise RuntimeError(
                    f"Aucune donnée OHLCV reçue pour {symbol} [{timeframe.value}]."
                )

            print(
                f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                f"— {len(data.df)} bougies reçues, calcul des indicateurs...",
                flush=True,
            )
            enriched = self._calculator.calculate(data)
            if "timestamp" not in enriched.columns:
                raise ValueError(
                    "Le DataFrame enrichi doit contenir la colonne 'timestamp'."
                )

            print(
                f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                "— évaluation des règles...",
                flush=True,
            )
            for row_index, opened_at in enumerate(enriched["timestamp"].to_list()):
                candle_closed_at = (
                    self._as_utc(opened_at)
                    + timedelta(days=candle_days)
                    - timedelta(milliseconds=1)
                )
                if not start <= candle_closed_at <= end:
                    continue

                snapshot = enriched.slice(0, row_index + 1)
                for rule_config in alert_configs:
                    if not self._rule_applies(rule_config, symbol, timeframe):
                        continue

                    rule_name = rule_config.get(
                        "name", rule_config.get("type", "threshold")
                    )
                    rule = self._registry.build(rule_name)
                    if rule.evaluate(symbol, timeframe, snapshot, rule_config):
                        rows.append({
                            "date": candle_closed_at.date(),
                            "symbol": symbol.value,
                            "alert_id": rule_config["id"],
                        })

            print(
                f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                "— terminé.",
                flush=True,
            )

        result = pl.DataFrame(
            rows,
            schema={
                "date": pl.Date,
                "symbol": pl.String,
                "alert_id": pl.String,
            },
        )
        if not result.is_empty():
            result = result.sort(["date", "symbol", "alert_id"])
        print(f"Simulation terminée : {len(result)} alerte(s) trouvée(s).", flush=True)
        return result

    def _task_config(
        self, timeframe_value: str
    ) -> tuple[Timeframe, list[dict[str, Any]], str, int]:
        for value, config_key, prefix, candle_days in _SIMULATED_TIMEFRAMES:
            if value != timeframe_value:
                continue
            timeframe_config = next(
                (
                    item
                    for item in self._config.get("timeframes", [])
                    if item["value"] == value
                ),
                {"value": value, "label": value, "candles_chart": candle_days},
            )
            alert_configs = self._config.get(
                config_key,
                self._config.get("alerts", []) if config_key == "alert_daily" else [],
            )
            if not isinstance(alert_configs, list):
                raise ValueError(f"'{config_key}' doit être une liste de règles.")
            return Timeframe(**timeframe_config), alert_configs, prefix, candle_days
        raise ValueError(f"Timeframe de simulation non supportée : {timeframe_value}")

    def _validate_alert_ids(self) -> None:
        seen_ids: set[str] = set()
        for timeframe, config_key, prefix, _ in _SIMULATED_TIMEFRAMES:
            _, configs, _, _ = self._task_config(timeframe)
            for rule_config in configs:
                alert_id = rule_config.get("id")
                if (
                    not isinstance(alert_id, str)
                    or not alert_id.startswith(prefix)
                    or len(alert_id) < 2
                    or len(alert_id) > 11
                ):
                    raise ValueError(
                        f"Chaque règle '{config_key}' doit avoir un id "
                        f"commençant par '{prefix}' et limité à 11 caractères."
                    )
                if alert_id in seen_ids:
                    raise ValueError(f"Identifiant d'alerte dupliqué : '{alert_id}'.")
                seen_ids.add(alert_id)

    @staticmethod
    def _rule_applies(
        rule_config: dict[str, Any], symbol: Symbol, timeframe: Timeframe
    ) -> bool:
        if "symbols" in rule_config and symbol.value not in rule_config["symbols"]:
            return False
        if (
            "timeframes" in rule_config
            and timeframe.value not in rule_config["timeframes"]
        ):
            return False
        return True

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
