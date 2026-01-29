@echo off
title PyTalk - Video Conferencing
color 0A

:menu
cls
echo.
echo  ====================================================
echo  ^|                                                  ^|
echo  ^|   ____        _____     _ _                      ^|
echo  ^|  ^|  _ \ _   _^|_   _^|_ _^| ^| ^| __                 ^|
echo  ^|  ^| ^|_) ^| ^| ^| ^| ^| ^| / _` ^| ^| ^|/ /                 ^|
echo  ^|  ^|  __/^| ^|_^| ^| ^| ^|^| (_^| ^| ^|   ^<                  ^|
echo  ^|  ^|_^|    \__, ^| ^|_^| \__,_^|_^|_^|\_\                 ^|
echo  ^|         ^|___/                                    ^|
echo  ^|                                                  ^|
echo  ^|          Video Conferencing Platform            ^|
echo  ^|                                                  ^|
echo  ====================================================
echo.
echo    [1] Start Server
echo    [2] First Time Setup
echo    [3] Run Migrations
echo    [4] Create Admin User
echo    [5] Open in Browser
echo    [6] View Logs
echo    [7] Exit
echo.
echo  ====================================================
echo.

set /p choice=   Select an option (1-7):

if "%choice%"=="1" goto start_server
if "%choice%"=="2" goto setup
if "%choice%"=="3" goto migrate
if "%choice%"=="4" goto create_admin
if "%choice%"=="5" goto open_browser
if "%choice%"=="6" goto view_logs
if "%choice%"=="7" goto exit

echo Invalid option, please try again...
timeout /t 2 >nul
goto menu

:start_server
cls
echo.
echo  Starting PyTalk Server...
echo  ====================================================
echo.
cd /d "%~dp0backend"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if not exist "logs" mkdir logs
echo  Server running at: http://127.0.0.1:3000
echo  Press Ctrl+C to stop
echo.
python manage.py runserver 0.0.0.0:3000
pause
goto menu

:setup
cls
call "%~dp0setup.bat"
goto menu

:migrate
cls
echo.
echo  Running Migrations...
echo  ====================================================
echo.
cd /d "%~dp0backend"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
python manage.py makemigrations
python manage.py migrate
echo.
echo  Migrations complete!
pause
goto menu

:create_admin
cls
echo.
echo  Create Admin User
echo  ====================================================
echo.
cd /d "%~dp0backend"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
python manage.py createsuperuser
pause
goto menu

:open_browser
start http://127.0.0.1:3000
goto menu

:view_logs
cls
echo.
echo  Recent Security Logs
echo  ====================================================
echo.
cd /d "%~dp0backend"
if exist "logs\security.log" (
    type logs\security.log | more
) else (
    echo  No logs found yet.
)
echo.
pause
goto menu

:exit
echo.
echo  Goodbye!
timeout /t 1 >nul
exit /b 0
