# ---------------------------------------------------------------------------
# PowerGIS · subir el código al VPS desde Windows
#
#     .\infra\hostinger\subir.ps1 -Ip 72.62.178.78
#     .\infra\hostinger\subir.ps1 -Ip 72.62.178.78 -Usuario root    # antes de endurecer
#     .\infra\hostinger\subir.ps1 -Ip 72.62.178.78 -SoloPaquete     # solo empaqueta
#
# Empaqueta, sube y descomprime en un solo comando. Está pensado para
# repetirse: vas a subir el código muchas veces mientras ajustamos cosas.
#
# DOS COSAS QUE NO TOCA, y son las que importan:
#
#   · El `.env` del servidor. No entra en el paquete, así que descomprimir
#     encima jamás se lleva por delante tus secretos.
#   · Los volúmenes de Docker. Subir código no toca la base de datos.
#
# Usa `tar`, que viene con Windows 10 y 11 desde 2018. `Compress-Archive` no
# vale aquí: cuando se le pasa una lista de ficheros APLANA las carpetas, y
# `engine/src/powergis/cli.py` llegaría al servidor como `cli.py` en la raíz.
# ---------------------------------------------------------------------------

param(
	[Parameter(Mandatory = $true)][string]$Ip,
	[string]$Usuario = "powergis",
	[string]$Destino = "powergis",
	[switch]$SoloPaquete
)

$ErrorActionPreference = "Stop"

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Bien($t) { Write-Host "   ok  $t" -ForegroundColor Green }
function Mal($t)  { Write-Host "`nABORTADO: $t" -ForegroundColor Red; exit 1 }

# -- comprobaciones previas -------------------------------------------------

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
	Mal "No encuentro 'ssh'. Actívalo en Configuración > Aplicaciones > Características opcionales > Cliente OpenSSH."
}
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
	Mal "No encuentro 'tar'. Viene con Windows 10/11; si no está, usa WinSCP (ver infra/hostinger/LEEME.md)."
}
if (-not (Test-Path "docker-compose.yml")) {
	Mal "Ejecuta esto desde la raíz del repositorio, donde está docker-compose.yml."
}

# -- 1. empaquetar ----------------------------------------------------------

Paso "Empaquetando"

$paquete = Join-Path $env:TEMP "powergis.tgz"
if (Test-Path $paquete) { Remove-Item $paquete -Force }

# `--exclude` de bsdtar. `.env` fuera: es lo único irrecuperable del servidor.
& tar -czf $paquete `
	--exclude=.git `
	--exclude=.env `
	--exclude=__pycache__ `
	--exclude=*.pyc `
	--exclude=.ruff_cache `
	--exclude=.pytest_cache `
	--exclude=node_modules `
	--exclude=*.tgz `
	--exclude=*.zip `
	.

if ($LASTEXITCODE -ne 0 -or -not (Test-Path $paquete)) { Mal "tar falló al empaquetar." }

$mb = [math]::Round((Get-Item $paquete).Length / 1MB, 2)
Bien "$mb MB"

# Comprobación de que las rutas van dentro, no aplanadas.
$muestra = (& tar -tzf $paquete | Select-Object -First 400) -match 'engine/src/powergis/cli\.py'
if (-not $muestra) { Mal "el paquete no conserva las rutas; no lo subo." }
Bien "rutas conservadas (engine/src/... dentro del paquete)"
Bien ".env excluido: el del servidor se conserva"

if ($SoloPaquete) {
	Write-Host "`nPaquete en: $paquete" -ForegroundColor Yellow
	exit 0
}

# -- 2. subir ---------------------------------------------------------------

Paso "Subiendo a $Usuario@$Ip"

& scp $paquete "${Usuario}@${Ip}:/tmp/powergis.tgz"
if ($LASTEXITCODE -ne 0) { Mal "falló el scp. Revisa la IP, el usuario y que tu clave SSH esté instalada." }
Bien "subido"

# -- 3. desplegar -----------------------------------------------------------

Paso "Desplegando en ~/$Destino"

$remoto = @"
set -e
mkdir -p ~/$Destino
tar -xzf /tmp/powergis.tgz -C ~/$Destino
rm -f /tmp/powergis.tgz
chmod +x ~/$Destino/infra/*.sh ~/$Destino/infra/*/*.sh 2>/dev/null || true
echo
echo "  Raiz:"
ls -1 ~/$Destino | head -15
echo
if [ -f ~/$Destino/.env ]; then
  echo "  .env: CONSERVADO"
else
  echo "  .env: no existe todavia  ->  cp .env.example .env"
fi
"@

& ssh "${Usuario}@${Ip}" $remoto
if ($LASTEXITCODE -ne 0) { Mal "falló el despliegue en el servidor." }

Remove-Item $paquete -Force

Write-Host @"

──────────────────────────────────────────────────────────────
 Código en ~/$Destino

 La primera vez:
     ssh $Usuario@$Ip
     cd $Destino
     cp .env.example .env
     nano .env
     make check-config
     make up

 Después de un cambio, este mismo comando y luego:
     ssh $Usuario@$Ip "cd $Destino && make up"
──────────────────────────────────────────────────────────────
"@ -ForegroundColor Cyan
