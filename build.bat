@echo off
rem Builds dist\SoundscapePreviewer\SoundscapePreviewer.exe and runs its self test.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call setup.bat || goto :error
.venv\Scripts\python.exe -m pip install -r requirements-build.txt || goto :error
.venv\Scripts\python.exe -m PyInstaller --noconfirm SoundscapePreviewer.spec || goto :error
start "" /wait dist\SoundscapePreviewer\SoundscapePreviewer.exe --self-test selftest.log
type selftest.log
echo.
echo Built dist\SoundscapePreviewer\SoundscapePreviewer.exe
goto :eof
:error
echo Build failed.
exit /b 1
