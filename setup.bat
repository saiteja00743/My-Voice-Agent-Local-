@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AI Voice Clone - Setup

cd /d "%~dp0"

:: ============================================================
:: CRASH TRAP WRAPPER — window NEVER closes silently
:: ============================================================
if "%1"=="__INNER__" goto :MAIN
cmd /d /c ""%~f0" __INNER__"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  !! Setup exited with error code: %ERRORLEVEL%
    echo     Read the messages above for details.
    echo.
)
echo  Press any key to close this window ...
pause >nul
exit /b

:: ============================================================
:MAIN
:: ============================================================

echo.
echo  ================================================
echo    AI Voice Clone  -  Environment Setup
echo  ================================================
echo.
echo  Folder: %CD%
echo.

:: ============================================================
:: STEP 1 - Check Python + Version Warning
:: ============================================================
echo [STEP 1/6]  Checking Python installation ...
echo.

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto :NO_PYTHON

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Found Python %PY_VER%

for /f "tokens=1,2,3 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
    set PY_PATCH=%%c
)

if %PY_MAJOR% LSS 3 goto :NO_PYTHON_VERSION
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 9 goto :NO_PYTHON_VERSION

:: Warn if Python 3.12+ (Coqui TTS has known issues)
if %PY_MAJOR% EQU 3 if %PY_MINOR% GEQ 12 (
    echo.
    echo  !! COMPATIBILITY WARNING !!
    echo     You are using Python %PY_VER%.
    echo     Coqui TTS officially supports Python 3.9 - 3.11 only.
    echo     With Python 3.12 we will try workarounds, but if they
    echo     fail you will need to install Python 3.11.
    echo.
    echo     Python 3.11 download: https://www.python.org/downloads/release/python-3119/
    echo.
    set PY312=1
    set /p CONT="  Continue anyway with Python %PY_VER%? (y/n): "
    if /i "!CONT!" NEQ "y" (
        echo  Exiting. Please install Python 3.11 and re-run setup.bat.
        goto :FAIL
    )
    echo.
) else (
    set PY312=0
)

echo  OK - Python %PY_VER%
echo.
goto :STEP2

:NO_PYTHON
echo  ERROR: Python not found in PATH.
echo  Install from: https://www.python.org/downloads/release/python-3119/
echo  Tick "Add Python to PATH" during install.
goto :FAIL

:NO_PYTHON_VERSION
echo  ERROR: Python 3.9+ required. Found: %PY_VER%
goto :FAIL

:: ============================================================
:STEP2
:: STEP 2 - Create virtual environment
:: ============================================================
echo [STEP 2/6]  Setting up virtual environment ...
echo.

set VENV_DIR=venv

if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo  Venv already exists - skipping creation.
    echo.
    goto :STEP3
)

python -m venv %VENV_DIR%
if %ERRORLEVEL% NEQ 0 goto :VENV_FAIL
echo  Created: %CD%\%VENV_DIR%\
echo.
goto :STEP3

:VENV_FAIL
echo  ERROR: Failed to create virtual environment.
goto :FAIL

:: ============================================================
:STEP3
:: STEP 3 - Activate venv
:: ============================================================
echo [STEP 3/6]  Activating virtual environment ...
echo.

call "%VENV_DIR%\Scripts\activate.bat"
if %ERRORLEVEL% NEQ 0 goto :ACTIVATE_FAIL
echo  Activated: %VENV_DIR%
echo.
goto :STEP4

:ACTIVATE_FAIL
echo  ERROR: Could not activate venv.
goto :FAIL

:: ============================================================
:STEP4
:: STEP 4 - Upgrade pip + install build tools
:: ============================================================
echo [STEP 4/6]  Upgrading pip and build tools ...
echo.

python -m pip install --upgrade pip setuptools wheel
echo.
goto :STEP5

:: ============================================================
:STEP5
:: STEP 5 - Install PyTorch
:: ============================================================
echo [STEP 5/6]  Installing PyTorch ...
echo.

nvidia-smi >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :INSTALL_CUDA_TORCH
goto :INSTALL_CPU_TORCH

:INSTALL_CUDA_TORCH
echo  NVIDIA GPU detected!
echo  Downloading PyTorch CUDA 11.8 (approx. 2.5 GB) ...
echo  Do NOT close this window.
echo.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
if %ERRORLEVEL% EQU 0 goto :TORCH_OK_CUDA
echo.
echo  CUDA PyTorch failed. Trying CPU fallback ...
echo.
goto :INSTALL_CPU_TORCH

:INSTALL_CPU_TORCH
echo  Installing CPU-only PyTorch (~200 MB) ...
pip install torch torchaudio
if %ERRORLEVEL% EQU 0 goto :TORCH_OK_CPU
goto :TORCH_FAIL

:TORCH_OK_CUDA
echo.
echo  PyTorch + CUDA 11.8 installed successfully.
echo.
goto :STEP6

:TORCH_OK_CPU
echo.
echo  CPU PyTorch installed successfully.
echo  NOTE: Generation will be slow without a GPU.
echo.
goto :STEP6

:TORCH_FAIL
echo  ERROR: PyTorch installation failed.
echo  Check your internet connection and disk space (need 4+ GB free).
goto :FAIL

:: ============================================================
:STEP6
:: STEP 6 - Install Coqui TTS (with Python 3.12 workarounds)
:: ============================================================
echo [STEP 6/6]  Installing application dependencies ...
echo.

