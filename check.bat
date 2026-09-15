@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "CHOPPER_PYTHON=%~dp0.venv\Scripts\python.exe"
"%CHOPPER_PYTHON%" -m ruff check .
if errorlevel 1 goto failed
"%CHOPPER_PYTHON%" -m ruff format --check .
if errorlevel 1 goto failed
"%CHOPPER_PYTHON%" -m mypy
if errorlevel 1 goto failed
"%CHOPPER_PYTHON%" -m pytest
if errorlevel 1 goto failed
popd
exit /b 0

:failed
popd
exit /b 1
