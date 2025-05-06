@echo off
echo ========================================================
echo     AI Website Monitor - Requirements Installer
echo ========================================================
echo.

REM --- Ensure script runs from its directory ---
cd /d %~dp0
echo Running from: %cd%
echo.

REM --- Check for virtual environment ---
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Is Python 3.8+ installed?
        pause
        exit /b 1
    )
)

REM --- Activate virtual environment ---
echo Activating virtual environment...
call venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM --- Upgrade pip ---
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [WARNING] Failed to upgrade pip, but continuing...
)

REM --- Install requirements ---
echo Installing/updating requirements from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

REM --- Install Playwright separately to ensure it's properly set up ---
echo Installing/updating Playwright...
pip install playwright
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright.
    pause
    exit /b 1
)

REM --- Install Playwright browsers (Chromium needed for screenshots) ---
echo Installing Playwright browsers (this may take a few minutes)...
python -m playwright install chromium
if errorlevel 1 (
    echo [WARNING] Failed to install Playwright browsers automatically.
    echo This might affect screenshot functionality.
    echo You can try running the command manually: python -m playwright install chromium
    pause
)

echo.
echo ========================================================
echo Installation complete!
echo Now you can run run_all.bat to start the application
echo ========================================================
echo.
pause 