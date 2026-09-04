@echo off
title FinScope — Personal Finance Analytics
echo ===================================================
echo   FinScope: Personal Finance Analytics App
echo ===================================================
echo Starting FinScope...

python app\main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FinScope stopped with error code %ERRORLEVEL%.
    pause
)
