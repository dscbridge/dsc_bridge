#!/bin/bash
# DSC Bridge Connector - stop on this Mac (it starts again at the next login; start.command starts it now)
launchctl bootout "gui/$(id -u)/com.dscbridge.connector" >/dev/null 2>&1
echo " DSC Bridge Connector stopped."
read -n 1 -s -r -p " Press any key to close"; echo
