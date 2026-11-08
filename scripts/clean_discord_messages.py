#!/usr/bin/env python3
"""Supprime les anciens messages publiés par les webhooks CryptoAnalyzer."""

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
        description="Supprime les messages anciens des webhooks CryptoAnalyzer dans un salon ou un fil Discord."
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
    bot_token = discord_config.get("bot_token")
    if not bot_token:
        parser.error("Renseignez discord.bot_token dans le fichier de configuration.")

    webhook_urls = discord_config.get("webhook_urls")
    if not isinstance(webhook_urls, dict) or not webhook_urls:
        parser.error("Renseignez discord.webhook_urls dans le fichier de configuration.")

    channel_ids = discord_config.get("channel_ids")
    if not isinstance(channel_ids, dict):
        parser.error("Renseignez discord.channel_ids dans le fichier de configuration.")
    if set(channel_ids) != set(webhook_urls):
        parser.error(
            "Les clés de discord.channel_ids doivent correspondre à celles de "
            "discord.webhook_urls."
        )

    webhook_ids = {}
    for name, webhook_url in webhook_urls.items():
        if not isinstance(webhook_url, str) or not webhook_url.strip():
            parser.error(f"discord.webhook_urls.{name} doit être une URL non vide.")
        channel_id = channel_ids[name]
        if not isinstance(channel_id, str) or not channel_id.isdigit():
            parser.error(
                f"discord.channel_ids.{name} doit être un identifiant Discord numérique."
            )
        try:
            webhook_ids[name] = webhook_id_from_url(webhook_url)
        except ValueError as exc:
            parser.error(f"discord.webhook_urls.{name} : {exc}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bot {bot_token}"})
        total_matched = 0
        total_deleted = 0
        for name, webhook_id in webhook_ids.items():
            channel_id = channel_ids[name]
            matched, deleted = clean_messages(
                session,
                channel_id,
                webhook_id,
                cutoff,
                dry_run=args.dry_run,
            )
            total_matched += matched
            total_deleted += deleted
            logger.info(
                "Webhook %s : %d message(s) concerné(s), %d supprimé(s).",
                name, matched, deleted,
            )

    if args.dry_run:
        logger.info(
            "Simulation terminée : %d message(s) seraient supprimés sur %d webhook(s).",
            total_matched, len(webhook_ids),
        )
    else:
        logger.info(
            "Nettoyage terminé : %d message(s) supprimé(s) sur %d webhook(s).",
            total_deleted, len(webhook_ids),
        )


if __name__ == "__main__":
    main()