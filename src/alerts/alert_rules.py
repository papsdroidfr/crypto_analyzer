"""
alert_rules.py — Règles d'alerte paramétrables.

Architecture :
  • IAlertRule          : contrat abstrait (interfaces.py)
  • ThresholdAlertRule  : règle générique « toutes les conditions sont vraies »
  • HourlyVariationRule : surveillance horaire des variations de cours

Principe O : ajouter une règle = créer une classe, sans modifier le moteur.
Principe I : les règles ne dépendent que de IAlertRule, pas du reste du système.

Format des conditions dans le JSON :
  {
    "indicator": "rsi_14",   // nom de colonne dans le DataFrame enrichi
    "operator":  ">",        // <, <=, >, >=, ==, !=
    "value":     70          // seuil numérique
  }

Une alerte est déclenchée si TOUTES les conditions de la règle sont vraies
sur la DERNIÈRE période pleine (dernière ligne du DataFrame).
"""

import logging
import operator as op
from datetime import datetime, timezone
from typing import Any, Optional

import polars as pl

from src.interfaces import Alert, IAlertRule, Symbol, Timeframe

logger = logging.getLogger(__name__)

# Opérateurs supportés
_OPS: dict[str, Any] = {
    "<":  op.lt,
    "<=": op.le,
    ">":  op.gt,
    ">=": op.ge,
    "==": op.eq,
    "!=": op.ne,
}


class ThresholdAlertRule(IAlertRule):
    """
    Règle générique : déclenche une alerte si TOUTES les conditions
    (comparaisons indicateur/seuil) sont vraies sur la dernière bougie complète.

    Paramètres attendus dans `params` (issu du JSON) :
      - conditions  : list[dict]  — liste des comparaisons
      - severity    : str         — "INFO" | "WARNING" | "CRITICAL"
      - message_tpl : str         — template du message avec {symbol}, {tf}, {value}
    """

    def __init__(self, rule_name: str) -> None:
        self._name = rule_name

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        enriched_df: pl.DataFrame,
        params: dict[str, Any],
    ) -> Optional[Alert]:

        conditions: list[dict] = params.get("conditions", [])
        if not conditions:
            logger.warning("Règle '%s' : aucune condition définie.", self._name)
            return None

        # On travaille sur les N dernières bougies complètes
        lookback: int = params.get("lookback_periods", 1)
        if len(enriched_df) < lookback:
            logger.debug("Pas assez de données pour la règle '%s'.", self._name)
            return None

        # Bougie(s) d'évaluation : les `lookback` dernières
        eval_df = enriched_df.tail(lookback)

        results: list[bool] = []
        context_values: dict[str, float] = {}

        for cond in conditions:
            indicator = cond["indicator"]
            operator_str = cond["operator"]
            threshold = float(cond["value"])

            if indicator not in eval_df.columns:
                logger.warning(
                    "Règle '%s' : indicateur '%s' absent du DataFrame.",
                    self._name, indicator,
                )
                results.append(False)
                continue

            fn = _OPS.get(operator_str)
            if fn is None:
                logger.error("Opérateur inconnu : '%s'", operator_str)
                results.append(False)
                continue

            # On évalue la condition sur TOUTES les lignes de lookback
            col_values = eval_df[indicator].drop_nulls()
            if col_values.is_empty():
                results.append(False)
                continue

            # Agrégation selon la stratégie définie (défaut: dernière valeur)
            agg = cond.get("agg", "last")
            if agg == "last":
                actual_value = col_values[-1]
            elif agg == "min":
                actual_value = col_values.min()
            elif agg == "max":
                actual_value = col_values.max()
            elif agg == "mean":
                actual_value = col_values.mean()
            else:
                actual_value = col_values[-1]

            context_values[indicator] = actual_value
            results.append(fn(actual_value, threshold))

        if not all(results):
            return None

        # Toutes les conditions sont vraies → génération de l'alerte
        severity   = params.get("severity", "INFO")
        msg_tpl    = params.get("message_tpl", "Alerte {rule} sur {symbol} [{tf}]")
        message    = msg_tpl.format(
            rule=self._name,
            symbol=symbol,
            tf=timeframe.label,
            **{k: f"{v:.4f}" for k, v in context_values.items()},
        )

        return Alert(
            symbol=symbol,
            timeframe=timeframe,
            rule_name=self._name,
            message=message,
            triggered_at=datetime.now(tz=timezone.utc),
            severity=severity,
        )


class HourlyVariationRule(IAlertRule):
    """
    Surveille la variation de cours de clôture entre la bougie horaire courante
    et la précédente. Déclenche une alerte si |variation| >= seuil (en %).

    Paramètres attendus dans `params` :
      - threshold_pct : float  — seuil en pourcentage (ex: 3.0 pour 3 %)
      - severity      : str
    """

    @property
    def name(self) -> str:
        return "hourly_variation"

    def evaluate(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        enriched_df: pl.DataFrame,
        params: dict[str, Any],
    ) -> Optional[Alert]:

        threshold_pct = float(params.get("threshold_pct", 3.0))

        if len(enriched_df) < 2:
            return None

        last_two = enriched_df.tail(2)
        prev_close = last_two["close"][0]
        curr_close = last_two["close"][1]

        if prev_close == 0:
            return None

        variation_pct = ((curr_close - prev_close) / prev_close) * 100.0
        direction = "hausse" if variation_pct > 0 else "baisse"

        if abs(variation_pct) < threshold_pct:
            return None

        severity = params.get("severity", "WARNING")
        message = (
            f"⚡ Variation horaire importante sur {symbol} : "
            f"{variation_pct:+.2f}% ({direction}) "
            f"| Cours : {prev_close:.4f} → {curr_close:.4f}"
        )

        return Alert(
            symbol=symbol,
            timeframe=timeframe,
            rule_name=self.name,
            message=message,
            triggered_at=datetime.now(tz=timezone.utc),
            severity=severity,
        )


class AlertRuleRegistry:
    """
    Registre des règles disponibles.
    Principe O : on enregistre de nouvelles règles sans modifier le moteur.
    """

    def __init__(self) -> None:
        self._rules: dict[str, type[IAlertRule]] = {}

    def register(self, rule_class: type[IAlertRule], rule_name: str) -> None:
        self._rules[rule_name] = rule_class
        logger.debug("Règle enregistrée : %s", rule_name)

    def build(self, rule_name: str) -> IAlertRule:
        """Instancie une règle par son nom."""
        if rule_name == "hourly_variation":
            return HourlyVariationRule()
        cls = self._rules.get(rule_name)
        if cls is None:
            # Règle inconnue → ThresholdAlertRule générique
            logger.debug("Règle '%s' non enregistrée → ThresholdAlertRule.", rule_name)
            return ThresholdAlertRule(rule_name)
        return cls(rule_name)


def build_default_registry() -> AlertRuleRegistry:
    """Crée et retourne un registre avec les règles built-in."""
    registry = AlertRuleRegistry()
    registry.register(ThresholdAlertRule, "threshold")
    return registry
