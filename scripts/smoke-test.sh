#!/usr/bin/env bash
# Prueba de humo del motor: firma HMAC de punta a punta, sin WordPress.
#
#   ./scripts/smoke-test.sh [URL_MOTOR] [SECRETO]
#
# Comprueba, en este orden:
#   1. el motor responde;
#   2. una lectura SIN firma se rechaza (el agujero que no debe existir);
#   3. una escritura firmada crea el informe;
#   4. una lectura firmada lo devuelve;
#   5. el informe básico NO trae datos de las secciones de pago.
set -uo pipefail

ENGINE="${1:-http://localhost:8000}"
SECRET="${2:-dev-secreto-compartido-cambialo-en-produccion-0123456789}"
UUID="${UUID:-$(cat /proc/sys/kernel/random/uuid)}"

OK=0; KO=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; OK=$((OK+1)); }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; KO=$((KO+1)); }

sign_body() {  # $1 = cuerpo
	TS=$(date +%s)
	SIG=$(printf '%s\n%s' "$TS" "$1" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')
	printf '%s %s' "$TS" "$SIG"
}
sign_get() {   # $1 = ruta?query
	TS=$(date +%s)
	SIG=$(printf '%s\nGET\n%s' "$TS" "$1" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')
	printf '%s %s' "$TS" "$SIG"
}

echo "PowerGIS · prueba de humo"
echo "Motor: $ENGINE"
echo "UUID:  $UUID"
echo ""

# 1 ------------------------------------------------------------------------
echo "1 · El motor responde"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$ENGINE/health" || echo 000)
[ "$CODE" = "200" ] && pass "GET /health → 200" || fail "GET /health → $CODE (¿está levantado?)"
[ "$CODE" = "200" ] || { echo; echo "Nada más que probar. Arranca el motor y vuelve."; exit 1; }

# 2 ------------------------------------------------------------------------
echo ""
echo "2 · Las lecturas exigen firma"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$ENGINE/v1/reports/$UUID?wp_user_id=1")
[ "$CODE" = "401" ] && pass "GET sin firma → 401" \
	|| fail "GET sin firma → $CODE (DEBERÍA ser 401: un UUID filtrado abriría el informe)"

CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$ENGINE/v1/reports" \
	-H 'Content-Type: application/json' -d '{"project_uuid":"'"$UUID"'"}')
[ "$CODE" = "401" ] && pass "POST sin firma → 401" || fail "POST sin firma → $CODE"

# 3 ------------------------------------------------------------------------
echo ""
echo "3 · Escritura firmada"
BODY='{"project_uuid":"'"$UUID"'","wp_user_id":1,"tier":"basico","scope":{"level":"ccaa","ine_code":"13","children_level":"provincia"},"segments":{"age":["18-35"],"sex":["F","M"]},"business":{"sector":"restauracion"}}'
read -r TS SIG <<<"$(sign_body "$BODY")"
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "$ENGINE/v1/reports" \
	-H 'Content-Type: application/json' \
	-H "X-PG-Timestamp: $TS" -H "X-PG-Signature: $SIG" \
	-H "Idempotency-Key: $UUID" -d "$BODY")
CODE=$(echo "$RESPONSE" | tail -1)
if [ "$CODE" = "202" ]; then
	pass "POST /v1/reports firmado → 202"
else
	fail "POST /v1/reports firmado → $CODE"
	echo "$RESPONSE" | head -1 | sed 's/^/      /'
	[ "$CODE" = "401" ] && echo "      → el secreto del motor y el de este script no coinciden"
fi

# 4 ------------------------------------------------------------------------
echo ""
echo "4 · Lectura firmada (se espera al worker)"
PAYLOAD=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
	sleep 2
	read -r TS SIG <<<"$(sign_get "/v1/reports/$UUID?wp_user_id=1")"
	RESPONSE=$(curl -s -w '\n%{http_code}' "$ENGINE/v1/reports/$UUID?wp_user_id=1" \
		-H "X-PG-Timestamp: $TS" -H "X-PG-Signature: $SIG")
	CODE=$(echo "$RESPONSE" | tail -1)
	[ "$CODE" = "200" ] && { PAYLOAD=$(echo "$RESPONSE" | head -n -1); break; }
	printf '  · intento %s: HTTP %s\n' "$attempt" "$CODE"
done

if [ -n "$PAYLOAD" ]; then
	pass "GET firmado → 200"
	echo "$PAYLOAD" | grep -q '"tier":"basico"' && pass "tier = basico" || fail "tier inesperado"
	echo "$PAYLOAD" | grep -q 'Comunidad de Madrid' && pass "ámbito resuelto" || fail "ámbito sin resolver"
else
	fail "el informe no llegó a estar listo"
	echo "      → mira los logs del worker: docker compose -f docker-compose.dev.yml logs worker"
fi

# 5 ------------------------------------------------------------------------
echo ""
echo "5 · El básico no filtra datos de pago"
if [ -n "$PAYLOAD" ]; then
	echo "$PAYLOAD" | grep -q 'eco.income.household.mean' \
		&& fail "FUGA: hay indicadores de pago en el informe gratuito" \
		|| pass "sin indicadores de pago"
	echo "$PAYLOAD" | grep -q '"placerank":null' \
		&& pass "sin PlaceRank" || fail "el básico no debería traer PlaceRank"
	echo "$PAYLOAD" | grep -q '"locked_reason":"tier"' \
		&& pass "secciones bloqueadas anunciadas" || fail "faltan las secciones bloqueadas"
else
	echo "  (omitido: no hay payload)"
fi

echo ""
printf '─── %s correctas, %s fallidas ───\n' "$OK" "$KO"
[ "$KO" -eq 0 ] || exit 1
