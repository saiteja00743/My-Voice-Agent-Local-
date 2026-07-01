@echo off
chcp 65001 >nul 2>&1
title AI Voice Clone
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo.
echo  Starting AI Voice Clone ...
echo  First run downloads the XTTS-v2 model (~1.8 GB). Please wait.
echo.
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  Error occurred. Check logs\app.log for details.
    pause
)
