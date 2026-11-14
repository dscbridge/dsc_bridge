@echo off
rem DSC Bridge Connector - stop the running connector (only the connector, not other Python programs)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*connector.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo  DSC Bridge Connector stopped.
