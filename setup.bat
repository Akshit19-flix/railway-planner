@echo off
echo ============================================
echo  Indian Railways Plugin - First-time Setup
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Installing Python dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo [2/3] Installing Playwright browser (Chromium)...
python -m playwright install chromium
if errorlevel 1 (
    echo ERROR: Playwright browser install failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Creating Streamlit config (disables email prompt)...
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
(
  echo [browser]
  echo gatherUsageStats = false
) > "%USERPROFILE%\.streamlit\config.toml"

echo.
echo ============================================
echo  Setup complete! Run start.bat to launch.
echo ============================================
pause
