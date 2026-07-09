#!/bin/bash
# Script de configuração inicial de VPS Ubuntu 22.04 LTS (Oracle Cloud, GCP ou qualquer provedor).
# Execute UMA VEZ como root logo após criar o VPS.
# Uso: bash setup_vps.sh
#
# Nota (Oracle Cloud / OCI): além do Security List/NSG da VCN, as imagens Ubuntu da
# Oracle bloqueiam portas via iptables no próprio SO. Depois do setup, rode:
#   sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
#   sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
#   sudo netfilter-persistent save
set -euo pipefail

APP_DIR="/var/www/valor-classico"
REPO_URL="https://github.com/anacarolinajustino/valor-classico.git"  # ajuste se necessário
DEPLOY_USER="deploy"
PY_VERSION="python3.11"
PG_DB="valor_classico"
PG_USER="valor_user"

echo "===== [1/9] Atualizar pacotes ====="
apt-get update -y && apt-get upgrade -y

echo "===== [2/9] Instalar dependências do sistema ====="
apt-get install -y \
    git curl nginx \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    postgresql postgresql-contrib \
    build-essential libpq-dev \
    certbot python3-certbot-nginx

echo "===== [3/9] Criar usuário de deploy ====="
if ! id "$DEPLOY_USER" &>/dev/null; then
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

# Permitir restart do serviço sem senha (necessário para o deploy.sh)
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart valor-classico, /bin/systemctl reload valor-classico" \
    > /etc/sudoers.d/valor-classico
chmod 440 /etc/sudoers.d/valor-classico

echo "===== [4/9] Clonar repositório ====="
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER":"$DEPLOY_USER" "$APP_DIR"
sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$APP_DIR"

echo "===== [5/9] Criar virtualenv e instalar dependências Python ====="
sudo -u "$DEPLOY_USER" $PY_VERSION -m venv "$APP_DIR/venv"
sudo -u "$DEPLOY_USER" bash -c "
    source $APP_DIR/venv/bin/activate
    pip install --upgrade pip
    pip install -r $APP_DIR/requirements.txt
"

echo "===== [6/9] Instalar Playwright e navegador Chromium ====="
mkdir -p /opt/playwright-browsers
chown "$DEPLOY_USER":"$DEPLOY_USER" /opt/playwright-browsers
sudo -u "$DEPLOY_USER" bash -c "
    export PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
    source $APP_DIR/venv/bin/activate
    playwright install chromium
    playwright install-deps chromium
"

echo "===== [7/9] Configurar PostgreSQL ====="
PG_PASSWORD=$(openssl rand -base64 32)
sudo -u postgres psql <<SQL
CREATE USER $PG_USER WITH PASSWORD '$PG_PASSWORD';
CREATE DATABASE $PG_DB OWNER $PG_USER;
GRANT ALL PRIVILEGES ON DATABASE $PG_DB TO $PG_USER;
SQL
echo ""
echo ">>> ANOTE: DATABASE_URL=postgresql://$PG_USER:$PG_PASSWORD@localhost:5432/$PG_DB"
echo ""

echo "===== [8/9] Criar arquivo de ambiente ====="
# Preencha os valores abaixo antes de continuar
cat > "$APP_DIR/.env.production" <<EOF
DATABASE_URL=postgresql://$PG_USER:$PG_PASSWORD@localhost:5432/$PG_DB
PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
ML_CLIENT_ID=PREENCHA
ML_CLIENT_SECRET=PREENCHA
DATAIMPULSE_HOST=PREENCHA
DATAIMPULSE_PORT=PREENCHA
DATAIMPULSE_USER=PREENCHA
DATAIMPULSE_PASS=PREENCHA
EOF
chown "$DEPLOY_USER":"$DEPLOY_USER" "$APP_DIR/.env.production"
chmod 600 "$APP_DIR/.env.production"

echo "===== [9/9] Configurar diretório de logs ====="
mkdir -p /var/log/valor-classico
chown "$DEPLOY_USER":"$DEPLOY_USER" /var/log/valor-classico

echo ""
echo "===== SETUP CONCLUÍDO ====="
echo "Próximos passos manuais:"
echo "  1. Edite $APP_DIR/.env.production com ML_CLIENT_ID, ML_CLIENT_SECRET e DATAIMPULSE_*"
echo "  2. Copie vps/valor-classico.service para /etc/systemd/system/"
echo "  3. Copie vps/nginx.conf para /etc/nginx/sites-available/valor-classico"
echo "  4. Ative nginx e habilite SSL com certbot"
echo "  5. Inicie o serviço com: systemctl enable --now valor-classico"
