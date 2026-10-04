#!/usr/bin/env python3
"""Supprime les anciens messages publiés par le webhook CryptoAnalyzer."""

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger("discord_cleanup")
API_BASE_URL = "https://discord.com/api/v10"
PAGE_SIZE = 100


def webhook_id_from_url(webhook_url: str) -> str:
    """Extrait l'identifiant du webhook sans exposer son token."""
    parts = urlparse(webhook_url).path.strip("/").split("/")
    try:
        webhook_index = parts.index("webhooks")
        webhook_id = parts[webhook_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("URL de webhook Discord invalide dans la configuration.") from exc

    if not webhook_id.isdigit():
        raise ValueError("L'URL configurée ne contient pas d'identifiant de webhook valide.")
    return webhook_id


def discord_request(
    session: requests.Session, method: str, url: str, **kwargs
) -> requests.Response:
    for attempt in range(5):
        response = session.request(method, url, timeout=15, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response

        retry_after = float(response.json().get("retry_after", 1))
        logger.warning("Limite de requêtes Discord atteinte, pause de %.1f s.", retry_after)
        if attempt == 4:
            response.raise_for_status()
        time.sleep(retry_after)

    raise RuntimeError("La requête Discord a échoué après plusieurs tentatives.")


def clean_messages(
    session: requests.Session,
    channel_id: str,
    webhook_id: str,
    cutoff: datetime,
    dry_run: bool = False,
) -> tuple[int, int]:
    url = f"{API_BASE_URL}/channels/{channel_id}/messages"
    before = None
    deleted = 0
    matched = 0

    while True:
        params = {"limit": PAGE_SIZE}
        if before is not None:
            params["before"] = before
        response = discord_request(session, "GET", url, params=params)
        messages = response.json()
        if not messages:
            break

        for message in messages:
            if message.get("webhook_id") != webhook_id:
                continue

            created_at = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
            if created_at >= cutoff:
                continue

            matched += 1
            if dry_run:
                logger.info("À supprimer : message %s daté du %s", message["id"], created_at)
                continue

            discord_request(
                session,
                "DELETE",
                f"{url}/{message['id']}",
            )
            deleted += 1
            logger.info("Message supprimé : %s", message["id"])

        before = messages[-1]["id"]
        if len(messages) < PAGE_SIZE:
            break

    return matched, deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supprime les messages anciens du webhook CryptoAnalyzer dans un salon ou un fil Discord."
    )
    parser.add_argument(
        "--config", default="config/settings.json",
        help="Fichier JSON contenant les paramètres Discord (défaut : config/settings.json)",
    )
    parser.add_argument(
        "--days", type=float, default=7,
        help="Âge minimum des messages à supprimer, en jours (défaut : 7)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche les messages concernés sans les supprimer",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.days <= 0:
        parser.error("--days doit être strictement positif.")

    config_path = Path(args.config)
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    discord_config = config.get("discord", {})
    channel_id = discord_config.get("channel_id")
    if not channel_id:
        parser.error("Renseignez discord.channel_id dans le fichier de configuration.")
    if not channel_id.isdigit():
        parser.error("discord.channel_id doit être un identifiant Discord numérique.")

    bot_token = discord_config.get("bot_token")
    if not bot_token:
        parser.error("Renseignez discord.bot_token dans le fichier de configuration.")

    webhook_id = webhook_id_from_url(discord_config["webhook_url"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bot {bot_token}"})
        matched, deleted = clean_messages(
            session,
            channel_id,
            webhook_id,
            cutoff,
            dry_run=args.dry_run,
        )

    if args.dry_run:
        logger.info("Simulation terminée : %d message(s) seraient supprimés.", matched)
    else:
        logger.info("Nettoyage terminé : %d message(s) supprimé(s).", deleted)


if __name__ == "__main__":
    main()