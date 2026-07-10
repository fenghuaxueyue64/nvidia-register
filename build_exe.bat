@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --clean --noconfirm nvidia_register_ui.spec
if errorlevel 1 exit /b 1

echo.
echo Built: dist\NVIDIARegister.exe
