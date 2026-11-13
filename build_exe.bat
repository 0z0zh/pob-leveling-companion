@echo off
rem Builds dist\PoBLevelingCompanion.exe locally (GitHub Actions does the same in .github\workflows\build.yml)
cd /d "%~dp0"
if not exist .venv python -m venv .venv
rem same pinned versions as the CI build
.venv\Scripts\python -m pip install -q -r requirements-build.txt
rem product name / version metadata for the exe, from the VERSION file
.venv\Scripts\python tools\make_version_info.py || exit /b 1
rem "python -m PyInstaller" (not pyinstaller.exe) keeps working after the folder is moved
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name PoBLevelingCompanion --specpath build ^
  --version-file "%~dp0build\version_info.txt" ^
  --add-data "%~dp0static;static" ^
  --add-data "%~dp0data;data" ^
  --add-data "%~dp0VERSION;." ^
  app.py
echo.
echo Done: dist\PoBLevelingCompanion.exe
pause
