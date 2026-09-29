@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title CRIBA - Conectar la API de Mercado Livre
color 0A

echo.
echo ======================================================================
echo    CRIBA - CONECTAR LA API DE MERCADO LIVRE
echo ======================================================================
echo.
echo   Este asistente hace los 3 pasos que faltan. Solo tienes que
echo   pegar DOS datos cuando te los pida.
echo.
echo   Pulsa una tecla para empezar...
pause >nul

REM ---------- Comprobar Python ----------
where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [ERROR] No se encuentra Python en este equipo.
  echo   Cierra esta ventana y avisa.
  echo.
  pause
  exit /b 1
)

REM ---------- Estado actual ----------
cls
echo.
echo ======================================================================
echo    ESTADO ACTUAL
echo ======================================================================
echo.
python obtener_token_ml.py --estado
echo.
echo ----------------------------------------------------------------------
echo   Pulsa una tecla para continuar...
pause >nul

REM ======================================================================
REM   PASO 1: el Client Secret
REM ======================================================================
cls
echo.
echo ======================================================================
echo    PASO 1 de 3  -  CLIENT SECRET
echo ======================================================================
echo.
echo   Ve a la pagina de tu aplicacion en el devcenter de Mercado Livre.
echo.
echo   Busca el campo  Client Secret  (al lado del Client ID).
echo   Pulsa el icono del OJO para verlo y luego COPIARLO.
echo.
echo   Cuando lo tengas copiado, vuelve aqui, pulsa el boton derecho del
echo   raton en esta ventana para PEGARLO y pulsa ENTER.
echo.
echo   (No se vera nada mientras pegas: es normal, esta oculto)
echo.
set /p "SECRET=Pega el Client Secret y pulsa ENTER: "

if "%SECRET%"=="" (
  echo.
  echo   [ERROR] No pegaste nada. Cierra y vuelve a empezar.
  echo.
  pause
  exit /b 1
)

REM El secret se escribe con PowerShell usando la variable de entorno:
REM asi los simbolos % & ^ | < > " no rompen nada (con "echo" si romperian).
powershell -NoProfile -Command "[IO.File]::WriteAllText('_secret_tmp.txt', $env:SECRET)" >nul 2>&1
set "SECRET="

echo.
python obtener_token_ml.py --secret-file _secret_tmp.txt
if errorlevel 1 (
  echo.
  echo   [ERROR] No se pudo guardar el secret. Revisa el mensaje de arriba.
  echo.
  pause
  exit /b 1
)

echo.
echo   Pulsa una tecla para seguir al paso 2...
pause >nul

REM ======================================================================
REM   PASO 2: autorizar y copiar el codigo
REM ======================================================================
cls
echo.
echo ======================================================================
echo    PASO 2 de 3  -  AUTORIZAR EN MERCADO LIVRE
echo ======================================================================
echo.
echo   Se va a abrir tu navegador. Si no se abre solo, copia la direccion
echo   que aparece abajo y pegala a mano.
echo.
python obtener_token_ml.py --paso2 --abrir

echo.
echo ----------------------------------------------------------------------
echo   En el navegador:
echo     1. Pulsa PERMITIR
echo     2. Te llevara a achadinhosnozap.com.br y veras el CODIGO EN VERDE
echo     3. Pulsa COPIAR CODIGO
echo.
echo   ATENCION: el codigo caduca en 10 MINUTOS. No te entretengas.
echo ----------------------------------------------------------------------
echo.
echo   Vuelve aqui, PEGA el codigo (boton derecho) y pulsa ENTER.
echo.
set /p "CODE=Pega el codigo y pulsa ENTER: "

if "%CODE%"=="" (
  echo.
  echo   [ERROR] No pegaste nada.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -Command "[IO.File]::WriteAllText('_code_tmp.txt', $env:CODE)" >nul 2>&1
set "CODE="

echo.
python obtener_token_ml.py --code-file _code_tmp.txt

REM ======================================================================
REM   PASO 3: subir a GitHub
REM ======================================================================
echo.
echo ======================================================================
echo    PASO 3 de 3  -  SUBIR A GITHUB
echo ======================================================================
echo.
python subir_secrets.py
echo.

echo.
echo ======================================================================
echo    RESULTADO FINAL
echo ======================================================================
echo.
python obtener_token_ml.py --estado
echo.
echo ======================================================================
echo    LISTO
echo ======================================================================
echo.
echo   Si arriba pone 'Prueba real contra la API: OK', ya esta conectado.
echo   El bot empezara a verificar precios, stock y PIX de verdad.
echo.
echo   (Puedes cerrar esta ventana)
echo.
pause
