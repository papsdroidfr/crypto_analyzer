"""
alert_rules.py — Règles d'alerte paramétrables.

Architecture :
  • IAlertRule                : contrat abstrait (interfaces.py)
  • ThresholdAlertRule        : règle générique « toutes les conditions sont vraies »
  • HourlyVariationRule       : surveillance horaire des variations de cours
  • BollingerBounceRule       : détection de rebond sur la bande inférieure de Bollinger
  • BollingerUpperBounceRule  : détection de rebond sur la bande supérieure de Bollinger

Principe O : ajouter une règle = créer une classe, sans modifier le moteur.
Principe I : les règles ne dépendent que de IAlertRule, pas du reste du système.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Format des conditions dans le JSON (ThresholdAlertRule) :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {
    "indicator": "rsi_14",   // nom de colonne dans le DataFrame enrichi
    "operator":  ">",        // <, <=, >, >=, ==, !=
    "value":     70,         // seuil numérique fixe
    "agg":       "last"      // stratégie d'agrégation sur lookback_periods (voir ci-dessous)
  }

Une alerte est déclenchée si TOUTES les conditions de la règle sont vraies.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Paramètre lookback_periods et stratégies d'agrégation (agg) :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lookback_periods (int, défaut: 1) :
    Nombre de bougies complètes sur lesquelles la condition est évaluée.
    Avec lookback_periods: 1, seule la dernière bougie est examinée.
    Avec lookback_periods: 3, les 3 dernières bougies sont agrégées via `agg`.

  agg (str, défaut: "last") — comment réduire les N valeurs en une seule :
    "last"  → valeur de la dernière bougie uniquement (comportement par défaut)
    "min"   → valeur minimale sur les N bougies
              Utile pour s'assurer qu'une condition a été vraie en continu.
              Ex: lookback_periods=2, agg="min", operator=">", value=70
                  → le RSI est resté AU-DESSUS de 70 sur les 2 dernières bougies
    "max"   → valeur maximale sur les N bougies
              Ex: lookback_periods=3, agg="max", operator="<", value=30
                  → le RSI a atteint AU MOINS UNE FOIS moins de 30 sur 3 bougies
    "mean"  → moyenne sur les N bougies
              Utile pour lisser les pics isolés et détecter une tendance.
              Ex: lookback_periods=5, agg="mean", operator=">", value=60
                  → le RSI moyen est au-dessus de 60 sur 5 bougies

  Conseil : avec lookback_periods=1 (défaut) et agg="last", lookback_periods
  n'a aucun effet — c'est la configuration la plus simple et la plus réactive.
  Augmenter lookback_periods avec agg="min" ou "max" permet de filtrer les
  faux signaux générés par des bougies isolées atypiques.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Règles nécessitant une comparaison inter-bougies :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Certains signaux (ex: rebond Bollinger, croisement de moyennes mobiles)
  nécessitent de comparer la bougie N à la bougie N-1. ThresholdAlertRule
  ne le permet pas car elle compare toujours à une valeur fixe.
  Ces cas font l'objet de règles dédiées (BollingerBounceRule, etc.)
  qui lisent explicitement les deux dernières lignes du DataFrame.
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

        conditions: list[dict] = params.get("conditions", [])
        if not conditions:
            logger.warning("Règle '%s' : aucune condition définie.", self._name)
            return None

        lookback: int = params.get("lookback_periods", 1)
        if len(enriched_df) < lookback:
            logger.debug("Pas assez de données pour la règle '%s'.", self._name)
            return None

        eval_df = enriched_df.tail(lookback)

        results: list[bool] = []
        context_values: dict[str, float] = {}

        for cond in conditions:
            indicator    = cond["indicator"]
            operator_str = cond["operator"]
            threshold    = float(cond["value"])

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

            col_values = eval_df[indicator].drop_nulls()
            if col_values.is_empty():
                results.append(False)
                continue

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

        severity = params.get("severity", "INFO")
        msg_tpl  = params.get("message_tpl", "Alerte {rule} sur {symbol} [{tf}]")
        message  = msg_tpl.format(
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
# HourlyVariationRule
# ===========================================================================

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

        last_two   = enriched_df.tail(2)
        prev_close = last_two["close"][0]
        curr_close = last_two["close"][1]

        if prev_close == 0:
            return None

        variation_pct = ((curr_close - prev_close) / prev_close) * 100.0
        direction     = "hausse" if variation_pct > 0 else "baisse"

        if abs(variation_pct) < threshold_pct:
            return None

        severity = params.get("severity", "WARNING")
        message  = (
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


# ===========================================================================
# BollingerBounceRule  (rebond sur la bande INFÉRIEURE)
# ===========================================================================

class BollingerBounceRule(IAlertRule):
    """
    Détecte un rebond haussier sur la bande inférieure de Bollinger.

    Conditions (toutes doivent être vraies) :
      1. Close N-1 < bb_lower N-1  — la bougie précédente était sous la bande
      2. Close N   > bb_lower N    — la bougie courante est repassée au-dessus
      3. Close N   > Close N-1     — momentum haussier confirmé

    Paramètres attendus dans `params` :
      - severity    : str  — "INFO" | "WARNING" | "CRITICAL"
      - message_tpl : str  — template optionnel
    """

    @property
    def name(self) -> str:
        return "bollinger_bounce"

    def evaluate(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        enriched_df: pl.DataFrame,
        params: dict[str, Any],
    ) -> Optional[Alert]:

        if len(enriched_df) < 2:
            logger.debug("BollingerBounceRule : pas assez de bougies.")
            return None

        if not {"close", "bb_lower"}.issubset(enriched_df.columns):
            logger.warning("BollingerBounceRule : colonnes manquantes.")
            return None

        last_two      = enriched_df.tail(2)
        prev_close    = last_two["close"][0]
        curr_close    = last_two["close"][1]
        prev_bb_lower = last_two["bb_lower"][0]
        curr_bb_lower = last_two["bb_lower"][1]

        if any(v is None for v in (prev_close, curr_close, prev_bb_lower, curr_bb_lower)):
            logger.debug("BollingerBounceRule : valeurs nulles, règle ignorée.")
            return None

        if not (
            prev_close < prev_bb_lower   # N-1 sous la bande
            and curr_close > curr_bb_lower  # N au-dessus
            and curr_close > prev_close     # momentum haussier
        ):
            return None

        severity = params.get("severity", "INFO")
        msg_tpl  = params.get(
            "message_tpl",
            "🔄 Rebond Bollinger basse sur {symbol} [{tf}] "
            "| Close N-1={prev_close} < BB_low N-1={prev_bb_lower} "
            "→ Close N={curr_close} > BB_low N={curr_bb_lower}",
        )
        message = msg_tpl.format(
            symbol=symbol, tf=timeframe.label,
            prev_close=f"{prev_close:.4f}", curr_close=f"{curr_close:.4f}",
            prev_bb_lower=f"{prev_bb_lower:.4f}", curr_bb_lower=f"{curr_bb_lower:.4f}",
        )

        return Alert(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            message=message, triggered_at=datetime.now(tz=timezone.utc),
            severity=severity,
        )


# ===========================================================================
# BollingerUpperBounceRule  (rebond sur la bande SUPÉRIEURE)
# ===========================================================================

class BollingerUpperBounceRule(IAlertRule):
    """
    Détecte un rebond baissier sur la bande supérieure de Bollinger.

    Conditions (toutes doivent être vraies) :
      1. Close N-1 > bb_upper N-1  — la bougie précédente était au-dessus de la bande
      2. Close N   < bb_upper N    — la bougie courante est repassée en-dessous
      3. Close N   < Close N-1     — momentum baissier confirmé

    Paramètres attendus dans `params` :
      - severity    : str  — "INFO" | "WARNING" | "CRITICAL"
      - message_tpl : str  — template optionnel
    """

    @property
    def name(self) -> str:
        return "bollinger_upper_bounce"

    def evaluate(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        enriched_df: pl.DataFrame,
        params: dict[str, Any],
    ) -> Optional[Alert]:

        if len(enriched_df) < 2:
            logger.debug("BollingerUpperBounceRule : pas assez de bougies.")
            return None

        if not {"close", "bb_upper"}.issubset(enriched_df.columns):
            logger.warning("BollingerUpperBounceRule : colonnes manquantes.")
            return None

        last_two      = enriched_df.tail(2)
        prev_close    = last_two["close"][0]
        curr_close    = last_two["close"][1]
        prev_bb_upper = last_two["bb_upper"][0]
        curr_bb_upper = last_two["bb_upper"][1]

        if any(v is None for v in (prev_close, curr_close, prev_bb_upper, curr_bb_upper)):
            logger.debug("BollingerUpperBounceRule : valeurs nulles, règle ignorée.")
            return None

        if not (
            prev_close > prev_bb_upper   # N-1 au-dessus de la bande
            and curr_close < curr_bb_upper  # N repassée en-dessous
            and curr_close < prev_close     # momentum baissier
        ):
            return None

        severity = params.get("severity", "INFO")
        msg_tpl  = params.get(
            "message_tpl",
            "🔄 Rebond Bollinger haute sur {symbol} [{tf}] "
            "| Close N-1={prev_close} > BB_up N-1={prev_bb_upper} "
            "→ Close N={curr_close} < BB_up N={curr_bb_upper}",
        )
        message = msg_tpl.format(
            symbol=symbol, tf=timeframe.label,
            prev_close=f"{prev_close:.4f}", curr_close=f"{curr_close:.4f}",
            prev_bb_upper=f"{prev_bb_upper:.4f}", curr_bb_upper=f"{curr_bb_upper:.4f}",
        )

        return Alert(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            message=message, triggered_at=datetime.now(tz=timezone.utc),
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
            return HourlyVariationRule()
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
    registry.register(BollingerBounceRule,      "bollinger_bounce")
    registry.register(BollingerUpperBounceRule, "bollinger_upper_bounce")
    return registry