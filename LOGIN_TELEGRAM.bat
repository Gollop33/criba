@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   CRIBA - LOGIN DE TELEGRAM (se hace UNA SOLA VEZ)
echo ============================================================
echo.
echo   Te va a pedir:
echo     1) Tu telefono con codigo de pais  (ej: +5511999999999)
echo     2) El codigo que te llega por Telegram
echo.
echo   Si tienes verificacion en dos pasos, tambien te pedira la contrasena.
echo.
echo   Al terminar te muestra una SESSION STRING larga.
echo   Copiala a GitHub - Settings - Secrets and variables - Actions:
echo        Nombre:  TELEGRAM_SESSION
echo.
echo ------------------------------------------------------------
echo.

python login_telegram.py
if errorlevel 1 (
    echo.
    echo   *** Algo fallo. Revisa el mensaje de arriba. ***
    echo   Si dice que falta telethon:   pip install telethon
)
echo.
echo ============================================================
echo   Cuando termines, pulsa una tecla para cerrar.
echo ============================================================
pause >nul
