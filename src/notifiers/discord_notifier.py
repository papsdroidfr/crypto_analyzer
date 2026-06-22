"""
discord_notifier.py — Publication des alertes sur Discord via Webhook.

Utilise l'API Webhook Discord (pas de bot token nécessaire).
Principe S : responsabilité unique d'envoi Discord.
Principe L : substitut conforme à INotifier sans surprises.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import requests

from src.interfaces import Alert, INotifier

logger = logging.getLogger(__name__)

# Couleurs des embeds Discord par sévérité
_SEVERITY_COLORS: dict[str, int] = {
    "INFO":     0x3498DB,   # Bleu
    "WARNING":  0xF39C12,   # Orange
    "CRITICAL": 0xE74C3C,   # Rouge
}

_SEVERITY_EMOJIS: dict[str, str] = {
    "INFO":     "ℹ️",
    "WARNING":  "⚠️",
    "CRITICAL": "🚨",
}


class DiscordNotifier(INotifier):
    """
    Envoie les alertes sur un canal Discord via Webhook.

    Supporte :
      - Messages texte enrichis (embed Discord)
      - Envoi de fichiers image (graphiques)
    """

    def __init__(
        self,
        webhook_url: str,
        username: str = "CryptoAnalyzer 🤖",
        avatar_url: Optional[str] = None,
        timeout: int = 10,
        retry: int = 3,
    ) -> None:
        if not webhook_url:
            raise ValueError("L'URL du webhook Discord est obligatoire.")
        self._webhook_url = webhook_url
        self._username    = username
        self._avatar_url  = avatar_url
        self._timeout     = timeout
        self._retry       = retry
        self._session     = requests.Session()

    # ------------------------------------------------------------------
    # Interface INotifier
    # ------------------------------------------------------------------

    def send(self, alert: Alert) -> None:
        """Envoie un embed Discord pour l'alerte."""
        payload = self._build_embed_payload(alert)
        self._post_json(payload)
        logger.info("Alerte Discord envoyée : %s [%s]", alert.rule_name, alert.severity)

    def send_chart(self, alert: Alert, chart_path: str) -> None:
        """Envoie l'alerte avec le graphique en pièce jointe."""
        chart_file = Path(chart_path)
        if not chart_file.exists():
            logger.warning("Graphique introuvable : %s — envoi sans image.", chart_path)
            self.send(alert)
            return

        payload = self._build_embed_payload(alert, with_image=True)
        self._post_with_file(payload, chart_file)
        logger.info(
            "Alerte Discord + graphique envoyés : %s [%s]",
            alert.rule_name, alert.severity,
        )

    # ------------------------------------------------------------------
    # Construction des payloads
    # ------------------------------------------------------------------

    def _build_embed_payload(
        self, alert: Alert, with_image: bool = False
    ) -> dict:
        emoji = _SEVERITY_EMOJIS.get(alert.severity, "📊")
        color = _SEVERITY_COLORS.get(alert.severity, 0x95A5A6)

        embed: dict = {
            "title":       f"{emoji} {alert.rule_name} — {alert.symbol}",
            "description": alert.message,
            "color":       color,
            "timestamp":   alert.triggered_at.isoformat(),
            "fields": [
                {
                    "name":   "Paire",
                    "value":  str(alert.symbol),
                    "inline": True,
                },
                {
                    "name":   "Période",
                    "value":  alert.timeframe.label,
                    "inline": True,
                },
                {
                    "name":   "Sévérité",
                    "value":  alert.severity,
                    "inline": True,
                },
            ],
            "footer": {
                "text": "CryptoAnalyzer • Raspberry Pi 4",
            },
        }

        if with_image:
            embed["image"] = {"url": "attachment://chart.png"}

        return {
            "username":   self._username,
            "avatar_url": self._avatar_url,
            "embeds":     [embed],
        }

    # ------------------------------------------------------------------
    # Envoi HTTP avec retry
    # ------------------------------------------------------------------

    def _post_json(self, payload: dict) -> None:
        self._request_with_retry(
            method="json",
            payload=payload,
        )

    def _post_with_file(self, payload: dict, chart_file: Path) -> None:
        import json
        with chart_file.open("rb") as fh:
            self._request_with_retry(
                method="file",
                payload=payload,
                file_content=fh.read(),
                file_name=chart_file.name,
            )

    def _request_with_retry(
        self,
        method: str,
        payload: dict,
        file_content: Optional[bytes] = None,
        file_name: str = "chart.png",
    ) -> None:
        import json
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._retry + 1):
            try:
                if method == "json":
                    resp = self._session.post(
                        self._webhook_url,
                        json=payload,
                        timeout=self._timeout,
                    )
                else:
                    resp = self._session.post(
                        self._webhook_url,
                        data={"payload_json": json.dumps(payload)},
                        files={"file": (file_name, file_content, "image/png")},
                        timeout=self._timeout,
                    )

                # 204 = succès Discord pour les webhooks
                if resp.status_code in (200, 204):
                    return

                # Gestion du rate-limit Discord (429)
                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 1.0)
                    logger.warning(
                        "Rate-limit Discord, attente %.1fs (tentative %d/%d)",
                        retry_after, attempt, self._retry,
                    )
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()

            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "Tentative Discord %d/%d échouée (%s) — attente %ds",
                    attempt, self._retry, exc, wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"Impossible d'envoyer sur Discord après {self._retry} tentatives"
        ) from last_exc
