"""Simulation historique des alertes quotidiennes et hebdomadaires."""

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl

from src.alerts.alert_rules import AlertRuleRegistry
from src.interfaces import (
    Alert,
    IDataFetcher,
    IChartGenerator,
    IIndicatorCalculator,
    INotifier,
    OHLCVData,
    Symbol,
    Timeframe,
)

_SIMULATED_TIMEFRAMES = (
    ("1d", "alert_daily", "D", 1),
    ("1w", "alert_weekly", "W", 7),
)
_LOOKBACK_DAYS = 30
_INDICATOR_WARMUP_CANDLES = 250
logger = logging.getLogger(__name__)


class AlertSimulator:
    """Évalue les règles quotidiennes et hebdomadaires sur les 30 derniers jours.

    La simulation inclut aussi la dernière bougie weekly clôturée avant la
    fenêtre pour amorcer les alertes hebdomadaires.
    """

    def __init__(
        self,
        fetcher: IDataFetcher,
        calculator: IIndicatorCalculator,
        rule_registry: AlertRuleRegistry,
        config: dict[str, Any],
        chart_generator: IChartGenerator | None = None,
        notifier: INotifier | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._calculator = calculator
        self._registry = rule_registry
        self._config = config
        self._chart_generator = chart_generator
        self._notifier = notifier

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
        daily_chart_data: dict[str, tuple[OHLCVData, pl.DataFrame]] = {}
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
            should_generate_daily_chart = (
                timeframe.value == "1d" and self._chart_generator is not None
            )
            if not alert_configs and not should_generate_daily_chart:
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
            if should_generate_daily_chart:
                daily_chart_data[symbol_value] = (data, enriched)

            if not alert_configs:
                print(
                    f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                    "— aucune règle configurée, analyse ignorée.",
                    flush=True,
                )
                continue

            print(
                f"[{task_number}/{len(tasks)}] {symbol} [{timeframe.value}] "
                "— évaluation des règles...",
                flush=True,
            )
            candle_closed_times = [
                self._as_utc(opened_at)
                + timedelta(days=candle_days)
                - timedelta(milliseconds=1)
                for opened_at in enriched["timestamp"].to_list()
            ]
            weekly_seed_index = None
            if timeframe.value == "1w":
                weekly_seed_index = max(
                    (
                        index
                        for index, closed_at in enumerate(candle_closed_times)
                        if closed_at < start
                    ),
                    key=lambda index: candle_closed_times[index],
                    default=None,
                )

            for row_index, candle_closed_at in enumerate(candle_closed_times):
                is_weekly_seed = row_index == weekly_seed_index
                if not (
                    start <= candle_closed_at <= end
                    or is_weekly_seed
                ):
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
        if self._chart_generator is not None:
            self._generate_simulation_charts(
                result, daily_chart_data, start.date(), end.date()
            )
        print(f"Simulation terminée : {len(result)} alerte(s) trouvée(s).", flush=True)
        return result

    def _generate_simulation_charts(
        self,
        result: pl.DataFrame,
        daily_chart_data: dict[str, tuple[OHLCVData, pl.DataFrame]],
        start_date: date,
        end_date: date,
    ) -> None:
        if self._chart_generator is None:
            return
        charts_dir = Path(self._config.get("charts_output_dir", "charts_output"))
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        for symbol, (data, enriched) in daily_chart_data.items():
            alert_flags = [
                (row["date"], row["alert_id"])
                for row in result.filter(pl.col("symbol") == symbol).iter_rows(
                    named=True
                )
            ]
            chart_data = OHLCVData(
                symbol=data.symbol,
                timeframe=Timeframe(
                    value=data.timeframe.value,
                    label=data.timeframe.label,
                    candles_chart=max(
                        data.timeframe.candles_chart, _LOOKBACK_DAYS + 8
                    ),
                ),
                df=data.df,
            )
            output_path = charts_dir / f"{symbol}_1d_{generated_at}.png"
            path = self._chart_generator.generate(
                chart_data,
                enriched,
                str(output_path),
                alert_flags=alert_flags,
            )
            logger.info("Graphique de simulation généré : %s", path)
            if self._notifier is not None:
                symbol_alerts = result.filter(pl.col("symbol") == symbol)
                period_alerts = symbol_alerts.filter(
                    (pl.col("date") >= start_date)
                    & (pl.col("date") <= end_date)
                )
                daily_count = period_alerts.filter(
                    pl.col("alert_id").str.starts_with("D")
                ).height
                weekly_count = period_alerts.filter(
                    pl.col("alert_id").str.starts_with("W")
                ).height
                total_count = daily_count + weekly_count
                summary = (
                    f"Bilan des alertes sur les 30 derniers jours pour {symbol} : "
                    f"{total_count} au total ({daily_count} daily, "
                    f"{weekly_count} weekly)."
                )
                alert = Alert(
                    symbol=data.symbol,
                    timeframe=chart_data.timeframe,
                    rule_name="Bilan des alertes — 30 derniers jours",
                    message=summary,
                    triggered_at=datetime.now(timezone.utc),
                    chart_path=path,
                )
                self._notifier.send_chart(alert, path)

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
                    or alert_id[1] not in ("S", "L")
                    or len(alert_id) > 11
                ):
                    raise ValueError(
                        f"Chaque règle '{config_key}' doit avoir un id "
                        f"commençant par '{prefix}', dont le deuxième caractère "
                        "est 'S' ou 'L', et limité à 11 caractères."
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
