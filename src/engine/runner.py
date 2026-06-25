"""
runner.py — Points d'entrée CLI pour la crontab Raspberry Pi.

Usage :
  python -m src.engine.runner daily                # Analyse quotidienne (cron : 0 6 * * *)
  python -m src.engine.runner hourly               # Variation horaire  (cron : 0 * * * *)
  python -m src.engine.runner chart BTCUSDC 1d     # Graphique ad-hoc
  python -m src.engine.runner daily  --no-notifier # Test sans envoi Discord
  python -m src.engine.runner hourly --no-notifier # Test sans envoi Discord

Principe D : l'assemblage des dépendances est ici (composition root).
"""

import argparse
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging configuré tôt pour capturer les imports
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/crypto_analyzer.log"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NullNotifier — implémente INotifier sans rien envoyer (tests / debug)
# ---------------------------------------------------------------------------

from src.interfaces import Alert, INotifier  # noqa: E402


class NullNotifier(INotifier):
    """
    Notifier factice : journalise les alertes dans les logs sans les envoyer.
    Principe L : substitut transparent de DiscordNotifier.
    """

    def send(self, alert: Alert) -> None:
        logger.info(
            "[NullNotifier] Alerte NON envoyée — %s [%s] %s : %s",
            alert.symbol, alert.timeframe.label, alert.severity, alert.message,
        )

    def send_chart(self, alert: Alert, chart_path: str) -> None:
        logger.info(
            "[NullNotifier] Alerte + graphique NON envoyés — %s [%s] %s : %s | chart=%s",
            alert.symbol, alert.timeframe.label, alert.severity, alert.message, chart_path,
        )


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------

def _build_engine(config_path: str = "config/settings.json", no_notifier: bool = False):
    """Assemble toutes les dépendances. Si no_notifier=True, utilise NullNotifier."""
    from src.alerts.alert_engine import AlertEngine
    from src.alerts.alert_rules import build_default_registry
    from src.charts.chart_generator import MatplotlibChartGenerator
    from src.config_loader import JsonConfigLoader
    from src.fetchers.binance_fetcher import BinanceFetcher
    from src.indicators.technical_indicators import TechnicalIndicatorCalculator
    from src.notifiers.discord_notifier import DiscordNotifier

    config = JsonConfigLoader(config_path).load()

    fetcher    = BinanceFetcher()
    calculator = TechnicalIndicatorCalculator()
    charts     = MatplotlibChartGenerator()
    registry   = build_default_registry()

    if no_notifier:
        logger.warning("Mode --no-notifier actif : aucune notification Discord ne sera envoyée.")
        notifier = NullNotifier()
    else:
        notifier = DiscordNotifier(
            webhook_url=config["discord"]["webhook_url"],
            username=config["discord"].get("username", "CryptoAnalyzer 🤖"),
        )

    return AlertEngine(
        fetcher=fetcher,
        calculator=calculator,
        notifier=notifier,
        chart_generator=charts,
        rule_registry=registry,
        config=config,
    )


def cmd_daily(args) -> None:
    logger.info("Commande : analyse quotidienne%s", " [dry-run]" if args.no_notifier else "")
    Path("logs").mkdir(exist_ok=True)
    engine = _build_engine(args.config, no_notifier=args.no_notifier)
    alerts = engine.run_daily()
    logger.info("Terminé. %d alerte(s) émise(s).", len(alerts))


def cmd_hourly(args) -> None:
    logger.info("Commande : surveillance horaire%s", " [dry-run]" if args.no_notifier else "")
    Path("logs").mkdir(exist_ok=True)
    engine = _build_engine(args.config, no_notifier=args.no_notifier)
    alerts = engine.run_hourly()
    logger.info("Terminé. %d alerte(s) horaire(s).", len(alerts))


def cmd_chart(args) -> None:
    """Génère un graphique ad-hoc pour un symbole et une timeframe donnés."""
    from src.charts.chart_generator import MatplotlibChartGenerator
    from src.config_loader import JsonConfigLoader
    from src.fetchers.binance_fetcher import BinanceFetcher
    from src.indicators.technical_indicators import TechnicalIndicatorCalculator
    from src.interfaces import Symbol, Timeframe

    config = JsonConfigLoader(args.config).load()
    tf_value = args.timeframe

    tf_cfg = next(
        (t for t in config.get("timeframes", []) if t["value"] == tf_value),
        {"value": tf_value, "label": tf_value, "candles_chart": 90},
    )
    tf     = Timeframe(**tf_cfg)
    symbol = Symbol(args.symbol)

    fetcher    = BinanceFetcher()
    calculator = TechnicalIndicatorCalculator()
    generator  = MatplotlibChartGenerator()

    data     = fetcher.fetch(symbol, tf, limit=max(250, tf.candles_chart + 200))
    enriched = calculator.calculate(data)

    output_dir  = config.get("charts_output_dir", "charts_output")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = f"{output_dir}/{symbol}_{tf_value}_manual.png"
    path = generator.generate(data, enriched, output_path)
    print(f"Graphique généré : {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CryptoAnalyzer — Analyse technique et alertes Discord"
    )
    parser.add_argument(
        "--config", default="config/settings.json",
        help="Chemin vers le fichier de configuration JSON",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sous-commandes daily et hourly partagent --no-notifier
    for cmd_name, cmd_help in [
        ("daily",  "Lancer l'analyse quotidienne"),
        ("hourly", "Lancer la surveillance horaire"),
    ]:
        sub = subparsers.add_parser(cmd_name, help=cmd_help)
        sub.add_argument(
            "--no-notifier",
            action="store_true",
            default=False,
            help="Désactive l'envoi Discord (dry-run / test)",
        )

    chart_parser = subparsers.add_parser("chart", help="Générer un graphique ad-hoc")
    chart_parser.add_argument("symbol",    help="Symbole (ex: BTCUSDC)")
    chart_parser.add_argument("timeframe", help="Timeframe (ex: 1d, 1w, 1h)")

    args = parser.parse_args()

    if args.command == "daily":
        cmd_daily(args)
    elif args.command == "hourly":
        cmd_hourly(args)
    elif args.command == "chart":
        cmd_chart(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()