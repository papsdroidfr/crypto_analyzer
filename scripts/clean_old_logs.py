#!/usr/bin/env python3
"""Supprime les anciens fichiers de log et graphiques."""

import argparse
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
CHARTS_DIR = Path(__file__).resolve().parents[1] / "charts_output"


def clean_old_files(directory: Path, pattern: str, days: int) -> int:
    cutoff = time.time() - days * 24 * 60 * 60
    removed = 0

    if not directory.is_dir():
        return removed

    for file_path in directory.glob(pattern):
        if file_path.is_file() and file_path.stat().st_mtime < cutoff:
            file_path.unlink()
            print(f"Supprimé : {file_path.name}")
            removed += 1

    return removed


def clean_logs(log_dir: Path, days: int) -> int:
    return clean_old_files(log_dir, "*.log", days)


def clean_charts(charts_dir: Path, days: int) -> int:
    return clean_old_files(charts_dir, "*.png", days)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supprime les anciens fichiers de log et graphiques."
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

    removed_logs = clean_logs(LOG_DIR, args.days)
    removed_charts = clean_charts(CHARTS_DIR, args.days)
    total_removed = removed_logs + removed_charts
    print(
        f"Nettoyage terminé : {total_removed} fichier(s) supprimé(s) "
        f"(logs : {removed_logs}, graphiques : {removed_charts})."
    )


if __name__ == "__main__":
    main()