@echo off
title PyTalk - Setup
color 0B

echo ========================================
echo        PyTalk - Initial Setup
echo ========================================
echo.

cd /d "%~dp0backend"

:: Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [*] Python found:
python --version
echo.

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

:: Activate virtual environment
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

:: Upgrade pip
echo [*] Upgrading pip...
python -m pip install --upgrade pip

:: Install dependencies
echo [*] Installing dependencies...
pip install -r requirements.txt

:: Create logs directory
if not exist "logs" (
    echo [*] Creating logs directory...
    mkdir logs
)

:: Create .env file if it doesn't exist
if not exist ".env" (
    echo [*] Creating .env file from template...
    copy .env.example .env
    echo [!] Please edit .env file with your settings
)

:: Run migrations
echo [*] Setting up database...
python manage.py migrate

:: Create superuser prompt
echo.
echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo Would you like to create an admin user? (Y/N)
set /p create_admin=

if /i "%create_admin%"=="Y" (
    echo.
    python manage.py createsuperuser
)

echo.
echo ========================================
echo    Setup finished successfully!
echo.
echo    Run 'start.bat' to start the server
echo    Access the app at http://127.0.0.1:3000
echo ========================================
echo.

pause
