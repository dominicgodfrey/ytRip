@echo off
rem One-time setup: creates .venv and installs dependencies.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv python -m venv .venv || (pause & exit /b 1)
.venv\Scripts\python -m pip install --disable-pip-version-check -U -r requirements.txt || (pause & exit /b 1)
if not exist "ffmpeg-*" where ffmpeg >nul 2>nul || echo WARNING: ffmpeg not found. Put an ffmpeg build folder here or add ffmpeg to PATH.
where node >nul 2>nul || where deno >nul 2>nul || echo WARNING: no JavaScript runtime found. Install Node.js or Deno, YouTube downloads need one.
echo.
echo Setup complete. Double-click ytRip.bat to start.
pause
