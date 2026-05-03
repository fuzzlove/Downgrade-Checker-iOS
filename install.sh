#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Apple TSS Downgrade Monitor"
VENV_DIR=".venv"
SCRIPT_NAME="downgrade_monitor.py"
TOOLS_DIR="tools"
TSSCHECKER_PATH="$TOOLS_DIR/tsschecker"

echo "======================================"
echo "$APP_NAME Installer"
echo "======================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 is not installed."
  echo "Install it with: brew install python"
  exit 1
fi

echo "[+] Creating project folders..."
mkdir -p "$TOOLS_DIR"
mkdir -p downgrade_cache/buildmanifests

echo "[+] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"

echo "[+] Upgrading pip..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

echo "[+] Installing Python requirements..."
"$VENV_DIR/bin/pip" install -r requirements.txt

echo "[+] Checking for tsschecker..."
if [[ -x "$TSSCHECKER_PATH" ]]; then
  echo "[+] Found local tsschecker: $TSSCHECKER_PATH"
elif command -v tsschecker >/dev/null 2>&1; then
  echo "[+] Found system tsschecker: $(command -v tsschecker)"
else
  echo "[!] tsschecker was not found."
  echo ""
  echo "Place the tsschecker binary here:"
  echo "  $TSSCHECKER_PATH"
  echo ""
  echo "Then run:"
  echo "  chmod +x $TSSCHECKER_PATH"
  echo ""
fi

echo "[+] Creating launcher: run.sh"
cat > run.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d ".venv" ]]; then
  echo "[ERROR] Virtual environment not found. Run ./install.sh first."
  exit 1
fi

if [[ ! -f "downgrade_monitor.py" ]]; then
  echo "[ERROR] downgrade_monitor.py not found in this folder."
  exit 1
fi

source .venv/bin/activate
python downgrade_monitor.py
EOF

chmod +x run.sh

echo ""
echo "======================================"
echo "Install complete."
echo "======================================"
echo ""
echo "Run with:"
echo "  ./run.sh"
echo ""
echo "If needed, add tsschecker here:"
echo "  $TSSCHECKER_PATH"
