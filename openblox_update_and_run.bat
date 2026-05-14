@echo off
setlocal
cd /d "%~dp0"
set "APP_DIR=%CD%"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

echo Upgrading pip...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto fail

echo Installing requirements...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo Updating OpenBlox and launching...
%PY% installer.py --terminal --path "%APP_DIR%" --launch
if errorlevel 1 goto fail

echo Done.
goto end

:fail
echo.
echo Update failed.

:end
pause
