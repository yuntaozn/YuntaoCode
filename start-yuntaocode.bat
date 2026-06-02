@echo off
setlocal EnableExtensions

if /I "%~1"=="--help" goto usage
if /I "%~1"=="-h" goto usage

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot enter project directory: %ROOT_DIR%
    pause
    exit /b 1
)

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8765"
if "%WORKSPACE%"=="" set "WORKSPACE=%CD%"
if "%OPEN_BROWSER%"=="" set "OPEN_BROWSER=0"

if not "%~1"=="" set "WORKSPACE=%~1"
if not "%~2"=="" set "PORT=%~2"
if not "%~3"=="" set "HOST=%~3"

set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if "%PYTHON_CMD%"=="" (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python was not found.
    echo Install Python 3.10+ or add python.exe to PATH.
    pause
    popd >nul
    exit /b 1
)

%PYTHON_CMD% -c "import tornado" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Missing Python dependencies.
    echo Run this once:
    echo   %PYTHON_CMD% -m pip install -r requirements.txt
    pause
    popd >nul
    exit /b 1
)

set "URL=http://%HOST%:%PORT%"

echo YuntaoCode quick start
echo Project   : %CD%
echo Workspace : %WORKSPACE%
echo URL       : %URL%
echo Python    : %PYTHON_CMD%
echo.
echo Press Ctrl+C to stop the runtime.
if not "%OPEN_BROWSER%"=="1" echo Open the URL manually if you need the web panel.
echo.

if "%OPEN_BROWSER%"=="1" (
    start "" /b cmd /c "timeout /t 2 /nobreak >nul & explorer.exe %URL%"
)

%PYTHON_CMD% -m runtime.app --host "%HOST%" --port "%PORT%" --workspace "%WORKSPACE%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Runtime stopped with exit code %EXIT_CODE%.
pause
popd >nul
exit /b %EXIT_CODE%

:usage
echo Usage:
echo   start-yuntaocode.bat [workspace] [port] [host]
echo.
echo Defaults:
echo   workspace = project directory
echo   port      = 8765
echo   host      = 127.0.0.1
echo.
echo Environment overrides:
echo   set PORT=8766
echo   set HOST=127.0.0.1
echo   set WORKSPACE=D:\code
echo   set OPEN_BROWSER=1
exit /b 0
