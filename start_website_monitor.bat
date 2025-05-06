@echo off
setlocal enabledelayedexpansion

echo ======================================
echo  AI Website Monitor - Startup Script
echo ======================================

REM --- Setup variables ---
set FLASK_APP=app:app
set REDIS_URL=redis://localhost:6379
set APP_PORT=5000
set APP_HOST=127.0.0.1

REM --- Ensure we're in the right directory ---
cd /d %~dp0

REM --- Activate virtual environment ---
echo Activating virtual environment...
call venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Virtual environment activation failed.
    echo Make sure your virtual environment is set up properly.
    pause
    exit /b 1
)

REM --- Check Redis connection ---
echo Testing Redis connection...
python check_redis.py
if errorlevel 1 (
    echo [ERROR] Redis connection failed.
    echo Make sure Redis is running at %REDIS_URL%
    echo Redis is required for background tasks and scheduled checks.
    pause
    exit /b 1
)
echo Redis connection successful.

REM --- Start RQ Worker ---
echo Starting RQ Worker in new window...
start "RQ Worker" cmd /k "call venv\Scripts\activate && python -m rq.cli worker default --url %REDIS_URL% --worker-class app.WindowsSimpleWorker --with-scheduler"

REM --- Wait for worker to start ---
echo Waiting for worker to initialize...
timeout /t 3 /nobreak > nul

REM --- Start Playwright server ---
echo Starting Playwright server...
start "Playwright Server" cmd /k "call venv\Scripts\activate && call start_playwright_server.bat"

REM --- Wait for server to start ---
echo Waiting for Playwright server to initialize...
timeout /t 3 /nobreak > nul

REM --- Start Flask app with Waitress ---
echo Starting Flask application with Waitress...
echo Server will be available at: http://%APP_HOST%:%APP_PORT%
echo Press Ctrl+C to stop the application.
echo (Remember to close the worker and server windows too)
echo ======================================

call venv\Scripts\activate && python -m waitress --host=%APP_HOST% --port=%APP_PORT% %FLASK_APP%

echo Application stopped.
pause 