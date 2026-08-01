"""
alert_rules.py — Règles d'alerte paramétrables.

Architecture :
  • IAlertRule                : contrat abstrait (interfaces.py)
  • ThresholdAlertRule        : règle générique configurable
  • ThresholdAlertRule         : règle générique configurable

Principe O : ajouter une règle = créer une classe ou une configuration JSON,
sans modifier le moteur.
Principe I : les règles ne dépendent que de IAlertRule, pas du reste du système.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Formats supportés par ThresholdAlertRule :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) Format legacy : comparaison à une valeur fixe

  {
    "indicator": "rsi_14",
    "operator":  ">",
    "value":     70,
    "agg":       "last"
  }

  Ce format reste compatible avec l’ancien comportement :
  - "lookback_periods" lit les N dernières bougies
  - "agg" agrège ces N valeurs en une seule
    ("last", "min", "max", "mean")

2) Format inter-bougies : comparaison d’indicateurs entre bougies

  {
    "left":  { "indicator": "close", "offset": 0 },
    "operator": ">",
    "right": { "indicator": "close", "offset": 1 }
  }

  Ici :
  - offset=0 = dernière bougie
  - offset=1 = bougie précédente
  - on peut comparer deux indicateurs sur deux lignes différentes
  - on peut comparer indicateur vs constante en mixant "left" et "right"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exemples de règles directes en JSON :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rebond Bollinger bas :

  {
    "name": "bollinger_bounce",
    "type": "threshold",
    "timeframes": ["1d"],
    "severity": "WARNING",
    "conditions": [
      {
        "left":  { "indicator": "close", "offset": 1 },
        "operator": "<",
        "right": { "indicator": "bb_lower", "offset": 1 }
      },
      {
        "left":  { "indicator": "close", "offset": 0 },
        "operator": ">",
        "right": { "indicator": "bb_lower", "offset": 0 }
      },
      {
        "left":  { "indicator": "close", "offset": 0 },
        "operator": ">",
        "right": { "indicator": "close", "offset": 1 }
      }
    ]
  }

Croisement de moyennes mobiles :

  {
    "name": "ma_cross",
    "type": "threshold",
    "timeframes": ["1d"],
    "conditions": [
      {
        "left":  { "indicator": "ma_50", "offset": 0 },
        "operator": ">",
        "right": { "indicator": "ma_200", "offset": 0 }
      },
      {
        "left":  { "indicator": "ma_50", "offset": 1 },
        "operator": "<",
        "right": { "indicator": "ma_200", "offset": 1 }
      }
    ]
  }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Compatibilité :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Le format legacy reste supporté.
- Les conditions inter-bougies rendent possibles les rules
  `BollingerBounceRule` et `BollingerUpperBounceRule` en JSON,
  sans code dédié.
- Les variations horaires se modélisent simplement via ThresholdAlertRule
  avec une condition de comparaison sur deux bougies consécutives.
"""

import logging
import operator as op
from datetime import datetime, timezone
from typing import Any, Optional

import polars as pl

from src.interfaces import Alert, IAlertRule, Symbol, Timeframe

logger = logging.getLogger(__name__)

from dataclasses import dataclass

@dataclass(frozen=True)
class Operand:
    indicator: str | None = None
    offset: int = 0
    value: float | None = None

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "Operand":
        if "indicator" in config:
            return cls(
                indicator=config["indicator"],
                offset=int(config.get("offset", 0)),
            )
        return cls(value=float(config["value"]))

    def required_rows(self) -> int:
        if self.indicator is None:
            return 1
        return self.offset + 1

    def resolve(self, df: pl.DataFrame) -> float | None:
        if self.value is not None:
            return self.value
        if self.indicator is None or self.indicator not in df.columns:
            return None
        index = len(df) - 1 - self.offset
        if index < 0:
            return None
        return df[self.indicator][index]


