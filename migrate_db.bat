@echo off
setlocal enabledelayedexpansion

echo ======================================
echo  Database Migration Helper Script
echo ======================================

REM --- Activate virtual environment ---
echo Activating virtual environment...
call venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Virtual environment activation failed.
    echo Make sure your virtual environment is set up properly.
    pause
    exit /b 1
)

echo Setting up Flask Migration...
set FLASK_APP=app:app

echo Running initial migrations...
python -m flask db init
if errorlevel 1 (
    echo [WARNING] Migration initialization failed - this is OK if migrations already exist.
) else (
    echo Migration folder initialized.
)

echo Creating new migration version...
python -m flask db migrate -m "automatic_migration"
if errorlevel 1 (
    echo [ERROR] Migration creation failed.
    pause
    exit /b 1
)

echo Applying migrations to database...
python -m flask db upgrade
if errorlevel 1 (
    echo [ERROR] Migration upgrade failed.
    pause
    exit /b 1
)

echo Applying additional schema updates...
python update_schema.py
if errorlevel 1 (
    echo [WARNING] Schema update script failed.
    pause
) else (
    echo Schema updates applied successfully.
)

echo Database migration completed.
pause
exit /b 0 