@echo off
rem DSC Bridge Connector - stop it and take it out of Windows start-up. Then the folder can be deleted.
call "%~dp0stop.bat" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DSC Bridge Connector.lnk" >nul 2>&1
echo.
echo  DSC Bridge Connector removed from start-up and stopped.
echo  You can now delete the folder %LOCALAPPDATA%\DSCBridge
echo.
pause
