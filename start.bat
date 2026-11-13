@echo off
title CoinDCX Algorithmic Trading Terminal
echo ===============================================================
echo Starting CoinDCX Institutional Quantitative Trading Terminal...
echo ===============================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if exist ".venv\Scripts\python.exe" (
    echo Using Virtual Environment Python...
    set PYTHON_EXE="%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    echo Using System Python...
    set PYTHON_EXE=python
)

set PYTHONPATH=%SCRIPT_DIR%
%PYTHON_EXE% run.py

pause
