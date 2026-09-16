@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Окружение не найдено. Сначала запустите install_windows.bat.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m app.main
if errorlevel 1 (
    echo Программа завершилась с ошибкой. Проверьте data\magiclab.log.
    pause
)
