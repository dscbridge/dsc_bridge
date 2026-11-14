@echo off
rem DSC Bridge Connector - one-time install on a Windows 10/11 PC. Nothing else to install: Python and the signing
rem libraries are inside this folder (one-click kit). Only the DSC token's own driver must be on the PC (it is,
rem wherever that DSC is already used for GST / Income Tax / MCA signing).
setlocal
cd /d "%~dp0"
echo.
echo  DSC Bridge Connector - install
echo  ==============================
if not exist "%~dp0python\pythonw.exe" (
  echo  Files are missing. Right-click the downloaded zip - "Extract All" - then run install.bat
  echo  from the extracted folder.
  pause
  exit /b 1
)
set "DEST=%LOCALAPPDATA%\DSCBridge"

echo  Stopping an older connector, if one is running ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*connector.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

if /I "%~dp0"=="%DEST%\" goto copied
echo  Copying to %DEST% ...
robocopy "%~dp0." "%DEST%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XF config.json connector.log >nul
if errorlevel 8 (
  echo  Could not copy the files to %DEST%.
  pause
  exit /b 1
)
:copied
rem files from a downloaded zip carry the "came from the internet" mark: clear it so Windows does not stop them
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%DEST%' -Recurse -File | Unblock-File" >nul 2>&1

echo  Checking the signing libraries ...
"%DEST%\python\python.exe" -c "import pyhanko, pkcs11, cryptography; print('  OK')"
if errorlevel 1 (
  echo  The signing libraries did not load. Send a photo of this window to your IT support.
  pause
  exit /b 1
)

echo  Making the connector start with Windows ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\DSC Bridge Connector.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%DEST%\start.vbs\"'; $s.WorkingDirectory='%DEST%'; $s.Description='DSC Bridge Connector'; $s.Save()"

wscript "%DEST%\start.vbs"
timeout /t 4 >nul
start "" "http://127.0.0.1:47831/"
echo.
echo  Done. The connector is running and will start with Windows.
echo  The browser now shows the DSC token and certificate. If it says the token or driver is not found,
echo  plug in the DSC token / install its driver, then run start.vbs in %DEST%.
echo.
pause
