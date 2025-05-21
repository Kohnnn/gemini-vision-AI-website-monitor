@echo off
setlocal enabledelayedexpansion

echo ==================================
echo  Redis Installer for Windows
echo ==================================
echo.

set REDIS_DIR=%~dp0redis
set REDIS_URL=https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.zip
set REDIS_ZIP=%TEMP%\redis.zip

echo Checking if Redis is already installed...
if exist "%REDIS_DIR%\redis-server.exe" (
    echo Redis is already installed.
    goto :start_redis
)

echo Installing Redis...

if not exist "%REDIS_DIR%" (
    mkdir "%REDIS_DIR%"
)

echo Downloading Redis from GitHub...
powershell -Command "Invoke-WebRequest '%REDIS_URL%' -OutFile '%REDIS_ZIP%'"

echo Extracting Redis files...
powershell -Command "Expand-Archive -Path '%REDIS_ZIP%' -DestinationPath '%TEMP%\redis-extract' -Force"
xcopy /E /Y "%TEMP%\redis-extract\*" "%REDIS_DIR%\"

echo Cleaning up temporary files...
del "%REDIS_ZIP%"
rmdir /S /Q "%TEMP%\redis-extract"

:start_redis
echo Starting Redis server...
start "Redis Server" /b cmd /c "%REDIS_DIR%\redis-server.exe"

echo Testing Redis connection...
"%REDIS_DIR%\redis-cli.exe" ping
if %errorlevel% equ 0 (
    echo Redis is running successfully!
) else (
    echo Failed to connect to Redis. Please check your firewall settings.
    echo You may need to run this script as administrator.
)

echo.
echo ==================================
echo Redis has been installed and started.
echo To use Redis in your application, connect to:
echo localhost:6379
echo ==================================
echo.
echo Press any key to close this window...
pause > nul 