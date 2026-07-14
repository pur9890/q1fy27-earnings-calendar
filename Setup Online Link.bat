@echo off
setlocal
cd /d "%~dp0"
title Publish Earnings Calendar Online

echo ================================================================
echo    PUBLISHING YOUR Q1 FY27 EARNINGS CALENDAR ONLINE
echo ================================================================
echo.
echo This will put your calendar on the internet with a link you can
echo open from any device. Just follow the prompts.
echo.
pause
echo.

REM --- Set your git identity only if it isn't set already ---
git config --global user.name  >nul 2>&1 || git config --global user.name  "Saarth"
git config --global user.email >nul 2>&1 || git config --global user.email "saarth62@gmail.com"

echo ----------------------------------------------------------------
echo  STEP 1 of 3 :  SIGN IN TO GITHUB
echo ----------------------------------------------------------------
echo  A web browser will open in a moment.
echo  Look here for a short CODE (like ABCD-1234), then type/paste it
echo  into the browser page and click the green buttons to approve.
echo.
pause
gh auth login --hostname github.com --git-protocol https --web
if errorlevel 1 goto fail
echo.
echo  Signed in successfully!
echo.

echo ----------------------------------------------------------------
echo  STEP 2 of 3 :  PACKING UP YOUR FILES
echo ----------------------------------------------------------------
git init -b main
git add .
git commit -m "Q1 FY27 earnings calendar + auto-deploy"
echo  Done.
echo.

echo ----------------------------------------------------------------
echo  STEP 3 of 3 :  UPLOADING AND GOING LIVE
echo ----------------------------------------------------------------
gh repo create q1fy27-earnings-calendar --public --source=. --push
if errorlevel 1 goto fail
echo.

for /f "delims=" %%u in ('gh api user --jq .login') do set GHUSER=%%u
echo ================================================================
echo    ALL DONE!
echo.
echo    Your calendar will be LIVE in about 1-2 minutes at:
echo.
echo        https://%GHUSER%.github.io/q1fy27-earnings-calendar/
echo.
echo    It refreshes itself every morning - no need to keep your PC on.
echo ================================================================
echo.
pause
exit /b 0

:fail
echo.
echo ----------------------------------------------------------------
echo  Something needs a look. Copy everything shown above and send it
echo  to Claude, and it will help you finish.
echo ----------------------------------------------------------------
echo.
pause
exit /b 1
