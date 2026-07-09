#!/bin/bash
# Script de deploy executado no VPS pela GitHub Action.
# Chamado via SSH: bash /var/www/valor-classico/deploy.sh
set -euo pipefail

APP_DIR="/var/www/valor-classico"
VENV="$APP_DIR/venv"
SERVICE="valor-classico"

echo "[deploy] Atualizando código..."
cd "$APP_DIR"
git pull origin main

echo "[deploy] Instalando dependências Python..."
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "[deploy] Reiniciando serviço..."
sudo systemctl restart "$SERVICE"

echo "[deploy] Concluído com sucesso!"
