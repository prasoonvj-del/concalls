@echo off
cd /d "%~dp0"
echo Installing libraries...
python -m pip install --no-cache-dir -r requirements.txt
echo.
echo Done. Now open config.ini in Notepad and paste your Gemini key.
pause
