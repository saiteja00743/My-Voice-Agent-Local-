@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AI Voice Clone - TTS Fix

cd /d "%~dp0"

echo.
echo  ================================================
echo    TTS Quick Fix  (reuses your existing venv)
echo  ================================================
echo.

:: Activate existing venv
if not exist "venv\Scripts\activate.bat" (
    echo  ERROR: venv not found. Run setup.bat first.
    pause
    exit /b 1
)

echo  Activating existing venv ...
call venv\Scripts\activate.bat
echo.

:: Step 1 - Force pre-built binary wheels for numpy/scipy/Cython
echo  [1/3] Installing numpy, scipy, Cython as pre-built binaries ...
echo        (No C++ compiler needed - downloading wheels only)
echo.
pip install --only-binary :all: numpy scipy
if %ERRORLEVEL% NEQ 0 (
    echo  Retrying numpy/scipy without binary restriction ...
    pip install numpy scipy --upgrade
)
pip install --only-binary :all: Cython
if %ERRORLEVEL% NEQ 0 (
    pip install Cython --upgrade
)
echo.

:: Step 2 - Try TTS install (strategies in order)
echo  [2/3] Installing Coqui TTS ...
echo.

echo     Strategy 1: Standard install ...
pip install "TTS>=0.22.0"
if %ERRORLEVEL% EQU 0 goto :TTS_OK

echo.
echo     Strategy 2: Ignore Python version check ...
pip install TTS --ignore-requires-python
if %ERRORLEVEL% EQU 0 goto :TTS_OK

echo.
echo     Strategy 3: From GitHub (coqui-ai fork) ...
pip install git+https://github.com/idiap/coqui-ai-TTS.git --ignore-requires-python
if %ERRORLEVEL% EQU 0 goto :TTS_OK

echo.
echo  ERROR: TTS installation still failed.
echo  Please install Visual C++ Build Tools from:
echo    https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo  Select "Desktop development with C++" then re-run this fix script.
echo.
pause
exit /b 1

:TTS_OK
echo.
echo  [3/3] Coqui TTS installed successfully!
echo.
echo  ================================================
echo    FIX COMPLETE - You can now run launch.bat
echo  ================================================
echo.
pause
exit /b 0
