@echo off
cd /d "%~dp0"
set /p T="Time to build the brief every morning (24h, e.g. 06:30) [06:30]: "
if "%T%"=="" set T=06:30
schtasks /create /f /tn "Concall Morning Brief" /tr "\"%~dp0morning_brief_auto.bat\"" /sc daily /st %T%
echo.
echo Done. The brief will be built daily at %T% (laptop must be on and logged in).
echo Open it with "Morning Brief.bat" or menu option 6. To remove: schtasks /delete /tn "Concall Morning Brief"
pause
