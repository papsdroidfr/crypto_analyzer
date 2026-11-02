#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, time
import time as t_module
import requests
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106

class SystemMonitor:
    """Gère la lecture des capteurs système du Raspberry Pi."""
    
    @staticmethod
    def get_cpu_temperature() -> float:
        """Récupère la température interne du SoC Raspberry Pi."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_milli = int(f.read().strip())
                return temp_milli / 1000.0
        except Exception:
            return 0.0

class BinanceClient:
    """Interagit avec l'API publique Binance pour récupérer les tickers 24h."""
    
    BASE_URL = "https://api.binance.com/api/v3/ticker/24hr"

    def __init__(self, symbols: list[str]):
        self.symbols = symbols

    def fetch_market_data(self) -> dict[str, dict]:
        """Récupère les données pour les paires configurées."""
        data = {}
        response = requests.get(self.BASE_URL, timeout=5)
        response.raise_for_status()
        market_data = {item['symbol']: item for item in response.json()}

        for symbol in self.symbols:
            if symbol in market_data:
                ticker = market_data[symbol]
                data[symbol] = {
                    "price": float(ticker['lastPrice']),
                    "price_change_percent": float(ticker['priceChangePercent'])
                }
        return data

class OLEDRenderer:
    """Gère l'affichage des données sur l'écran SH1106 1.3' via luma.oled et canvas."""

    def __init__(self, port: int = 1, address: int = 0x3C):
        self.serial = i2c(port=port, address=address)
        self.device = sh1106(self.serial, width=128, height=64, rotate=0)

    def power_off(self):
        """Éteint complètement l'écran OLED (veille)."""
        self.device.hide()

    def power_on(self):
        """Rallume l'écran OLED."""
        self.device.show()

    def display_market_status(self, market_data: dict[str, dict], cpu_temp: float):
        """Génère l'affichage optimisé des marchés avec colonnes alignées."""
        with canvas(self.device) as draw:
            # Ligne d'en-tête : Date à gauche, | au centre (x=61), Température à droite
            now_str = datetime.now().strftime("%d/%m %H:%M")
            temp_str = f"{cpu_temp:.1f}°C"
            
            draw.text((0, 0), now_str, fill="white")
            draw.text((61, 0), "|", fill="white")
            
            temp_x = 128 - (len(temp_str) * 6)
            draw.text((temp_x, 0), temp_str, fill="white")
            
            draw.line((0, 10, self.device.width, 10), fill="white")

            y_offset = 13
            for symbol, info in market_data.items():
                short_name = symbol.replace("USDC", "")
                price = info["price"]
                change = info["price_change_percent"]

                # Indicateur visuel de tendance (+ ou -)
                trend_char = "+" if change >= 0 else "-"

                if price < 1:
                    price_str = f"{price:.4f}"
                elif price < 10:
                    price_str = f"{price:.3f}"
                elif price < 1000:
                    price_str = f"{price:.2f}"
                else:
                    price_str = f"{int(price):,}".replace(",", " ")

                change_str = f"({change:+.1f}%)"

                # Colonne 1 (Gauche) : Tendance + Nom de la crypto (ex: "+ BTC")
                left_text = f"{trend_char} {short_name}"
                draw.text((0, y_offset), left_text, fill="white")

                # Colonne 2 (Centre) : Prix
                draw.text((42, y_offset), price_str, fill="white")

                # Colonne 3 (Droite) : Pourcentage de variation
                draw.text((86, y_offset), change_str, fill="white")

                y_offset += 10

    def display_offline_status(self, cpu_temp: float):
        """Affiche un écran d'alerte en cas de perte de connexion réseau."""
        with canvas(self.device) as draw:
            now_str = datetime.now().strftime("%d/%m %H:%M")
            temp_str = f"{cpu_temp:.1f}°C"
            
            draw.text((0, 0), now_str, fill="white")
            draw.text((61, 0), "|", fill="white")
            
            temp_x = 128 - (len(temp_str) * 6)
            draw.text((temp_x, 0), temp_str, fill="white")
            
            draw.line((0, 10, self.device.width, 10), fill="white")

            draw.text((10, 22), "! PAS DE RESEAU !", fill="white")
            draw.text((14, 38), "Connexion perdue", fill="white")

class CryptoAppController:
    """Orchestre la boucle continue de récupération et d'affichage."""

    def __init__(self):
        self.symbols = ["BTCUSDC", "ETHUSDC", "NEARUSDC", "TAOUSDC", "HYPEUSDC"]
        self.binance_client = BinanceClient(self.symbols)
        self.renderer = OLEDRenderer()
        self.system_monitor = SystemMonitor()

    def _is_night_time(self) -> bool:
        """Vérifie si l'heure actuelle est comprise entre 22h30 et 7h00."""
        now = datetime.now().time()
        start_night = time(22, 30)
        end_night = time(7, 0)
        
        if start_night <= now or now < end_night:
            return True
        return False

    def run_loop(self):
        """Exécute la boucle infinie de mise à jour toutes les 5 minutes."""
        print("Démarrage du service d'affichage crypto ergonomique...")
        while True:
            try:
                cpu_temp = self.system_monitor.get_cpu_temperature()

                if self._is_night_time():
                    self.renderer.power_off()
                else:
                    self.renderer.power_on()
                    try:
                        market_data = self.binance_client.fetch_market_data()
                        if market_data:
                            self.renderer.display_market_status(market_data, cpu_temp)
                    except Exception as e:
                        print(f"Mode hors-ligne activé (Erreur: {e})")
                        self.renderer.display_offline_status(cpu_temp)
                
                t_module.sleep(300)
            except KeyboardInterrupt:
                print("Arrêt demandé par l'utilisateur.")
                break
            except Exception as e:
                print(f"Erreur inattendue dans la boucle : {e}")
                t_module.sleep(30)

if __name__ == "__main__":
    app = CryptoAppController()
    app.run_loop()