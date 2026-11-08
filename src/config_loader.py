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

    def __init__(
        self, config_path: str | Path, *, validate_discord: bool = True
    ) -> None:
        self._path = Path(config_path)
        self._validate_discord = validate_discord

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
        required_keys = ["symbols", "timeframes"]
        if self._validate_discord:
            required_keys.append("discord")
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Clé obligatoire manquante dans la config : '{key}'")

        if self._validate_discord:
            discord_config = config["discord"]
            if not isinstance(discord_config, dict):
                raise ValueError("'discord' doit être un objet.")

            webhook_urls = discord_config.get("webhook_urls")
            if not isinstance(webhook_urls, dict):
                raise ValueError("'discord.webhook_urls' doit être un objet.")
            for command in ("daily", "hourly", "weekly"):
                webhook_url = webhook_urls.get(command)
                if not isinstance(webhook_url, str) or not webhook_url.strip():
                    raise ValueError(
                        f"'discord.webhook_urls.{command}' doit être une URL non vide."
                    )

            channel_ids = discord_config.get("channel_ids")
            if not isinstance(channel_ids, dict):
                raise ValueError("'discord.channel_ids' doit être un objet.")
            for command in ("daily", "hourly", "weekly"):
                channel_id = channel_ids.get(command)
                if not isinstance(channel_id, str) or not channel_id.isdigit():
                    raise ValueError(
                        f"'discord.channel_ids.{command}' doit être un identifiant "
                        "Discord numérique."
                    )

        if not isinstance(config["symbols"], list) or not config["symbols"]:
            raise ValueError("'symbols' doit être une liste non vide.")

        daily_alerts = config.get("alert_daily", config.get("alerts"))
        if daily_alerts is None:
            raise ValueError("Clé obligatoire manquante : 'alert_daily' (ou 'alerts').")
        if not isinstance(daily_alerts, list):
            raise ValueError("'alert_daily' doit être une liste de règles.")

        hourly_alerts = config.get("alert_hourly")
        if hourly_alerts is not None and not isinstance(hourly_alerts, list):
            raise ValueError("'alert_hourly' doit être une liste de règles.")

        weekly_alerts = config.get("alert_weekly")
        if weekly_alerts is not None and not isinstance(weekly_alerts, list):
            raise ValueError("'alert_weekly' doit être une liste de règles.")

        logger.debug("Configuration validée : %d symboles, %d règles d'alerte",
                     len(config["symbols"]), len(daily_alerts))
