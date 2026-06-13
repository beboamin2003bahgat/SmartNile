#!/usr/bin/env bash
# =============================================================================
# Smart Nile — Raspberry Pi 5 Setup Script
# =============================================================================
# Run as the 'pi' user (NOT root):
#   chmod +x setup.sh
#   ./setup.sh
#
# What this does:
#   1. Updates the system
#   2. Enables 1-Wire (DS18B20) and Serial UART (GPS + Arduino) interfaces
#   3. Installs Python dependencies
#   4. Installs and starts the systemd service
#   5. Verifies the installation
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$BACKEND_DIR")"

YELLOW='\033[1;33m'; GREEN='\033[0;32m'; RED='\033[0;31m'; RESET='\033[0m'
info()    { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
heading() { echo -e "\n${YELLOW}══ $* ══${RESET}"; }

# ── check we're not root ─────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    error "Do NOT run as root. Run as the 'pi' user: ./setup.sh"
fi

heading "1 / 7  System update"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
info "System updated"

heading "2 / 7  System packages"
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    python3-picamera2 \
    libatlas-base-dev \
    libopenblas-dev \
    libjpeg-dev \
    sqlite3 \
    git \
    i2c-tools
info "System packages installed"

heading "3 / 7  Hardware interfaces"

# Enable 1-Wire for DS18B20
if ! grep -q "dtoverlay=w1-gpio" /boot/config.txt 2>/dev/null && \
   ! grep -q "dtoverlay=w1-gpio" /boot/firmware/config.txt 2>/dev/null; then
    CONFIG_FILE="/boot/firmware/config.txt"
    [[ -f /boot/config.txt ]] && CONFIG_FILE="/boot/config.txt"
    echo "dtoverlay=w1-gpio" | sudo tee -a "$CONFIG_FILE" > /dev/null
    warn "1-Wire enabled in $CONFIG_FILE — reboot required"
else
    info "1-Wire already enabled"
fi

# Disable serial console (needed for GPS UART)
if grep -q "console=serial" /boot/cmdline.txt 2>/dev/null || \
   grep -q "console=serial" /boot/firmware/cmdline.txt 2>/dev/null; then
    warn "Serial console detected. Disable it manually:"
    warn "  sudo raspi-config → Interface Options → Serial Port"
    warn "  'Login shell over serial?' → No   |   'Serial port hardware?' → Yes"
else
    info "Serial console not detected (GPS UART should be available)"
fi

# Add pi user to required groups
sudo usermod -aG dialout,gpio,i2c,video pi 2>/dev/null || true
info "User 'pi' added to dialout, gpio, i2c, video groups"

heading "4 / 7  Python virtual environment"
cd "$BACKEND_DIR"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    info "Virtual environment created at $BACKEND_DIR/.venv"
else
    info "Virtual environment already exists"
fi

source .venv/bin/activate
pip install --upgrade pip -q

heading "5 / 7  Python dependencies"
pip install -r "$SCRIPT_DIR/requirements.txt" -q
info "Python packages installed"

heading "6 / 7  Environment file"
ENV_FILE="$PROJECT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$BACKEND_DIR/.env.example" "$ENV_FILE"
    warn ".env file created from template at $ENV_FILE"
    warn "Edit it now to set FIREBASE_PROJECT_ID, API keys, and ports:"
    warn "  nano $ENV_FILE"
else
    info ".env file already exists at $ENV_FILE"
fi

heading "7 / 7  systemd service"
SERVICE_SRC="$SCRIPT_DIR/smartnile.service"
SERVICE_DST="/etc/systemd/system/smartnile.service"

# Update paths in service file to match actual install location
sed "s|/home/pi/smartnile|$PROJECT_DIR|g; \
     s|ExecStart=.*|ExecStart=$BACKEND_DIR/.venv/bin/python $BACKEND_DIR/main.py|" \
    "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable smartnile.service
info "systemd service installed and enabled"

# ── summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  Smart Nile setup complete!${RESET}"
echo -e "${GREEN}════════════════════════════════════════════${RESET}"
echo ""
echo "Next steps:"
echo "  1. Edit the .env file:  nano $ENV_FILE"
echo "  2. Add Firebase credentials JSON to:  $BACKEND_DIR/config/firebase_credentials.json"
echo "  3. Add your YOLO/TFLite model to:  $BACKEND_DIR/models/plant_detect.tflite"
echo "  4. Reboot (required for 1-Wire and UART changes):"
echo "       sudo reboot"
echo "  5. After reboot, start the service:"
echo "       sudo systemctl start smartnile"
echo "  6. Check logs:"
echo "       sudo journalctl -u smartnile -f"
echo "       # or:"
echo "       tail -f $BACKEND_DIR/data/logs/smartnile_\$(date +%Y-%m-%d).log"
echo ""
echo "Test in simulation mode (no hardware needed):"
echo "  cd $BACKEND_DIR"
echo "  SIMULATION_MODE=True .venv/bin/python main.py"
echo ""
