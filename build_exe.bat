@echo off
rem Builds dist\PoBLevelingCompanion.exe locally (GitHub Actions does the same in .github\workflows\build.yml)
cd /d "%~dp0"
if not exist .venv python -m venv .venv
rem same pinned versions as the CI build
.venv\Scripts\python -m pip install -q -r requirements-build.txt
rem "python -m PyInstaller" (not pyinstaller.exe) keeps working after the folder is moved
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name PoBLevelingCompanion --specpath build ^
  --add-data "%~dp0static;static" ^
  --add-data "%~dp0data;data" ^
  app.py
echo.
echo Done: dist\PoBLevelingCompanion.exe
pause
