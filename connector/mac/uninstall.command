#!/bin/bash
# DSC Bridge Connector - remove the auto-start from this Mac (the folder itself you can delete after this)
LABEL="com.dscbridge.connector"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo " DSC Bridge Connector removed from this Mac's start-up."
read -n 1 -s -r -p " Press any key to close"; echo
