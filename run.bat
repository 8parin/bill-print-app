@echo off

:: Always run from the folder where run.bat lives
cd /d "%~dp0"

echo ===========================
echo Starting Bill Print Webapp
echo ===========================
echo.
echo Server will start on http://localhost:5003
echo Your browser will open automatically...
echo.
echo Press Ctrl+C to stop the server
echo.

:: Try python, then py launcher, then python3
set PYTHON_CMD=

python --version >nul 2>&1
if not errorlevel 1 set PYTHON_CMD=python

if "%PYTHON_CMD%"=="" (
    py --version >nul 2>&1
    if not errorlevel 1 set PYTHON_CMD=py
)

if "%PYTHON_CMD%"=="" (
    python3 --version >nul 2>&1
    if not errorlevel 1 set PYTHON_CMD=python3
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python not found. Please run install.bat first.
    pause
    exit /b 1
)

%PYTHON_CMD% app.py

pause
