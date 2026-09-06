@echo off
REM ---------------------------------------------------------------------------
REM PowerGIS · atajos para Windows (cmd y PowerShell)
REM
REM `make` no existe en Windows y los scripts .sh necesitan bash, así que aquí
REM va el mismo juego de comandos en un .cmd. Todo se ejecuta DENTRO de los
REM contenedores, así que hace exactamente lo mismo que en Linux o macOS.
REM
REM   En cmd.exe:      pg dev
REM   En PowerShell:   .\pg dev      ← el .\ es obligatorio
REM
REM PowerShell no ejecuta programas del directorio actual salvo que se lo
REM pidas con `.\`, por seguridad. cmd.exe sí lo hace.
REM
REM   pg dev            levanta el entorno de pruebas
REM   pg setup          instala WordPress y activa el plugin
REM   pg doctor         diagnostica el motor (lo primero cuando algo falla)
REM   pg smoke          prueba de humo de punta a punta
REM   pg endpoints      dispara todos los endpoints con datos de prueba
REM   pg demo           datos sintéticos para arrancar sin INE
REM   pg almacen        catálogo + geografías + municipios del INE
REM   pg formulario     mete el payload real del formulario por el circuito
REM   pg rutas          detecta choques de rutas entre plugin y tema
REM   pg logs [serv]    sigue los logs
REM   pg ps             estado de los servicios
REM   pg diagnostico    lo vuelca TODO a diagnostico.txt, para mandarlo
REM   pg reset          borra todo y vuelve a empezar
REM ---------------------------------------------------------------------------

setlocal
set "DEV=docker compose -f docker-compose.dev.yml"
REM El perfil de produccion, tambien en local: es el que usa el tunel.
set "PROD=docker compose -f docker-compose.yml"

set "CMD=%~1"
if "%CMD%"=="" goto :ayuda

REM Se valida el comando ANTES de saltar. `goto :etiqueta-inexistente` no
REM devuelve un error que se pueda capturar con `||`: cmd aborta el script
REM entero con «No se encuentra la etiqueta del proceso por lotes», que no
REM dice nada útil. Con esto, escribir mal un comando enseña la ayuda.
for %%C in (dev setup doctor smoke endpoints demo almacen verify ingest formulario rutas logs ps diagnostico psql down reset secreto firmar firmar-get firmar-web tunel tunel-rapido tunel-off) do if /i "%%C"=="%CMD%" goto :%%C
goto :desconocido

:dev
%DEV% up -d --build
echo.
echo Esperando a la base de datos...
timeout /t 10 /nobreak >nul
%DEV% exec -T api alembic upgrade head
REM Igual que `make dev`: sin la semilla el motor arranca con las tablas
REM vacias y toda consulta de geografia devuelve 404. Estaban desalineados.
%DEV% exec -T api powergis seed --demo
%DEV% --profile setup run --rm wpcli
echo.
echo   WordPress  http://localhost:8080   (admin/admin . cliente/cliente)
echo   Motor      http://localhost:8000/docs
echo.
echo   Comprueba con:  pg doctor
goto :fin

:setup
%DEV% --profile setup run --rm wpcli
goto :fin

REM --------------------------------------------------------------------------
REM  Antes de meterse dentro del contenedor, comprobar que hay contenedor.
REM
REM  Sin esto, si `postgres` o `redis` estan caidos el diagnostico sale con
REM  tres lineas de «Name or service not known», que es el DNS interno de
REM  Compose diciendo que ese servicio no existe — no un problema de red ni
REM  de configuracion. El mensaje real es «no esta levantado», y conviene
REM  decirlo asi.
REM --------------------------------------------------------------------------
:comprobar
%DEV% ps --services --status running > "%TEMP%\pg-servicios.txt" 2>nul
set "FALTAN="
findstr /X /C:"postgres" "%TEMP%\pg-servicios.txt" >nul || set "FALTAN=%FALTAN% postgres"
findstr /X /C:"redis"    "%TEMP%\pg-servicios.txt" >nul || set "FALTAN=%FALTAN% redis"
findstr /X /C:"api"      "%TEMP%\pg-servicios.txt" >nul || set "FALTAN=%FALTAN% api"
if "%FALTAN%"=="" exit /b 0
echo.
echo   No estan arriba estos servicios del entorno de pruebas:%FALTAN%
echo.
echo   El DNS interno de Docker solo resuelve nombres de contenedores que
echo   estan corriendo. Por eso el motor dice «Name or service not known»:
echo   no es un fallo de red, es que no hay nadie al otro lado.
echo.
echo   Causas, por orden de frecuencia:
echo.
echo   1^) El entorno no esta levantado, o Docker Desktop se reinicio y no
echo      volvio todo. Se arregla igual:
echo            .\pg dev
echo.
echo   2^) Estas mirando el proyecto equivocado. Los comandos del tunel usan
echo      el perfil de PRODUCCION ^(proyecto "powergis"^); todos los demas
echo      usan el de pruebas ^(proyecto "powergis-dev"^). Son dos stacks
echo      independientes. Para ver cual tienes arriba:
echo            docker compose ls
echo.
echo   3^) Un servicio arranco y murio. El motivo esta en sus logs:
echo            .\pg logs postgres
echo.
echo   Estado de todos los contenedores del entorno de pruebas:
%DEV% ps -a
exit /b 1

:doctor
call :comprobar || exit /b 1
%DEV% exec -T api powergis doctor
goto :fin

:smoke
call :comprobar || exit /b 1
%DEV% exec -T api powergis smoke
goto :fin

:endpoints
call :comprobar || exit /b 1
%DEV% exec -T api powergis endpoints
goto :fin

:demo
call :comprobar || exit /b 1
%DEV% exec -T api powergis seed --demo
goto :fin

:almacen
call :comprobar || exit /b 1
%DEV% exec -T api powergis seed
%DEV% exec -T api powergis load-municipios
echo.
echo Antes de cargar datos:  pg verify
goto :fin

:verify
call :comprobar || exit /b 1
%DEV% exec -T api powergis ine-verify
goto :fin

:ingest
call :comprobar || exit /b 1
%DEV% exec -T api powergis ine-verify || (echo. & echo ABORTADO: el mapeo del INE no cuadra. & exit /b 1)
%DEV% exec -T api powergis ingest ine --level municipio
goto :fin

REM --------------------------------------------------------------------------
REM  El tunel: publica ESTE motor en internet para que powergis.es lo alcance.
REM
REM  Usa el perfil de PRODUCCION en local (docker-compose.yml), no el de
REM  desarrollo. No es un capricho: el de desarrollo lleva el HMAC_SECRET
REM  escrito en el fichero, y por tanto en el repositorio. Publicarlo seria
REM  poner en internet un motor cuya unica llave conoce cualquiera que haya
REM  visto el codigo.
REM --------------------------------------------------------------------------

:secreto
docker run --rm alpine/openssl rand -hex 32
goto :fin

REM --------------------------------------------------------------------------
REM  Firmar para probar desde Swagger.
REM
REM  El cuerpo se lee de scripts\cuerpo.json y NO se copia por la linea de
REM  comandos: entre las comillas de cmd y los saltos CRLF de Windows, firmar
REM  a mano es donde mas se falla. La carpeta scripts\ esta montada dentro del
REM  contenedor como /scripts, asi que editas en Windows y firma el motor.
REM --------------------------------------------------------------------------

:firmar
call :comprobar || exit /b 1
if not exist "scripts\cuerpo.json" (
  echo No existe scripts\cuerpo.json.
  echo El repositorio trae uno de ejemplo; editalo y vuelve a intentarlo.
  exit /b 1
)
%DEV% exec -T api powergis firmar --cuerpo /scripts/cuerpo.json
goto :fin

:firmar-web
REM Abre el firmador offline. Es un FICHERO, no lo sirve el motor: pedirselo
REM a localhost:8000/docs/firmar.html devuelve el 404 de la API, porque ahi
REM /docs es Swagger. Coincidencia de nombres con la carpeta docs\ del
REM repositorio.
if not exist "docs\firmar.html" (
  echo No encuentro docs\firmar.html.
  echo Ejecuta esto desde la raiz del repositorio.
  exit /b 1
)
start "" "docs\firmar.html"
echo Abierto docs\firmar.html en tu navegador.
echo El secreto de pruebas es:
echo    dev-secreto-compartido-cambialo-en-produccion-0123456789
goto :fin

:firmar-get
call :comprobar || exit /b 1
if "%2"=="" (
  echo Indica la ruta. Ejemplo:
  echo    .\pg firmar-get /v1/reports/11111111-2222-3333-4444-555555555555 wp_user_id=1
  exit /b 1
)
%DEV% exec -T api powergis firmar --get %2 --query "%3"
goto :fin

:tunel
if not exist ".env" (
  echo No hay fichero .env. Copia .env.example y rellenalo:
  echo    copy .env.example .env
  echo.
  echo Genera cada secreto con:  pg secreto
  exit /b 1
)
findstr /B /C:"TUNNEL_TOKEN=" .env | findstr /R "TUNNEL_TOKEN=..*" >nul || (
  echo Falta TUNNEL_TOKEN en .env.
  echo    Cloudflare ^> Zero Trust ^> Networks ^> Tunnels ^> Create a tunnel
  exit /b 1
)
%PROD% -f docker-compose.tunnel.yml up -d --build
echo.
echo Comprueba que responde por el nombre publico, no por localhost:
echo    curl -i https://TU-NOMBRE.powergis.es/health              200
echo    curl -i https://TU-NOMBRE.powergis.es/internal/coverage   404
echo.
echo Para pararlo:  pg tunel-off
goto :fin

:tunel-rapido
REM Tunel EFIMERO: sin cuenta, sin DNS, sin tocar el dominio. Cloudflare da
REM un nombre https://algo.trycloudflare.com que cambia en CADA arranque.
REM
REM Por eso no se edita wp-config: pega el nombre que salga aqui en
REM   Proyectos ^> Diagnostico ^> URL del motor (modo pruebas)
REM y listo. Esa pantalla solo aparece si POWERGIS_ENGINE_URL no esta
REM definida, que es justo el caso mientras pruebas.
REM
REM Esta ventana se queda ocupada: el tunel vive mientras el comando corra.
REM Ciérrala con Ctrl+C cuando termines.
%PROD% up -d --build
echo.
echo Levantando el tunel. Busca la linea con trycloudflare.com:
echo.
docker run --rm --network powergis_default cloudflare/cloudflared:latest tunnel --url http://api:8000
goto :fin

:tunel-off
%PROD% -f docker-compose.tunnel.yml stop cloudflared
echo.
echo Tunel cerrado. El motor sigue en marcha, pero ya no es alcanzable
echo desde internet.
goto :fin

:formulario
%DEV% --profile setup run --rm --entrypoint= wpcli wp eval-file /scripts/probar-formulario.php --allow-root --path=/var/www/html
goto :fin

:rutas
%DEV% --profile setup run --rm --entrypoint= wpcli wp eval "foreach (rest_get_server()->get_routes() as $r => $h) { if (str_starts_with($r, '/saas/v1')) { echo $r . '  ->  ' . count($h) . ' manejador(es)' . (count($h) > 1 ? '  OJO: CHOQUE' : '') . PHP_EOL; } }" --allow-root --path=/var/www/html
goto :fin

:logs
if "%2"=="" (%DEV% logs -f --tail=100) else (%DEV% logs -f --tail=100 %2)
goto :fin

:ps
%DEV% ps
goto :fin

:diagnostico
REM Un solo fichero con todo lo que hace falta para diagnosticar desde fuera.
REM Se manda tal cual: no lleva secretos reales, sólo los de desarrollo.
set "OUT=diagnostico.txt"
echo PowerGIS · diagnostico > "%OUT%"
echo Fecha: %DATE% %TIME% >> "%OUT%"
echo. >> "%OUT%"
echo ===== 1. SERVICIOS ===================================== >> "%OUT%"
%DEV% ps >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 2. VERSIONES ==================================== >> "%OUT%"
docker --version >> "%OUT%" 2>&1
docker compose version >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 3. DOCTOR ======================================= >> "%OUT%"
%DEV% exec -T api powergis doctor >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 4. ENDPOINTS ==================================== >> "%OUT%"
%DEV% exec -T api powergis endpoints >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 5. RUTAS DE WORDPRESS =========================== >> "%OUT%"
%DEV% --profile setup run --rm --entrypoint= wpcli wp eval "foreach (rest_get_server()->get_routes() as $r => $h) { if (str_starts_with($r, '/saas/v1')) { echo $r . '  ->  ' . count($h) . PHP_EOL; } }" --allow-root --path=/var/www/html >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 6. LOGS DEL WORKER (ultimas 80) ================= >> "%OUT%"
%DEV% logs --tail=80 worker >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== 7. LOGS DE LA API (ultimas 40) ================== >> "%OUT%"
%DEV% logs --tail=40 api >> "%OUT%" 2>&1
echo.
echo Escrito en %CD%\%OUT%
echo Mandame ese fichero y lo leo entero.
goto :fin

:psql
%DEV% exec postgres psql -U powergis -d powergis
goto :fin

:down
%DEV% down
goto :fin

:reset
%DEV% down -v
call "%~f0" dev
goto :fin

:desconocido
echo Comando desconocido: %CMD%
:ayuda
echo.
echo PowerGIS · atajos para Windows
echo.
echo   pg dev          levanta el entorno de pruebas
echo   pg setup        instala WordPress y activa el plugin
echo   pg doctor       diagnostica el motor (empieza SIEMPRE por aqui)
echo   pg smoke        prueba de humo de punta a punta
echo   pg endpoints    dispara todos los endpoints con datos de prueba
echo   pg demo         datos sinteticos, sin depender del INE
echo   pg almacen      catalogo + geografias + municipios
echo   pg verify       comprueba las tablas del INE antes de cargar
echo   pg ingest       carga la demografia del INE
echo   pg formulario   mete el payload real del formulario por el circuito
echo   pg rutas        detecta choques de rutas entre plugin y tema
echo   pg logs [serv]  sigue los logs (ej: pg logs worker)
echo   pg ps           estado de los servicios
echo   pg diagnostico  vuelca TODO a diagnostico.txt, para mandarmelo
echo   pg psql         consola SQL
echo   pg down         para el entorno
echo   pg reset        borra TODO y vuelve a empezar
echo.
echo  Probar contra powergis.es (el front real, en internet):
echo   pg secreto      genera un secreto de 32 bytes
echo   pg firmar       firma scripts\cuerpo.json para pegarlo en Swagger
echo   pg firmar-get   firma un GET: pg firmar-get /v1/reports/UUID wp_user_id=1
echo   pg firmar-web   abre el firmador offline en el navegador
echo   pg tunel        publica este motor (tunel con nombre propio)
echo   pg tunel-rapido tunel efimero, sin cuenta ni DNS
echo   pg tunel-off    cierra el tunel
echo.
goto :fin

:fin
endlocal
