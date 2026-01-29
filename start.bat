@echo off
title PyTalk - Video Conferencing App
color 0A

echo ========================================
echo        PyTalk - Starting Server
echo ========================================
echo.

cd /d "%~dp0backend"

:: Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [!] Virtual environment not found, using system Python
)

:: Install/update dependencies in venv
echo [*] Installing dependencies...
pip install -r requirements.txt -q

:: Create logs directory if it doesn't exist
if not exist "logs" (
    echo [*] Creating logs directory...
    mkdir logs
)

:: Run migrations
echo [*] Applying database migrations...
python manage.py migrate --run-syncdb

echo.
echo ========================================
echo    Server starting on port 3000
echo    http://127.0.0.1:3000
echo ========================================
echo.
echo Press Ctrl+C to stop the server
echo.

:: Start the server
python manage.py runserver 0.0.0.0:3000

pause
