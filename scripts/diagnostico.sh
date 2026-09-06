#!/usr/bin/env bash
# Vuelca a un solo fichero todo lo necesario para diagnosticar el entorno
# desde fuera. Equivalente a `pg diagnostico` en Windows.
#
#   ./scripts/diagnostico.sh          → diagnostico.txt
#
# No lleva secretos reales: los del entorno de pruebas son públicos y están
# en docker-compose.dev.yml.
set -uo pipefail

DEV="docker compose -f docker-compose.dev.yml"
OUT="${1:-diagnostico.txt}"

seccion() { printf '\n===== %s %s\n' "$1" "$(printf '=%.0s' $(seq 1 $((54 - ${#1}))))"; }

{
	echo "PowerGIS · diagnóstico"
	echo "Fecha: $(date -Iseconds)"
	echo "Sistema: $(uname -srm)"

	seccion "1. SERVICIOS"
	$DEV ps 2>&1

	seccion "2. VERSIONES"
	docker --version 2>&1
	docker compose version 2>&1

	seccion "3. DOCTOR"
	$DEV exec -T api powergis doctor 2>&1

	seccion "4. ENDPOINTS"
	$DEV exec -T api powergis endpoints 2>&1

	seccion "5. RUTAS DE WORDPRESS"
	$DEV --profile setup run --rm --entrypoint= wpcli \
		wp eval 'foreach (rest_get_server()->get_routes() as $r => $h) { if (str_starts_with($r, "/saas/v1")) { echo $r . "  ->  " . count($h) . PHP_EOL; } }' \
		--allow-root --path=/var/www/html 2>&1

	seccion "6. LOGS DEL WORKER (últimas 80)"
	$DEV logs --tail=80 worker 2>&1

	seccion "7. LOGS DE LA API (últimas 40)"
	$DEV logs --tail=40 api 2>&1
} > "$OUT"

echo "Escrito en $(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
echo "Mándame ese fichero y lo leo entero."
