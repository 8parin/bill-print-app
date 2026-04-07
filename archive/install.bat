@echo off

echo ==================================
echo Bill Print Webapp - Installation
echo ==================================
echo.
echo [!] IMPORTANT: If the app is currently running, stop it first!
echo     Close the Command Prompt window running the server, then re-run this script.
echo.

:: Clear stale Python bytecode from any previous install
echo Clearing cached bytecode...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
del /s /q "*.pyc" 2>nul
echo [OK] Bytecode cache cleared
echo.

:: Detect Python (try python, then py launcher, then python3)
echo Checking Python version...
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
    echo [ERROR] Python 3 is not installed or not in PATH
    echo.
    echo Please reinstall Python from https://www.python.org/downloads/
    echo and check the box "Add Python to PATH" during install,
    echo then open a NEW Command Prompt and run install.bat again.
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% --version
echo [OK] Python found
echo.

:: Check pip
echo Checking pip...
%PYTHON_CMD% -m pip --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] pip is not available
    echo Try: %PYTHON_CMD% -m ensurepip --upgrade
    pause
    exit /b 1
)
echo [OK] pip is available
echo.

:: Install dependencies
echo Installing Python dependencies...
echo This may take a few minutes...
echo.

%PYTHON_CMD% -m pip install --user -r requirements.txt

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [OK] Dependencies installed successfully
echo.

:: Create directories
echo Creating necessary directories...
if not exist "uploads" mkdir uploads
if not exist "output\bills" mkdir output\bills
echo [OK] Directories created
echo.

:: Create desktop shortcut using PowerShell (proper .lnk file, no encoding issues)
echo Creating desktop shortcut...
set APP_PATH=%~dp0

:: Write a temp PowerShell script then execute it
set "PS_TEMP=%TEMP%\batchbill_sc.ps1"
> "%PS_TEMP%" echo $ws = New-Object -ComObject WScript.Shell
>> "%PS_TEMP%" echo $sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\BatchBill.lnk")
>> "%PS_TEMP%" echo $sc.TargetPath = "cmd.exe"
>> "%PS_TEMP%" echo $sc.Arguments = "/k run.bat"
>> "%PS_TEMP%" echo $sc.WorkingDirectory = "%APP_PATH%"
>> "%PS_TEMP%" echo $sc.Save()
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_TEMP%"
del "%PS_TEMP%" 2>nul

echo [OK] Desktop shortcut created: %USERPROFILE%\Desktop\BatchBill.lnk
echo.

echo ==================================
echo [OK] Installation Complete!
echo ==================================
echo.
echo To start the application:
echo   1. Double-click 'BatchBill.bat' on your Desktop
echo   2. Or run: run.bat
echo.
echo The webapp will open in your default browser at http://localhost:5003
echo.
pause
