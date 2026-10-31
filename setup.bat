@echo off
rem Creates the virtual environment and installs the dependencies.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
echo.
echo Done. Start the app with run.bat
goto :eof
:error
echo Setup failed.
exit /b 1
