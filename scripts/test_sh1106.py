import time
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106

# 1. On initialise l'I2C sur l'adresse valide 0x3C
serial = i2c(port=1, address=0x3C)

# 2. On force le pilote SH1106 avec les dimensions exactes (128x64).
# Parfois, l'écran nécessite une inversion ou une configuration de sous-page.
device = sh1106(serial, width=128, height=64, rotate=0)

print("Affichage stabilisé en cours... Ctrl+C pour quitter.")

try:
    while True:
        with canvas(device) as draw:
            # Efface tout et dessine un cadre propre
            draw.rectangle(device.bounding_box, outline="white", fill="black")
            
            # Écriture de texte bien aligné
            draw.text((15, 15), "SH1106 Fixe !", fill="white")
            draw.text((15, 35), "Affichage OK", fill="white")
            
        time.sleep(1)
except KeyboardInterrupt:
    print("Test arrêté.")
