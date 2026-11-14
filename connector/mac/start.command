#!/bin/bash
# DSC Bridge Connector - (re)start on this Mac
LABEL="com.dscbridge.connector"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ ! -f "$PLIST" ]; then echo " Not installed yet: double-click install.command first."; read -n 1 -s -r -p " Press any key to close"; exit 1; fi
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
echo " DSC Bridge Connector started. Status:"; curl -s -m 5 http://127.0.0.1:47831/status; echo
read -n 1 -s -r -p " Press any key to close"; echo
