#!/bin/sh
# Copia de seguridad cifrada de PostgreSQL.
#
# Los snapshots del VPS NO son backup de base de datos: capturan el volumen a
# medias de una escritura. Esto sí es un backup consistente.
#
# Y lo más importante: PRUEBA LA RESTAURACIÓN. Un backup que nunca se ha
# restaurado no es un backup, es una carpeta.
set -eu

STAMP=$(date +%Y%m%d-%H%M%S)
FILE="/backups/powergis-${STAMP}.sql.gz"
RETENTION="${BACKUP_RETENTION_DAYS:-14}"

echo "[backup] volcando ${POSTGRES_DB} …"
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    --host=postgres \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=plain --no-owner --no-privileges \
    | gzip -9 > "${FILE}"

# Si has pedido cifrado o subida y la herramienta no está, esto FALLA.
#
# Antes se comprobaba `command -v` y, si faltaba, se saltaba el paso sin decir
# nada. El resultado era el peor posible: pides cifrado, el log dice
# «[backup] listo» y el fichero está en claro. Un backup que miente sobre lo
# que ha hecho es peor que no tenerlo, porque encima te confía.

if [ -n "${BACKUP_GPG_PASSPHRASE:-}" ]; then
    command -v gpg >/dev/null 2>&1 || {
        echo "[backup] ERROR: BACKUP_GPG_PASSPHRASE definida pero gpg no está instalado."
        exit 1; }
    echo "[backup] cifrando …"
    gpg --batch --yes --passphrase "${BACKUP_GPG_PASSPHRASE}" \
        --symmetric --cipher-algo AES256 "${FILE}"
    rm -f "${FILE}"
    FILE="${FILE}.gpg"
fi

if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
    command -v aws >/dev/null 2>&1 || {
        echo "[backup] ERROR: BACKUP_S3_BUCKET definido pero aws no está instalado."
        exit 1; }
    echo "[backup] subiendo a almacenamiento externo …"
    AWS_ACCESS_KEY_ID="${BACKUP_S3_KEY}" \
    AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET}" \
    aws --endpoint-url "${BACKUP_S3_ENDPOINT}" \
        s3 cp "${FILE}" "s3://${BACKUP_S3_BUCKET}/postgres/$(basename "${FILE}")"
else
    echo "[backup] AVISO: sin destino externo. Esta copia vive SÓLO en el VPS."
fi

find /backups -name 'powergis-*.sql.gz*' -mtime "+${RETENTION}" -delete
echo "[backup] listo: ${FILE}"
