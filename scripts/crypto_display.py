#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
import os
import requests
from PIL import Image, ImageDraw, ImageFont
import board
import digitalio
import adafruit_ssd1306

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
        """Récupère les données pour les paires configurées. 
        Lève une exception en cas de problème réseau.
        """
        data = {}
        # Lève requests.RequestException en cas de timeout ou d'absence de réseau
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
    """Gère l'affichage des données sur l'écran OLED SSD1306 128x64 I2C."""

    def __init__(self, width: int = 128, height: int = 64):
        self.width = width
        self.height = height
        
        # Initialisation I2C et écran
        i2c = board.I2C()
        # Adresse I2C par défaut du SSD1306 : 0x3C
        self.disp = adafruit_ssd1306.SSD1306_I2C(width, height, i2c, addr=0x3C)
        
        self.disp.fill(0)
        self.disp.show()

        # Chargement d'une police système par défaut
        try:
            self.font = ImageFont.load_default()
        except Exception:
            self.font = None

    def display_market_status(self, market_data: dict[str, dict], cpu_temp: float):
        """Génère l'image des marchés et l'affiche sur l'écran."""
        image = Image.new("1", (self.width, self.height))
        draw = ImageDraw.Draw(image)

        # Ligne 1 : Date, heure et température du Raspberry Pi
        now_str = datetime.now().strftime("%d/%m %H:%M")
        header_text = f"{now_str} | {cpu_temp:.1f}°C"
        draw.text((0, 0), header_text, font=self.font, fill=255)
        
        # Ligne de séparation
        draw.line((0, 10, self.width, 10), fill=255)

        # Lignes suivantes : Paires de cryptomonnaies (max 5 lignes)
        y_offset = 13
        for symbol, info in market_data.items():
            short_name = symbol.replace("USDC", "")
            price = info["price"]
            change = info["price_change_percent"]

            # Formatage dynamique du prix selon sa valeur
            if price < 1:
                price_str = f"{price:.4f}"
            elif price < 10:
                price_str = f"{price:.3f}"
            elif price < 1000:
                price_str = f"{price:.2f}"
            else:
                price_str = f"{int(price):,}".replace(",", " ")

            line_text = f"{short_name:<5} {price_str} ({change:+.1f}%)"
            draw.text((0, y_offset), line_text, font=self.font, fill=255)
            y_offset += 10

        self.disp.image(image)
        self.disp.show()

    def display_offline_status(self, cpu_temp: float):
        """Affiche un écran d'alerte en cas de perte de connexion réseau."""
        image = Image.new("1", (self.width, self.height))
        draw = ImageDraw.Draw(image)

        # Ligne 1 : Date, heure et température du Raspberry Pi
        now_str = datetime.now().strftime("%d/%m %H:%M")
        header_text = f"{now_str} | {cpu_temp:.1f}°C"
        draw.text((0, 0), header_text, font=self.font, fill=255)
        
        # Ligne de séparation
        draw.line((0, 10, self.width, 10), fill=255)

        # Message d'avertissement centré / répété verticalement
        draw.text((10, 22), "! PAS DE RESEAU !", font=self.font, fill=255)
        draw.text((14, 38), "Connexion perdue", font=self.font, fill=255)

        self.disp.image(image)
        self.disp.show()

class CryptoAppController:
    """Orchestre l'ensemble du processus de récupération et d'affichage."""

    def __init__(self):
        self.symbols = ["BTCUSDC", "ETHUSDC", "NEARUSDC", "TAOUSDC", "HYPEUSDC"]
        self.binance_client = BinanceClient(self.symbols)
        self.renderer = OLEDRenderer()
        self.system_monitor = SystemMonitor()

    def run(self):
        cpu_temp = self.system_monitor.get_cpu_temperature()
        try:
            market_data = self.binance_client.fetch_market_data()
            if market_data:
                self.renderer.display_market_status(market_data, cpu_temp)
        except Exception as e:
            # En cas d'erreur de connexion ou d'API, on bascule sur l'affichage hors-ligne
            print(f"Mode hors-ligne activé (Erreur: {e})")
            self.renderer.display_offline_status(cpu_temp)

if __name__ == "__main__":
    app = CryptoAppController()
    app.run()