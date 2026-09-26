@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   CRIBA - LOGIN DE TELEGRAM  (se hace UNA SOLA VEZ)
echo ============================================================
echo.
echo   Si la ventana se queda congelada y no te deja escribir
echo   ni pegar: es el "Modo de edicion rapida" de Windows.
echo   Pulsa la tecla  ESC  y se desbloquea sola.
echo.
echo   Este script NO necesita que escribas nada aqui:
echo   todo se hace desde el archivo  .env  con el Bloc de notas.
echo.
echo ------------------------------------------------------------
echo.

python login_telegram.py

echo.
echo ============================================================
echo   Lee el mensaje de arriba: te dice exactamente que hacer.
echo   Pulsa una tecla para cerrar.
echo ============================================================
pause >nul
