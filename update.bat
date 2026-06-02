@echo off
echo ========================================
echo Обновление репозитория RusFoxQt6
echo ========================================
echo.

REM Добавляем все изменения
git add .

REM Показываем, что будет отправлено
echo Будут отправлены следующие изменения:
git status --short
echo.

REM Создаём коммит с датой и временем
for /f "tokens=1-3 delims=.: " %%a in ('echo %time%') do set "mytime=%%a:%%b:%%c"
set "commitmsg=Обновление от %date% %mytime%"

git commit -m "%commitmsg%"

REM Отправляем на GitHub
git push origin master

echo.
echo ========================================
echo Готово! Репозиторий обновлён.
echo ========================================
pause
