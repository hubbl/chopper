@echo off
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\python.exe" -m chopper %*
