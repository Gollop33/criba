@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title CRIBA - Actualizar ofertas de Amazon
color 0A

echo.
echo ======================================================================
echo    CRIBA - ACTUALIZAR LAS OFERTAS DE AMAZON
echo ======================================================================
echo.
echo   POR QUE ESTE ARCHIVO:
echo   Amazon bloquea los servidores de GitHub, asi que el bot cosecha
echo   0 ofertas de Amazon en la nube (por eso el grupo sale casi todo de
echo   Mercado Livre). Desde tu conexion SI funciona: la misma cosecha trae
echo   unas 300 ofertas.
echo.
echo   Este archivo hace eso y sube el resultado al repositorio, que es de
echo   donde el bot lo lee.
echo.
echo   Tarda 2-3 minutos. Puedes cerrar la ventana cuando termine.
echo.
echo   CONSEJO: programa este archivo en el Programador de tareas de
echo   Windows para que se ejecute 1 vez al dia y no tengas que pensarlo.
echo.
echo   Pulsa una tecla para empezar...
pause >nul
cls

python amazon_desde_pc.py

echo.
echo ======================================================================
echo    FIN
echo ======================================================================
echo.
echo   Si arriba pone "[OK] Subido", ya esta hecho.
echo   El bot usara estas ofertas en la proxima ejecucion.
echo.
pause
