#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PowerGIS · crear el servidor en Hetzner Cloud desde la línea de comandos
#
#     ./infra/hetzner/crear-servidor.sh
#     ./infra/hetzner/crear-servidor.sh --tipo cx33 --nombre powergis-pro
#
# Hace tres cosas y las deja verificadas:
#
#   1. Un firewall de Hetzner que sólo deja pasar 22, 80 y 443.
#   2. El servidor, con el cloud-init de esta carpeta como user-data, así que
#      nace ya endurecido: sin root, sin contraseñas, con ufw, swap y Docker.
#   3. SIN IPv6, y esto es deliberado — ver el aviso al final del fichero.
#
# Requisitos:
#   · hcloud CLI          https://github.com/hetznercloud/cli
#   · export HCLOUD_TOKEN=…   (Proyecto → Security → API tokens, permiso R/W)
#   · tu clave SSH subida al proyecto de Hetzner
# ---------------------------------------------------------------------------
set -euo pipefail

NOMBRE="powergis"
TIPO="cx23"
UBICACION="nbg1"          # Núremberg. fsn1 = Falkenstein, hel1 = Helsinki.
IMAGEN="ubuntu-24.04"
CLAVE_SSH=""

while [ $# -gt 0 ]; do
	case "$1" in
		--nombre)    NOMBRE="$2";    shift 2 ;;
		--tipo)      TIPO="$2";      shift 2 ;;
		--ubicacion) UBICACION="$2"; shift 2 ;;
		--clave)     CLAVE_SSH="$2"; shift 2 ;;
		-h|--help)
			sed -n '2,22p' "$0" | sed 's/^# \?//'
			exit 0 ;;
		*) echo "Opción desconocida: $1" >&2; exit 1 ;;
	esac
done

AQUI="$(cd "$(dirname "$0")" && pwd)"
PLANTILLA="$AQUI/cloud-init.yaml"

# -- comprobaciones previas -------------------------------------------------

command -v hcloud >/dev/null 2>&1 || {
	echo "Falta el CLI de Hetzner. Instálalo:"
	echo "  https://github.com/hetznercloud/cli/releases"
	exit 1; }

[ -n "${HCLOUD_TOKEN:-}" ] || {
	echo "Falta HCLOUD_TOKEN."
	echo "  Consola de Hetzner → tu proyecto → Security → API tokens (Read & Write)"
	echo "  export HCLOUD_TOKEN=…"
	exit 1; }

[ -f "$PLANTILLA" ] || { echo "No encuentro $PLANTILLA"; exit 1; }

# La clave SSH: la del proyecto de Hetzner (para poder entrar aunque
# cloud-init falle) y la misma dentro del cloud-init (para el usuario
# `powergis`). Si sólo pones una de las dos, o entras como root o no entras.
if [ -z "$CLAVE_SSH" ]; then
	CLAVE_SSH="$(hcloud ssh-key list -o noheader -o columns=name | head -1 || true)"
fi
[ -n "$CLAVE_SSH" ] || {
	echo "No hay ninguna clave SSH en el proyecto de Hetzner."
	echo "  hcloud ssh-key create --name mi-portatil --public-key-from-file ~/.ssh/id_ed25519.pub"
	exit 1; }

PUBLICA="$(hcloud ssh-key describe "$CLAVE_SSH" -o format='{{.PublicKey}}')"
[ -n "$PUBLICA" ] || { echo "No pude leer la clave pública de '$CLAVE_SSH'"; exit 1; }

if grep -q 'AQUI_TU_CLAVE_PUBLICA' "$PLANTILLA"; then
	echo "· Inyectando la clave '$CLAVE_SSH' en el cloud-init."
fi

USERDATA="$(mktemp)"
trap 'rm -f "$USERDATA"' EXIT
# `awk` en vez de `sed`: la clave pública lleva `/` y `+`, que romperían el
# patrón de sustitución de sed sin un escapado incómodo.
awk -v clave="$PUBLICA" \
	'{ gsub(/AQUI_TU_CLAVE_PUBLICA/, clave); print }' \
	"$PLANTILLA" > "$USERDATA"

# -- 1. firewall ------------------------------------------------------------

FW="${NOMBRE}-fw"
if hcloud firewall describe "$FW" >/dev/null 2>&1; then
	echo "· El firewall '$FW' ya existe."
else
	echo "· Creando el firewall '$FW' (22, 80, 443 y nada más)…"
	hcloud firewall create --name "$FW" >/dev/null
	for PUERTO in 22 80 443; do
		hcloud firewall add-rule "$FW" \
			--direction in --protocol tcp --port "$PUERTO" \
			--source-ips 0.0.0.0/0 --source-ips ::/0 >/dev/null
	done
fi

# -- 2. servidor ------------------------------------------------------------

if hcloud server describe "$NOMBRE" >/dev/null 2>&1; then
	echo "· El servidor '$NOMBRE' ya existe. No toco nada."
else
	echo "· Creando '$NOMBRE' ($TIPO, $IMAGEN, $UBICACION)…"
	hcloud server create \
		--name "$NOMBRE" \
		--type "$TIPO" \
		--image "$IMAGEN" \
		--location "$UBICACION" \
		--ssh-key "$CLAVE_SSH" \
		--firewall "$FW" \
		--user-data-from-file "$USERDATA" \
		--without-ipv6
fi

IP="$(hcloud server ip "$NOMBRE")"

cat <<FIN

──────────────────────────────────────────────────────────────
 Servidor '$NOMBRE' en $IP

 cloud-init tarda un par de minutos en terminar. Espera y entra:

     ssh powergis@$IP
     cloud-init status --wait          → status: done

 Luego, en tu proveedor de DNS:

     Tipo   Nombre   Valor          TTL
     A      motor    $IP            300

 NO crees un registro AAAA. Ver la nota de abajo.

 Y cuando 'dig +short motor.powergis.es' devuelva esa IP:

     git clone <tu-repo> powergis && cd powergis
     cp .env.example .env    # y rellénalo
     make check-config
     make up TIER=$TIPO
──────────────────────────────────────────────────────────────
FIN

# ---------------------------------------------------------------------------
# Por qué --without-ipv6
# ---------------------------------------------------------------------------
#
# Hetzner asigna un /64 de IPv6 a cada servidor, y la consola invita a crear
# el registro AAAA correspondiente. El problema es Let's Encrypt: si existe
# un AAAA, lo prefiere sobre el A para el desafío HTTP. Docker no enruta IPv6
# salvo que se configure a mano, así que Traefik no recibe ese desafío, el
# certificado no se emite, y el mensaje de error habla de tiempos de espera
# sin mencionar en ningún momento IPv6. Se pierde una tarde.
#
# Con `--without-ipv6` el servidor no tiene dirección IPv6, no hay tentación
# de crear el AAAA, y el problema no puede darse.
#
# Si más adelante quieres IPv6 de verdad: habilítalo en el demonio de Docker
# (`"ipv6": true` y `"fixed-cidr-v6"` en /etc/docker/daemon.json), comprueba
# que Traefik escucha en `::`, y sólo ENTONCES crea el AAAA.
