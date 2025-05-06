@echo off
echo Starting Playwright MCP server...
cd /d %~dp0

REM Configuration
set MCP_SERVER_DIR=mcp_server\playwright-custom-server
set MCP_SERVER_SCRIPT=server.js
set MCP_SERVER_PORT=11435

REM Activate virtual environment if not yet activated
if not defined VIRTUAL_ENV (
    echo Activating virtual environment...
    call venv\Scripts\activate
    if errorlevel 1 (
        echo [ERROR] Failed to activate virtual environment. Scripts might not work properly.
    ) else (
        echo Virtual environment activated.
    )
)

REM Check if Node.js is installed
where node > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH. Playwright server cannot start.
    echo Install Node.js from https://nodejs.org/
    echo.
    echo Attempting to use local Playwright as fallback...
    echo Make sure 'pip install playwright' and 'python -m playwright install chromium' have been run.
    pause
    exit /b 1
)

REM Check if the server script exists
if not exist "%MCP_SERVER_DIR%\%MCP_SERVER_SCRIPT%" (
    echo [ERROR] Playwright server script not found at %MCP_SERVER_DIR%\%MCP_SERVER_SCRIPT%
    echo.
    echo Attempting to use local Playwright as fallback...
    echo Make sure 'pip install playwright' and 'python -m playwright install chromium' have been run.
    pause
    exit /b 1
)

REM Check if the port is already in use
netstat -ano | findstr ":%MCP_SERVER_PORT% " | findstr "LISTENING" > nul
if errorlevel 0 (
    echo [INFO] Port %MCP_SERVER_PORT% is already in use. 
    echo A Playwright server might already be running.
    
    set /p continue="Continue anyway? (y/n): "
    if /i "%continue%" neq "y" (
        exit /b 0
    )
)

REM Start the server
echo Starting Playwright MCP Server on port %MCP_SERVER_PORT%...
echo Press Ctrl+C to stop the server.
cd %MCP_SERVER_DIR%
node %MCP_SERVER_SCRIPT%

REM This line is reached only if the server stops
echo Server stopped.
pause 