@dataclass(frozen=True)
class AlertCondition:
    left: Operand
    operator_str: str
    right: Operand
    agg: str = "last"
    legacy_indicator: str | None = None
    threshold_pct: float | None = None

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "AlertCondition":
        if "left" in config or "right" in config:
            return cls(
                left=Operand.from_dict(config["left"]),
                operator_str=config["operator"],
                right=Operand.from_dict(config["right"]),
                agg=config.get("agg", "last"),
                threshold_pct=float(config["threshold_pct"]) if "threshold_pct" in config else None,
            )
        return cls(
            left=Operand.from_dict({"indicator": config["indicator"]}),
            operator_str=config["operator"],
            right=Operand.from_dict({"value": config["value"]}),
            agg=config.get("agg", "last"),
            legacy_indicator=config["indicator"],
            threshold_pct=float(config["threshold_pct"]) if "threshold_pct" in config else None,
        )

    def max_offset(self) -> int:
        return max(self.left.required_rows(), self.right.required_rows()) - 1

    def is_legacy(self) -> bool:
        return self.legacy_indicator is not None

    def _aggregate(self, df: pl.DataFrame) -> float | None:
        values = df[self.left.indicator].drop_nulls()
        if values.is_empty():
            return None
        if self.agg == "last":
            return values[-1]
        if self.agg == "min":
            return values.min()
        if self.agg == "max":
            return values.max()
        if self.agg == "mean":
            return values.mean()
        return values[-1]

    def evaluate(self, df: pl.DataFrame, lookback: int) -> tuple[bool, dict[str, float]]:
        fn = _OPS.get(self.operator_str)
        if fn is None:
            return False, {}

        if self.is_legacy():
            if self.left.indicator is None:
                return False, {}
            sub_df = df.tail(lookback)
            left_value = self._aggregate(sub_df)
            right_value = self.right.value
        else:
            left_value = self.left.resolve(df)
            right_value = self.right.resolve(df)

        if left_value is None or right_value is None:
            return False, {}

        if self.threshold_pct is not None:
            if right_value == 0:
                return False, {}
            variation_pct = abs((left_value - right_value) / right_value * 100.0)
            context_values: dict[str, float] = {
                "variation_pct": float(variation_pct),
                "threshold_pct": float(self.threshold_pct),
            }
            return fn(variation_pct, self.threshold_pct), context_values

        context_values: dict[str, float] = {}
        if self.legacy_indicator is not None:
            context_values[self.legacy_indicator] = float(left_value)
        else:
            if self.left.indicator is not None:
                key = f"{self.left.indicator}_{self.left.offset}"
                context_values[key] = float(left_value)
            if self.right.indicator is not None:
                key = f"{self.right.indicator}_{self.right.offset}"
                context_values[key] = float(right_value)

        return fn(left_value, right_value), context_values
    

# Opérateurs supportés
_OPS: dict[str, Any] = {
    "<":  op.lt,
    "<=": op.le,
    ">":  op.gt,
    ">=": op.ge,
    "==": op.eq,
    "!=": op.ne,
}


# ===========================================================================
# ThresholdAlertRule
# ===========================================================================

class ThresholdAlertRule(IAlertRule):
    """
    Règle générique : déclenche une alerte si TOUTES les conditions
    (comparaisons indicateur/seuil fixe) sont vraies sur les N dernières
    bougies complètes (voir lookback_periods + agg dans la docstring du module).
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

        conditions_cfg: list[dict] = params.get("conditions", [])
        if not conditions_cfg and "threshold_pct" in params:
            conditions_cfg = [{
                "left": {"indicator": "close", "offset": 0},
                "operator": ">=",
                "right": {"indicator": "close", "offset": 1},
                "threshold_pct": float(params["threshold_pct"]),
            }]

        if not conditions_cfg:
            logger.warning("Règle '%s' : aucune condition définie.", self._name)
            return None

        lookback: int = params.get("lookback_periods", 1)
        conditions = [AlertCondition.from_dict(cond) for cond in conditions_cfg]

        required_lookback = max(
            lookback,
            max((cond.max_offset() + 1 for cond in conditions), default=1),
        )

        if len(enriched_df) < required_lookback:
            logger.debug("Pas assez de données pour la règle '%s'.", self._name)
            return None

        eval_df = enriched_df.tail(required_lookback)

        results: list[bool] = []
        context_values: dict[str, float] = {}

        for cond in conditions:
            if cond.is_legacy():
                if cond.left.indicator not in eval_df.columns:
                    logger.warning(
                        "Règle '%s' : indicateur '%s' absent du DataFrame.",
                        self._name, cond.left.indicator,
                    )
                    results.append(False)
                    continue
            else:
                if cond.left.indicator and cond.left.indicator not in eval_df.columns:
                    logger.warning(
                        "Règle '%s' : indicateur '%s' absent du DataFrame.",
                        self._name, cond.left.indicator,
                    )
                    results.append(False)
                    continue
                if cond.right.indicator and cond.right.indicator not in eval_df.columns:
                    logger.warning(
                        "Règle '%s' : indicateur '%s' absent du DataFrame.",
                        self._name, cond.right.indicator,
                    )
                    results.append(False)
                    continue

            ok, ctx = cond.evaluate(eval_df, lookback)
            results.append(ok)
            context_values.update(ctx)

        if not all(results):
            return None

        severity = params.get("severity", "INFO")
        msg_tpl = params.get("message_tpl", "Alerte {rule} sur {symbol} [{tf}]")
        message = msg_tpl.format(
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


# ===========================================================================
# Registre
# ===========================================================================

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
            return ThresholdAlertRule(rule_name)
        if rule_name == "bollinger_bounce":
            return BollingerBounceRule()
        if rule_name == "bollinger_upper_bounce":
            return BollingerUpperBounceRule()
        cls = self._rules.get(rule_name)
        if cls is None:
            logger.debug("Règle '%s' non enregistrée → ThresholdAlertRule.", rule_name)
            return ThresholdAlertRule(rule_name)
        return cls(rule_name)


def build_default_registry() -> AlertRuleRegistry:
    """Crée et retourne un registre avec les règles built-in."""
    registry = AlertRuleRegistry()
    registry.register(ThresholdAlertRule,       "threshold")
    return registry