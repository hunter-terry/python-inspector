@echo off
cd /d "%~dp0src"
if not exist "..\.venv\Scripts\pythonw.exe" (
    echo Python Inspector's virtual environment is missing. See README.md for setup.
    pause
    exit /b 1
)
start "" "..\.venv\Scripts\pythonw.exe" -m inspector_app.main
