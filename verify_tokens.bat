@echo off
REM ============================================================
REM Token Verification Batch Script
REM Checks if 'UPDATED' marker exists in token .txt files
REM ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo Token Update Verification Script
echo Date: %date% %time%
echo ============================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "TOTAL=0"
set "UPDATED=0"
set "NOT_UPDATED=0"

REM List of token files to check
set "FILES=Claude-Opus4.5.txt gemini-2.5-pro.txt gpt-5-mini.txt Grok-3.txt"

echo Checking token files for 'UPDATED' marker...
echo.

for %%f in (%FILES%) do (
    set /a TOTAL+=1
    set "FILE=%SCRIPT_DIR%%%f"
    
    if exist "!FILE!" (
        findstr /C:"UPDATED" "!FILE!" >nul 2>&1
        if !errorlevel! equ 0 (
            echo [OK] %%f - UPDATED marker found
            set /a UPDATED+=1
        ) else (
            echo [!!] %%f - UPDATED marker NOT found
            set /a NOT_UPDATED+=1
        )
    ) else (
        echo [XX] %%f - FILE NOT FOUND
        set /a NOT_UPDATED+=1
    )
)

echo.
echo ============================================================
echo Summary:
echo   Total files checked: %TOTAL%
echo   Updated: !UPDATED!
echo   Not updated: !NOT_UPDATED!
echo ============================================================

if !NOT_UPDATED! equ 0 (
    echo.
    echo [SUCCESS] All token files have been updated!
    echo.
    exit /b 0
) else (
    echo.
    echo [WARNING] Some token files need to be updated!
    echo Please update the tokens from the Bayer myGenAssist portal.
    echo.
    exit /b 1
)
