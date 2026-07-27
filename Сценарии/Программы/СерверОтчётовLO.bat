@echo off
title SmartGrid Server Manager

set SCRIPT_DIR=%~dp0
set LO_PORT=2002
set WEB_PORT=8080
set LO_MODE=hidden

color 0F

echo ============================================
echo    SmartGrid Server Manager v2.1
echo ============================================
echo.

:menu
echo [1] Zapustit servera (SKRYTY rezhim LO)
echo [2] Zapustit servera (NORMALNY rezhim LO)
echo [3] Ostanovit vse servera
echo [4] Perepustit servera
echo [5] Proverit status serverov
echo [6] Vyhod
echo.
set /p choice="Vyberite deystvie (1-6): "

if "%choice%"=="1" goto start_hidden
if "%choice%"=="2" goto start_visible
if "%choice%"=="3" goto stop_all
if "%choice%"=="4" goto restart_all
if "%choice%"=="5" goto check_status
if "%choice%"=="6" goto exit
goto menu

:start_hidden
set LO_MODE=hidden
goto start_all

:start_visible
set LO_MODE=visible
goto start_all

:start_all
echo.
echo ============================================
if "%LO_MODE%"=="hidden" (
    echo    ZAPUSK SERVEROV (SKRYTY rezhim)
) else (
    echo    ZAPUSK SERVEROV (NORMALNY rezhim)
)
echo ============================================
echo.

call :stop_processes

:: Zapusk LibreOffice
echo Zapusk LibreOffice...
if "%LO_MODE%"=="hidden" (
    start "" "C:\Program Files\LibreOffice\program\soffice.exe" --accept="socket,host=localhost,port=%LO_PORT%;urp;" --norestore --nologo --nodefault --invisible --headless
    echo   [OK] LibreOffice zapushen (port %LO_PORT%, SKRYTY rezhim)
) else (
    start "" "C:\Program Files\LibreOffice\program\soffice.exe" --accept="socket,host=localhost,port=%LO_PORT%;urp;" --norestore --nologo --nodefault
    echo   [OK] LibreOffice zapushen (port %LO_PORT%, NORMALNY rezhim)
)

if %errorlevel%==0 (
    echo   [OK] LibreOffice zapushen
) else (
    echo   [ERROR] Oshibka zapuska LibreOffice
)

:: Zapusk web-servera
echo Zapusk web-servera...
start /B "" "C:\Program Files\LibreOffice\program\python.exe" "%SCRIPT_DIR%web_server.py" %WEB_PORT%
if %errorlevel%==0 (
    echo   [OK] Web-server zapushen (port %WEB_PORT%)
) else (
    echo   [ERROR] Oshibka zapuska web-servera
)

echo.
echo Proverka rabotosposobnosti serverov...
echo.

call :check_servers

echo.
echo ============================================
echo    ZAPUSK ZAVERSHEN
echo ============================================
echo.
goto menu

:stop_all
echo.
echo ============================================
echo    OSTANOVKA SERVEROV
echo ============================================
echo.

call :stop_processes

echo.
echo ============================================
echo    OSTANOVKA ZAVERSHENA
echo ============================================
echo.
goto menu

:restart_all
echo.
echo ============================================
echo    PEREZAPUSK SERVEROV
echo ============================================
echo.

call :stop_processes
timeout /t 2 /nobreak > nul
goto menu

:check_status
echo.
echo ============================================
echo    STATUS SERVEROV
echo ============================================
echo.

call :check_servers

echo.
goto menu

:stop_processes
echo Ostanovka web-servera...
taskkill /F /IM python.exe 2>nul
if %errorlevel%==0 (
    echo   [OK] Web-server ostanovlen
) else (
    echo   [WARN] Web-server ne byl zapushen
)

echo Ostanovka LibreOffice...
taskkill /F /IM soffice.exe 2>nul
taskkill /F /IM soffice.bin 2>nul
if %errorlevel%==0 (
    echo   [OK] LibreOffice ostanovlen
) else (
    echo   [WARN] LibreOffice ne byl zapushen
)
exit /b

:check_servers
set LO_OK=0
set WEB_OK=0

echo Proverka LibreOffice...
timeout /t 2 /nobreak > nul

tasklist /FI "IMAGENAME eq soffice.exe" 2>NUL | find /I "soffice.exe" >NUL
if %errorlevel%==0 (
    echo   [OK] LibreOffice: PROCESS ZAPUSHEN
    set LO_OK=1
) else (
    echo   [X] LibreOffice: PROCESS NE NAJDEN
)

echo Proverka web-servera...
timeout /t 1 /nobreak > nul

tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe" >NUL
if %errorlevel%==0 (
    echo   [OK] Web-server: PROCESS ZAPUSHEN
    set WEB_OK=1
) else (
    echo   [X] Web-server: PROCESS NE NAJDEN
)

:: Proverka cherez port (esli est curl)
where curl >nul 2>nul
if %errorlevel%==0 (
    curl --connect-timeout 2 http://localhost:%WEB_PORT%/ping 2>nul | find "OK" >nul
    if %errorlevel%==0 (
        echo   [OK] Web-server: OTVECHAET (ping OK)
    ) else (
        if "%WEB_OK%"=="1" (
            echo   [WARN] Web-server: PROCESS EST, NO NE OTVECHAET
        )
    )
)

echo.
if "%LO_OK%"=="1" (
    if "%WEB_OK%"=="1" (
        echo [OK] VSE SERVERY RABOTAYUT
    ) else (
        echo [WARN] LIBREOFFICE RABOTAET, NO WEB-SERVER NE ZAPUSHEN
    )
) else (
    if "%WEB_OK%"=="1" (
        echo [WARN] WEB-SERVER RABOTAET, NO LIBREOFFICE NE ZAPUSHEN
    ) else (
        echo [ERROR] NI ODIN SERVER NE ZAPUSHEN
    )
)
exit /b

:exit
echo.
echo Vyhod...
exit /b 0