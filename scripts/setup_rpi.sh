#!/usr/bin/env bash
# =============================================================================
# setup_rpi.sh — Installation complète sur Raspberry Pi 4 (OS Lite headless)
# =============================================================================
# Usage :
#   chmod +x scripts/setup_rpi.sh
#   ./scripts/setup_rpi.sh
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

# --- 6. Configuration de la crontab ----------------------------------------
echo ""
echo "[6/6] Configuration de la crontab..."

PYTHON_BIN="${VENV_DIR}/bin/python"
DAILY_CMD="0 6 * * * cd ${PROJECT_DIR} && ${PYTHON_BIN} -m src.engine.runner daily >> ${PROJECT_DIR}/logs/cron_daily.log 2>&1"
HOURLY_CMD="0 * * * * cd ${PROJECT_DIR} && ${PYTHON_BIN} -m src.engine.runner hourly >> ${PROJECT_DIR}/logs/cron_hourly.log 2>&1"

# Ajout si pas déjà présent
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

if echo "${CURRENT_CRON}" | grep -qF "runner daily"; then
    echo "  ℹ️   Tâche quotidienne déjà présente dans crontab."
else
    (echo "${CURRENT_CRON}"; echo "${DAILY_CMD}") | crontab -
    echo "  ✅  Tâche quotidienne ajoutée (tous les jours à 6h00)."
fi

if echo "${CURRENT_CRON}" | grep -qF "runner hourly"; then
    echo "  ℹ️   Tâche horaire déjà présente dans crontab."
else
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)
    (echo "${CURRENT_CRON}"; echo "${HOURLY_CMD}") | crontab -
    echo "  ✅  Tâche horaire ajoutée (toutes les heures)."
fi

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
echo "  3. Vérifiez la crontab :"
echo "     crontab -l"
echo "========================================================="
