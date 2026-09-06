#!/usr/bin/env bash
# Genera las teselas vectoriales de GeoLens.
#
#   geometrías del IGN → mapshaper (simplificado por zoom) → tippecanoe → PMTiles
#
# Las teselas llevan SOLO `geo_code` y la geometría. Los valores viajan en el
# payload del informe y se unen en el cliente con `setFeatureState`: así una
# misma tesela sirve a todas las capas y a todos los usuarios, y el caché del
# CDN es perfecto.
#
# Requisitos:  npm i -g mapshaper   +   tippecanoe   +   pmtiles
set -euo pipefail

SRC="${1:-./infra/geo}"        # GeoJSON de entrada, uno por nivel
OUT="${2:-./data/tiles}"
mkdir -p "$OUT" "$SRC"

# Simplificación por nivel: más agresiva cuanto más grande es la unidad.
declare -A SIMPLIFY=( [ccaa]=8%  [provincia]=6%  [municipio]=3%  [seccion]=1.5% )
declare -A MINZOOM=(  [ccaa]=3   [provincia]=4   [municipio]=6   [seccion]=11 )
declare -A MAXZOOM=(  [ccaa]=8   [provincia]=9   [municipio]=12  [seccion]=16 )

for LEVEL in ccaa provincia municipio seccion; do
    INPUT="${SRC}/${LEVEL}.geojson"
    [ -f "$INPUT" ] || { echo "· ${LEVEL}: sin fichero, se omite"; continue; }

    echo "· ${LEVEL}: simplificando (${SIMPLIFY[$LEVEL]}) …"
    mapshaper "$INPUT" \
        -simplify "${SIMPLIFY[$LEVEL]}" keep-shapes \
        -filter-fields geo_code,name \
        -o format=geojson "${SRC}/${LEVEL}.simplified.geojson"

    echo "· ${LEVEL}: teselando (z${MINZOOM[$LEVEL]}–z${MAXZOOM[$LEVEL]}) …"
    tippecanoe \
        --output="${OUT}/${LEVEL}.mbtiles" --force \
        --layer="${LEVEL}" \
        --minimum-zoom="${MINZOOM[$LEVEL]}" --maximum-zoom="${MAXZOOM[$LEVEL]}" \
        --drop-densest-as-needed --coalesce-densest-as-needed \
        --no-tile-compression \
        "${SRC}/${LEVEL}.simplified.geojson"

    echo "· ${LEVEL}: convirtiendo a PMTiles …"
    pmtiles convert "${OUT}/${LEVEL}.mbtiles" "${OUT}/${LEVEL}.pmtiles"
    rm -f "${OUT}/${LEVEL}.mbtiles" "${SRC}/${LEVEL}.simplified.geojson"

    echo "  → ${OUT}/${LEVEL}.pmtiles ($(du -h "${OUT}/${LEVEL}.pmtiles" | cut -f1))"
done

echo ""
echo "Listo. Las sirve el contenedor `tiles` con caché de 30 días."
echo "Recuerda: los 8.100 municipios de España son el motivo de usar teselas"
echo "vectoriales y no GeoJSON con Leaflet."
