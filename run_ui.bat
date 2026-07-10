@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  NVIDIA Register Control - Desktop UI
echo ========================================
echo.

REM --- Activate conda nvidia env ---
set "CONDA_BASE="
for %%D in (miniconda3 anaconda3 Miniconda3 Anaconda3) do (
    for %%R in (%USERPROFILE% C:\ProgramData C:\) do (
        if exist "%%R\%%D\Scripts\activate.bat" (
            set "CONDA_BASE=%%R\%%D"
            goto :conda_found
        )
    )
)

:conda_found
if defined CONDA_BASE (
    echo [OK] conda: !CONDA_BASE!
    call "!CONDA_BASE!\Scripts\activate.bat" nvidia >NUL 2>NUL
    if !ERRORLEVEL! neq 0 (
        echo [FAIL] conda activate nvidia failed
        pause
        exit /b 1
    )
    echo [OK] env activated: nvidia
) else (
    echo [WARN] conda not found, falling back to system Python
)

REM --- Check UI dependencies ---
python -c "import customtkinter" >NUL 2>NUL
if !ERRORLEVEL! neq 0 (
    echo Installing customtkinter Pillow...
    pip install customtkinter Pillow -q
)

REM --- Check Playwright browsers ---
python -c "import playwright" >NUL 2>NUL
if !ERRORLEVEL! neq 0 (
    echo [WARN] Playwright not installed.
) else (
    python -m playwright install chromium
)

REM --- Launch ---
echo.
echo Launching UI...
python app.py
pause
