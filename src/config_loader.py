"""
config_loader.py — Chargement et validation de la configuration JSON.
Principe S : responsabilité unique de lecture/validation de config.
"""

import json
import logging
from pathlib import Path
from typing import Any

from src.interfaces import IConfigLoader

logger = logging.getLogger(__name__)


class JsonConfigLoader(IConfigLoader):
    """Charge la configuration depuis un fichier JSON avec validation basique."""

    def __init__(self, config_path: str | Path) -> None:
        self._path = Path(config_path)

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            raise FileNotFoundError(f"Fichier de configuration introuvable : {self._path}")

        with self._path.open("r", encoding="utf-8") as fh:
            config = json.load(fh)

        self._validate(config)
        logger.info("Configuration chargée depuis %s", self._path)
        return config

    # ------------------------------------------------------------------
    # Validation interne
    # ------------------------------------------------------------------

    def _validate(self, config: dict[str, Any]) -> None:
        required_keys = ["symbols", "timeframes", "discord"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Clé obligatoire manquante dans la config : '{key}'")

        if not isinstance(config["symbols"], list) or not config["symbols"]:
            raise ValueError("'symbols' doit être une liste non vide.")

        daily_alerts = config.get("alerte_dailly", config.get("alerts"))
        if daily_alerts is None:
            raise ValueError("Clé obligatoire manquante : 'alerte_dailly' (ou 'alerts').")
        if not isinstance(daily_alerts, list):
            raise ValueError("'alerte_dailly' doit être une liste de règles.")

        hourly_alerts = config.get("alert_hourly")
        if hourly_alerts is not None and not isinstance(hourly_alerts, list):
            raise ValueError("'alert_hourly' doit être une liste de règles.")

        logger.debug("Configuration validée : %d symboles, %d règles d'alerte",
                     len(config["symbols"]), len(daily_alerts))
