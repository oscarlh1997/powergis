#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PowerGIS · desplegar la última versión desde GitHub
#
#     ~/powergis/infra/hostinger/desplegar.sh
#
# Trae los cambios, reconstruye lo que haga falta y deja el stack en marcha.
# Pensado para ejecutarse muchas veces: es lo que sustituye a subir un zip.
#
# Lo que NO toca, y conviene tenerlo claro:
#
#   · El `.env`. Está en .gitignore, así que `git pull` no lo ve. Tus secretos
#     viven sólo aquí, en el servidor.
#   · Los volúmenes de Docker. La base de datos, el almacén de indicadores y
#     los certificados sobreviven a cualquier despliegue.
#
# Si has tocado ficheros en el servidor a mano, `git pull` se negará a pisarlos
# y lo dirá. Es a propósito: prefiero que falle a que se pierda un cambio.
# ---------------------------------------------------------------------------
set -euo pipefail

RAIZ="${RAIZ:-$HOME/powergis}"

azul()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()    { printf '   \033[0;32mok\033[0m  %s\n' "$*"; }
morir() { printf '\n\033[0;31mABORTADO: %s\033[0m\n' "$*" >&2; exit 1; }

cd "$RAIZ" 2>/dev/null || morir "no encuentro $RAIZ"
[ -d .git ] || morir "$RAIZ no es un repositorio git. Clónalo primero."
[ -f .env ] || morir "falta el .env. Crea uno desde .env.example antes de desplegar."

azul "Estado actual"
ANTES="$(git rev-parse --short HEAD)"
ok "en $ANTES · rama $(git rev-parse --abbrev-ref HEAD)"

# Un cambio local sin guardar se perdería o bloquearía el pull. Mejor saberlo.
if ! git diff --quiet || ! git diff --cached --quiet; then
	printf '\n\033[0;33m!!\033[0m  Hay cambios locales sin confirmar:\n\n'
	git status --short
	printf '\n    Guárdalos (git stash) o descártalos antes de desplegar.\n'
	morir "no sigo con cambios sin confirmar"
fi

azul "Trayendo cambios"
git pull --ff-only
DESPUES="$(git rev-parse --short HEAD)"

if [ "$ANTES" = "$DESPUES" ]; then
	ok "ya estabas en la última versión"
else
	ok "$ANTES → $DESPUES"
	echo
	git --no-pager log --oneline "$ANTES..$DESPUES" | sed 's/^/     /'
fi

azul "Levantando"
# `make up` reconstruye la imagen si el código cambió y deja intactos los
# volúmenes. No hace falta `down`: Compose recrea sólo lo que difiere.
make up

azul "Estado"
make ps

cat <<FIN

──────────────────────────────────────────────────────────────
 Desplegado.

 Comprueba:
     curl -i https://\${ENGINE_HOST:-motor.powergis.es}/health   200
     curl -i https://\${ENGINE_HOST:-motor.powergis.es}/ready     200

 Si algo no responde:  make logs
──────────────────────────────────────────────────────────────
FIN
