@echo off
cd /d C:\andreosh\CPP\Wind\_SmartGrid\githab

echo ========================================
echo    RusFoxQt6 Repository Update
echo ========================================
echo.

git add .

echo Files to be committed:
git status --short
echo.

for /f "tokens=1-3 delims=.: " %%a in ('echo %time%') do set "mytime=%%a:%%b:%%c"
git commit -m "Update from %date% %mytime%"

git push origin master

echo.
echo ========================================
echo    Done!
echo ========================================
pause
