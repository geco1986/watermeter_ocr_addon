#!/bin/bash
# ===========================================================================
# Ollama-Setup fuer Raspberry Pi 4 - Wasserzaehler-OCR
# ===========================================================================
# Ausfuehren auf dem Pi selbst (per SSH oder Terminal):
#   chmod +x install_ollama_pi.sh
#   ./install_ollama_pi.sh
# ===========================================================================

set -e

MODEL="moondream"

echo "=== 1. System-Checks ==="

ARCH=$(uname -m)
echo "Architektur: $ARCH"
if [ "$ARCH" != "aarch64" ]; then
  echo "FEHLER: Es wird ein 64-bit-OS (aarch64) benoetigt, gefunden: $ARCH"
  echo "Bitte den Pi mit einem 64-bit Raspberry Pi OS (Bookworm) neu flashen."
  exit 1
fi

RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
echo "RAM: ${RAM_MB} MB"
if [ "$RAM_MB" -lt 2500 ]; then
  echo ""
  echo "WARNUNG: Sehr wenig RAM erkannt (${RAM_MB} MB)."
  echo "Das Modell ${MODEL} braucht ca. 2 GB. Mit weniger wird es eng."
  echo ""
  read -p "Trotzdem fortfahren? (j/N) " ANSWER
  if [ "$ANSWER" != "j" ] && [ "$ANSWER" != "J" ]; then
    echo "Abgebrochen."
    exit 1
  fi
fi

echo ""
echo "=== 2. Ollama installieren ==="
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama ist bereits installiert ($(ollama --version 2>/dev/null | head -1))."
  echo "Aktualisiere per Install-Skript (aktualisiert in-place)..."
fi
curl -fsSL https://ollama.com/install.sh | sh

echo ""
echo "=== 3. Ollama im Netzwerk erreichbar machen ==="
# Standardmaessig lauscht Ollama nur auf 127.0.0.1. Damit Home Assistant
# vom anderen Rechner aus zugreifen kann, muss OLLAMA_HOST auf 0.0.0.0.
OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
sudo mkdir -p "$OVERRIDE_DIR"
sudo tee "$OVERRIDE_DIR/override.conf" >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

echo ""
echo "=== 4. Vision-Modell herunterladen ==="
echo "Lade ${MODEL} (ca. 1.5 GB, kann auf dem Pi etwas dauern)..."
ollama pull "$MODEL"

echo ""
echo "=== 5. Fertig ==="
IP=$(hostname -I | awk '{print $1}')
echo "Ollama laeuft jetzt und ist erreichbar unter:"
echo "    http://${IP}:11434"
echo ""
echo "Diese IP traegst du gleich in die Add-on-Konfiguration ein"
echo "(Option 'ollama_url'):"
echo "    http://${IP}:11434/api/generate"
echo ""
echo "Test von einem anderen Rechner aus:"
echo "    curl http://${IP}:11434/api/tags"
