#!/usr/bin/env python3
"""Supprime les fichiers de log plus anciens que la durée indiquée."""

import argparse
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def clean_logs(log_dir: Path, days: int) -> int:
    cutoff = time.time() - days * 24 * 60 * 60
    removed = 0

    if not log_dir.is_dir():
        return removed

    for log_file in log_dir.glob("*.log"):
        if log_file.is_file() and log_file.stat().st_mtime < cutoff:
            log_file.unlink()
            print(f"Supprimé : {log_file.name}")
            removed += 1

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supprime les fichiers de log anciens du dossier logs."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Âge minimum des logs à supprimer, en jours (défaut : 7)",
    )
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days doit être strictement positif.")

    removed = clean_logs(LOG_DIR, args.days)
    print(f"Nettoyage terminé : {removed} fichier(s) supprimé(s).")


if __name__ == "__main__":
    main()