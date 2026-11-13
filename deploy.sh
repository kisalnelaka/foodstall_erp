#!/usr/bin/env bash
# ==============================================================================
# Sumiyuru Catering & Roadside Stall ERP - Automated VPS Deployment Script
# Supports: Ubuntu, Debian, Arch Linux, Rocky/CentOS
# ==============================================================================

set -euo pipefail

echo "=================================================================="
echo "  SUMIYURU STALL ERP & CASH COCKPIT - VPS DEPLOYMENT SYSTEM"
echo "=================================================================="

APP_DIR="/opt/sumiyuru-stall-erp"
PORT="${PORT:-8080}"

# 1. Check for root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root or with sudo: sudo ./deploy.sh"
  exit 1
fi

echo "[1/4] Checking and installing dependencies..."
if command -v docker &>/dev/null && command -v docker-compose &>/dev/null; then
  DEPLOY_MODE="docker"
  echo "[+] Docker and Docker Compose detected. Using Containerized Deployment."
elif command -v python3 &>/dev/null; then
  DEPLOY_MODE="native"
  echo "[+] Python3 detected. Using Native Systemd Service Deployment."
else
  echo "[*] Installing Python 3 & pip..."
  if command -v apt-get &>/dev/null; then
    apt-get update -y && apt-get install -y python3 python3-pip sqlite3
  elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm python python-pip sqlite
  elif command -v dnf &>/dev/null; then
    dnf install -y python3 python3-pip sqlite
  fi
  DEPLOY_MODE="native"
fi

# 2. Deploy codebase
echo "[2/4] Setting up application in ${APP_DIR}..."
mkdir -p "${APP_DIR}"
cp -ru ./* "${APP_DIR}/"
cd "${APP_DIR}"

# 3. Launch service
if [ "${DEPLOY_MODE}" = "docker" ]; then
  echo "[3/4] Building and launching Docker container..."
  docker compose down 2>/dev/null || true
  docker compose up -d --build
  echo "[+] Docker container 'sumiyuru-erp' running on port ${PORT}!"
else
  echo "[3/4] Installing Python dependencies and configuring systemd service..."
  python3 -m pip install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
  python3 db.py

  cp sumiyuru.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable sumiyuru.service
  systemctl restart sumiyuru.service
  echo "[+] Systemd service 'sumiyuru' activated and running on port ${PORT}!"
fi

# 4. Verification
echo "[4/4] Verifying health check endpoint..."
sleep 2
if curl -sf "http://127.0.0.1:${PORT}/api/health" > /dev/null; then
  IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_VPS_IP")
  echo ""
  echo "=================================================================="
  echo "  🚀 DEPLOYMENT SUCCESSFUL!"
  echo "=================================================================="
  echo "  Access the ERP & Cash Cockpit at:"
  echo "  👉 http://${IP_ADDR}:${PORT}"
  echo ""
  echo "  To point a custom domain with automatic SSL (HTTPS):"
  echo "  Configure Caddyfile with your domain and run: docker compose up -d"
  echo "=================================================================="
else
  echo "[-] Health check failed. Check logs via:"
  if [ "${DEPLOY_MODE}" = "docker" ]; then
    echo "    docker compose logs -f"
  else
    echo "    journalctl -u sumiyuru.service -f"
  fi
  exit 1
fi
