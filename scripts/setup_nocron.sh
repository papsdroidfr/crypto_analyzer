#!/usr/bin/env bash
# =============================================================================
# setup_nocron.sh — Installation complète sans crontab
# =============================================================================
# Usage :
#   chmod +x scripts/setup_nocron.sh
#   ./scripts/setup_nocron.sh
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
PYTHON_MIN="3.11"

echo "========================================================="
echo "  CryptoAnalyzer — Installation Raspberry Pi 4"
echo "  Répertoire : ${PROJECT_DIR}"
echo "========================================================="

# --- 1. Vérification Python -----------------------------------------------
echo ""
echo "[1/6] Vérification de Python..."
if ! command -v python3 &>/dev/null; then
    echo "  ❌  Python3 introuvable. Installation..."
    sudo apt-get update -q
    sudo apt-get install -y python3 python3-pip python3-venv
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✅  Python ${PY_VERSION} détecté."

# --- 2. Dépendances système ------------------------------------------------
echo ""
echo "[2/6] Installation des dépendances système..."
sudo apt-get update -q
sudo apt-get install -y \
    libatlas-base-dev \
    libopenblas-dev \
    libfreetype6-dev \
    libpng-dev \
    libjpeg-dev \
    pkg-config \
    git \
    --no-install-recommends
echo "  ✅  Dépendances système installées."

# --- 3. Création du venv ---------------------------------------------------
echo ""
echo "[3/6] Création de l'environnement virtuel..."
if [ -d "${VENV_DIR}" ]; then
    echo "  ℹ️   venv existant détecté — suppression et recréation."
    rm -rf "${VENV_DIR}"
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
echo "  ✅  venv créé : ${VENV_DIR}"

# --- 4. Installation des packages Python -----------------------------------
echo ""
echo "[4/6] Installation des packages Python..."
pip install --upgrade pip --quiet
pip install -r "${PROJECT_DIR}/requirements.txt" --quiet
echo "  ✅  Packages installés."

# --- 5. Création des répertoires de travail --------------------------------
echo ""
echo "[5/6] Création des répertoires de travail..."
mkdir -p "${PROJECT_DIR}/logs"
mkdir -p "${PROJECT_DIR}/charts_output"
echo "  ✅  Répertoires créés."


echo ""
echo "========================================================="
echo "  ✅  Installation terminée !"
echo ""
echo "  Prochaines étapes :"
echo "  1. Éditez config/settings.json"
echo "     → Ajoutez votre webhook Discord"
echo "     → Ajoutez votre clé API CryptoCompare (optionnel)"
echo "     → Personnalisez les règles d'alertes"
echo ""
echo "  2. Testez manuellement :"
echo "     source venv/bin/activate"
echo "     python -m src.engine.runner hourly"
echo "     python -m src.engine.runner daily"
echo "     python -m src.engine.runner chart BTCUSDC 1d"
echo ""
echo "  3. Installer la crontab pour exécuter les tâches automatiquement :"
echo "     chmod +x scripts/setup_crontab.sh"
echo "     ./scripts/setup_crontab.sh"
echo "========================================================="