:: --- Pre-install binary wheels to avoid C++ compiler requirement ---
echo  -- Pre-installing binary dependencies (numpy, scipy, etc.) ...
echo     This avoids needing Microsoft Visual C++ Build Tools.
echo.
pip install --only-binary :all: numpy scipy
if %ERRORLEVEL% NEQ 0 (
    echo  WARNING: Binary-only numpy/scipy failed, trying normal install ...
    pip install numpy scipy
)
pip install --only-binary :all: Cython
if %ERRORLEVEL% NEQ 0 (
    pip install Cython
)
echo.

:: --- TTS Installation (multiple strategies) ---
echo  -- Installing Coqui TTS (XTTS-v2 voice engine) ...
echo     Strategy 1: Standard install ...
echo.

pip install "TTS>=0.22.0"
if %ERRORLEVEL% EQU 0 goto :TTS_INSTALLED

echo.
echo     Strategy 1 failed. Trying Strategy 2 (ignore Python version check) ...
echo.
pip install TTS --ignore-requires-python
if %ERRORLEVEL% EQU 0 goto :TTS_INSTALLED

echo.
echo     Strategy 2 failed. Trying Strategy 3 (install without strict deps) ...
echo.
pip install TTS --ignore-requires-python --no-deps
if %ERRORLEVEL% EQU 0 (
    echo  Installing TTS dependencies manually ...
    pip install numpy scipy librosa scikit-learn numba
    pip install pyyaml fsspec aiofiles packaging
    pip install gruut coqpit
    pip install trainer>=0.0.36
    pip install "transformers>=4.35.0"
    pip install "inflect>=5.3.0"
    pip install "anyascii>=0.3.0"
    pip install "jinja2>=3.0.0"
    pip install "tqdm>=4.64.0"
    goto :TTS_INSTALLED
)

echo.
echo     Strategy 3 failed. Trying Strategy 4 (install from GitHub) ...
echo.
pip install git+https://github.com/idiap/coqui-ai-TTS.git --ignore-requires-python
if %ERRORLEVEL% EQU 0 goto :TTS_INSTALLED

echo.
echo  ERROR: All TTS installation strategies failed.
echo.
echo  YOU ARE USING PYTHON %PY_VER%
echo  Coqui TTS requires Python 3.9 to 3.11.
echo.
echo  SOLUTION: Install Python 3.11.9:
echo    https://www.python.org/downloads/release/python-3119/
echo.
echo  Steps:
echo    1. Download Python 3.11.9 from the link above
echo    2. Install it (tick "Add to PATH")
echo    3. Delete the "venv" folder in this project
echo    4. Run setup.bat again using Python 3.11
echo.
echo  TIP: You can have multiple Python versions installed.
echo  To force a specific version, open CMD and run:
echo    py -3.11 -m venv venv
echo    then re-run setup.bat
goto :FAIL

:TTS_INSTALLED
echo.
echo  Coqui TTS installed successfully.
echo.

:: --- Other dependencies ---
echo  -- Installing GUI (PySide6) ...
pip install "PySide6>=6.6.0"

echo.
echo  -- Installing audio libraries ...
pip install sounddevice soundfile scipy

echo.
echo  -- Installing pygame (audio fallback) ...
pip install pygame

echo.
echo  -- Installing librosa (audio processing) ...
pip install librosa

echo.
echo  -- Installing utilities ...
pip install colorlog colorama

echo.
echo  -- Installing Hugging Face hub ...
pip install "transformers>=4.35.0" "huggingface-hub>=0.19.0"

echo.
goto :CREATE_LAUNCHER

:: ============================================================
:CREATE_LAUNCHER
:: ============================================================
echo  Creating launch.bat ...
(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title AI Voice Clone
    echo cd /d "%%~dp0"
    echo call venv\Scripts\activate.bat
    echo echo.
    echo echo  Starting AI Voice Clone ...
    echo echo  First run downloads the XTTS-v2 model (~1.8 GB). Please wait.
    echo echo.
    echo python main.py
    echo if %%ERRORLEVEL%% NEQ 0 ^(
    echo     echo.
    echo     echo  Error occurred. Check logs\app.log for details.
    echo     pause
    echo ^)
) > launch.bat
echo  Created: launch.bat

:: ============================================================
:: SUCCESS
:: ============================================================
echo.
echo  ================================================
echo    SETUP COMPLETE!
echo  ================================================
echo.
echo  All dependencies installed successfully.
echo.
echo  FIRST RUN NOTE:
echo    XTTS-v2 model (~1.8 GB) downloads automatically on
echo    first launch (internet needed once only).
echo    After that the app works fully OFFLINE.
echo.
echo  TO LAUNCH:
echo    Double-click launch.bat
echo    -- OR --
echo    venv\Scripts\activate  then  python main.py
echo.

set /p LAUNCH="  Launch the app now? (y/n): "
if /i "!LAUNCH!"=="y" (
    echo.
    echo  Launching AI Voice Clone ...
    echo.
    python main.py
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo  App exited with an error. Check logs\app.log for details.
    )
)

echo.
echo  Press any key to close ...
pause >nul
exit /b 0

:: ============================================================
:FAIL
:: ============================================================
echo.
echo  ================================================
echo    SETUP FAILED
echo  ================================================
echo.
echo  Read the error above, fix it, then re-run setup.bat.
echo  See README.md for help.
echo.
echo  Press any key to close ...
pause >nul
exit /b 1
