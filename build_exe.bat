@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Окружение не найдено. Сначала запустите install_windows.bat.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider --basetemp "work\build-tests-%RANDOM%"
if errorlevel 1 (
    echo Тесты не пройдены. Сборка отменена.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" tools\prepare_release.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --paths . --name MagicLabManager --icon "app\resources\icons\magiclab.ico" --add-data "app\resources;app\resources" launcher.py
if errorlevel 1 (
    echo Сборка PyInstaller завершилась с ошибкой.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" tools\prepare_release.py --finalize
if errorlevel 1 exit /b 1

echo Сборка завершена: dist\MagicLabManager\MagicLabManager.exe
if /I not "%~1"=="--no-pause" pause
