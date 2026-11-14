#!/bin/bash
# DSC Bridge Connector - one-time install on a Mac. Double-click this file (first time: right-click > Open).
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
LABEL="com.dscbridge.connector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
echo ""
echo " DSC Bridge Connector - install (Mac)"
echo " ===================================="
PY="$(command -v python3)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  echo " Python 3 was not found. Install Python 3.11+ from https://www.python.org/downloads/macos/ and run this file again."
  read -n 1 -s -r -p " Press any key to close"; echo; exit 1
fi
echo " Installing the signing libraries (in this folder, nothing system-wide) ..."
"$PY" -m venv "$DIR/venv" || { echo " Could not make the Python folder."; read -n 1 -s -r -p " Press any key to close"; exit 1; }
"$DIR/venv/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1
if ! "$DIR/venv/bin/python" -m pip install -q -r requirements.txt; then
  echo " The libraries could not be installed. Check the internet connection and run again."
  read -n 1 -s -r -p " Press any key to close"; echo; exit 1
fi
echo " Making the connector start with the Mac ..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>$LABEL</string>
	<key>ProgramArguments</key>
	<array><string>$DIR/venv/bin/python</string><string>$DIR/connector.py</string></array>
	<key>WorkingDirectory</key><string>$DIR</string>
	<key>RunAtLoad</key><true/>
	<key>KeepAlive</key><true/>
	<key>StandardOutPath</key><string>/dev/null</string>
	<key>StandardErrorPath</key><string>$DIR/connector_error.log</string>
</dict>
</plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
echo ""
STATUS="$(curl -s -m 5 http://127.0.0.1:47831/status)"
if echo "$STATUS" | grep -q '"ok": true'; then
  echo " Done. The connector is running and will start with the Mac. DSC found:"
  echo "$STATUS" | "$DIR/venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print("   ", d["cert"]["cn"], "- valid till", d["cert"]["valid_to"])'
elif echo "$STATUS" | grep -q "PKCS#11"; then
  echo " The connector is running, but the DSC token's Mac driver is not installed yet."
  echo " Install the driver from your token maker (see README.md), plug in the DSC and double-click start.command."
else
  echo " The connector is running. Plug in the DSC and open http://127.0.0.1:47831/ in Chrome to check."
fi
echo ""
read -n 1 -s -r -p " Press any key to close"; echo
