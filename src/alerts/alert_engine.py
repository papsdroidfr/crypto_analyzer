"""
alert_engine.py — Moteur d'orchestration des alertes.

Deux modes de fonctionnement :
  1. run_daily()  : analyse sur 7 dernières périodes pleines (1d ou 1w)
                    → à planifier une fois par jour via crontab
  2. run_hourly() : surveille les variations de cours horaires
                    → à planifier toutes les heures via crontab

Principe S : le moteur orchestre, il ne calcule ni ne notifie directement.
Principe D : toutes les dépendances sont injectées (fetcher, calculator, etc.).
"""

import logging
from typing import Any

from src.alerts.alert_rules import AlertRuleRegistry
from src.interfaces import (
    Alert,
    IChartGenerator,
    IDataFetcher,
    IIndicatorCalculator,
    INotifier,
    Symbol,
    Timeframe,
)

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Orchestre le cycle complet :
    fetch → calculate → evaluate rules → notify.
    """

    def __init__(
        self,
        fetcher: IDataFetcher,
        calculator: IIndicatorCalculator,
        notifier: INotifier,
        chart_generator: IChartGenerator,
        rule_registry: AlertRuleRegistry,
        config: dict[str, Any],
    ) -> None:
        self._fetcher   = fetcher
        self._calc      = calculator
        self._notifier  = notifier
        self._charts    = chart_generator
        self._registry  = rule_registry
        self._config    = config

    # ------------------------------------------------------------------
    # Mode quotidien
    # ------------------------------------------------------------------

    def run_daily(self) -> list[Alert]:
        """
        Analyse sur les 7 dernières périodes pleines pour toutes les paires
        et toutes les timeframes configurées (1d, 1w).
        Évalue les règles d'alerte (hors variation horaire).
        """
        logger.info("=== Démarrage analyse quotidienne ===")
        all_alerts: list[Alert] = []

        symbols    = [Symbol(s) for s in self._config["symbols"]]
        timeframes = self._build_timeframes(daily=True)
        alert_configs = self._daily_alert_configs()

        for symbol in symbols:
            for tf in timeframes:
                try:
                    alerts = self._process_symbol_timeframe(
                        symbol, tf, lookback=7, alert_configs=alert_configs,
                        mode="quotidienne",
                    )
                    all_alerts.extend(alerts)
                except Exception as exc:
                    logger.error(
                        "Erreur traitement %s [%s] : %s", symbol, tf, exc,
                        exc_info=True,
                    )

        logger.info("Analyse quotidienne terminée : %d alerte(s) générée(s).", len(all_alerts))
        return all_alerts

    # ------------------------------------------------------------------
    # Mode horaire
    # ------------------------------------------------------------------

    def run_hourly(self) -> list[Alert]:
        """
        Évalue les règles configurées pour la timeframe horaire, comme
        run_daily() le fait pour les timeframes quotidiennes.
        """
        logger.info("=== Surveillance horaire ===")
        all_alerts: list[Alert] = []
        symbols = [Symbol(s) for s in self._config["symbols"]]
        tf_hourly = self._get_hourly_timeframe()
        alert_configs = self._hourly_alert_configs()

        for symbol in symbols:
            try:
                all_alerts.extend(
                    self._process_symbol_timeframe(
                        symbol, tf_hourly, lookback=7, alert_configs=alert_configs,
                        mode="horaire",
                    )
                )
            except Exception as exc:
                logger.error("Erreur horaire %s : %s", symbol, exc, exc_info=True)

        return all_alerts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _daily_alert_configs(self) -> list[dict[str, Any]]:
        return self._config.get("alerte_dailly", self._config.get("alerts", []))

    def _hourly_alert_configs(self) -> list[dict[str, Any]]:
        if "alert_hourly" in self._config:
            return self._config["alert_hourly"]

        legacy_config = self._config.get("hourly_variation", {
            "threshold_pct": 3.0,
            "severity": "WARNING",
        })
        return [{
            "name": "hourly_variation",
            "type": "hourly_variation",
            "timeframes": ["1h"],
            **legacy_config,
        }]

    def _get_hourly_timeframe(self) -> Timeframe:
        """
        Lit la config de la timeframe '1h' depuis settings.json.
        Garantit que candles_chart est respecté pour les graphiques.
        """
        tf_cfg = next(
            (t for t in self._config.get("timeframes", []) if t["value"] == "1h"),
            {"value": "1h", "label": "1 heure", "candles_chart": 48},
        )
        return Timeframe(
            value=tf_cfg["value"],
            label=tf_cfg["label"],
            candles_chart=tf_cfg.get("candles_chart", 48),
        )

    def _process_symbol_timeframe(
        self,
        symbol: Symbol,
        tf: Timeframe,
        lookback: int,
        alert_configs: list[dict[str, Any]],
        mode: str,
    ) -> list[Alert]:
        # On récupère assez de données pour les indicateurs (200 SMA min)
        fetch_limit = max(250, lookback + 200)
        data     = self._fetcher.fetch(symbol, tf, limit=fetch_limit)
        enriched = self._calc.calculate(data)

        # Sous-DataFrame des N dernières périodes pleines pour l'évaluation
        eval_df = enriched.tail(lookback)

        alerts: list[Alert] = []
        for rule_cfg in alert_configs:
            if "symbols" in rule_cfg and symbol.value not in rule_cfg["symbols"]:
                continue
            if "timeframes" in rule_cfg and tf.value not in rule_cfg["timeframes"]:
                continue
            if mode == "quotidienne" and rule_cfg.get("type") == "hourly_variation":
                continue

            rule  = self._registry.build(rule_cfg.get("name", rule_cfg.get("type", "threshold")))
            alert = rule.evaluate(symbol, tf, eval_df, rule_cfg)
            if alert:
                # Le graphique utilise le DataFrame complet (pas juste les 7 périodes)
                chart_path = self._generate_chart(data, enriched, alert)
                if chart_path:
                    alert.chart_path = chart_path
                    self._notifier.send_chart(alert, chart_path)
                else:
                    self._notifier.send(alert)
                alerts.append(alert)
                logger.info("Alerte %s déclenchée : %s — %s", mode, rule.name, alert.message)

        return alerts

    def _generate_chart(self, data, enriched, alert: Alert) -> str | None:
        try:
            charts_dir = self._config.get("charts_output_dir", "charts_output")
            path = (
                f"{charts_dir}/{alert.symbol}_{alert.timeframe.value}"
                f"_{alert.triggered_at.strftime('%Y%m%d_%H%M%S')}.png"
            )
            return self._charts.generate(data, enriched, path)
        except Exception as exc:
            logger.warning("Impossible de générer le graphique : %s", exc)
            return None

    def _build_timeframes(self, daily: bool) -> list[Timeframe]:
        tf_configs = self._config.get("timeframes", [])
        result = []
        for cfg in tf_configs:
            tf = Timeframe(
                value=cfg["value"],
                label=cfg["label"],
                candles_chart=cfg.get("candles_chart", 90),
            )
            # Mode quotidien : on skip la timeframe horaire
            if daily and tf.value == "1h":
                continue
            result.append(tf)
        return result