@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title CRIBA - Volver a autorizar Mercado Livre
color 0E

echo.
echo ======================================================================
echo    CRIBA - VOLVER A AUTORIZAR LA API DE MERCADO LIVRE
echo ======================================================================
echo.
echo   Se usa DESPUES de cambiar los permisos en el devcenter.
echo.
echo   IMPORTANTE: si cambias los permisos de la aplicacion, el token
echo   viejo NO los hereda. Hay que emitir uno nuevo. Esto hace eso.
echo.
echo   Antes de seguir, comprueba en el devcenter que tienes:
echo.
echo      PERMISSOES
echo        Publicacao e sincronizacao   ->  Leitura
echo        Promocoes, cupons e descontos->  Leitura
echo        Usuarios                     ->  Leitura e escrita
echo.
echo      TOPICOS
echo        items, prices, catalog, promotions
echo.
echo   Y que pulsaste GUARDAR.
echo.
echo   Pulsa una tecla para continuar...
pause >nul

REM ---------- Abrir el navegador con la URL de autorizacion ----------
cls
echo.
echo ======================================================================
echo    AUTORIZAR
echo ======================================================================
echo.
echo   Se va a abrir el navegador. Si no se abre, copia la direccion que
echo   aparece abajo.
echo.
python obtener_token_ml.py --paso2 --abrir

echo.
echo ----------------------------------------------------------------------
echo     1. Pulsa PERMITIR
echo     2. Te llevara a achadinhosnozap.com.br y veras el CODIGO EN VERDE
echo     3. Pulsa COPIAR CODIGO
echo.
echo   El codigo caduca en 10 MINUTOS.
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

REM ---------- Comprobar si ahora SI funciona ----------
echo.
echo ======================================================================
echo    COMPROBANDO SI YA FUNCIONA
echo ======================================================================
echo.
python diagnosticar_api_ml.py

echo.
echo ======================================================================
echo    SUBIR A GITHUB
echo ======================================================================
echo.
python subir_secrets.py
echo.

echo ======================================================================
echo    RESULTADO
echo ======================================================================
echo.
echo   Mira arriba si pone:
echo     'TODO CORRECTO: 3/3 comprobaciones clave pasan'
echo.
echo   Si sigue diciendo 'FALTAN PERMISOS', es que el cambio de permisos
echo   no se guardo en el devcenter. Vuelve a revisarlo y repite.
echo.
echo   (Puedes cerrar esta ventana)
echo.
pause
