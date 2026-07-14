@echo off
REM Refreshes the Q1 FY27 earnings calendar from MoneyControl and opens it.
cd /d "%~dp0"
python update_calendar.py
if %errorlevel%==0 (
    start "" "earnings_calendar.html"
) else (
    echo.
    echo Update failed - check your internet connection and try again.
    pause
)
