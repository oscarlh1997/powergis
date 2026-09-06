# Guía de pruebas — front de WordPress + motor

Todo lo que necesitas para verlo funcionando entero en tu máquina, sin tocar
powergis.es y sin configurar Stripe.

**Requisitos:** Docker + Docker Compose. Nada más.

---

## Antes de empezar: qué he cambiado para que esto sea posible

La primera versión del backend **no estaba lista** para una prueba conjunta.
Faltaban cuatro cosas, y una de ellas era un fallo de seguridad:

1. **`GET /v1/reports/{uuid}` no exigía firma.** El `wp_user_id` lo ponía quien
   llamara, así que bastaba conocer un UUID para leer el informe de pago de
   otro usuario. Ahora las lecturas van firmadas igual que las escrituras
   (`GET\nruta?query`), y hay tres tests que lo comprueban. Si esto se te
   hubiera colado a producción, habría sido una fuga de datos de clientes.
2. **Un formulario mal montado devolvía 500** en vez de decir qué campo falla.
   Los endpoints firmados validan el cuerpo a mano, y `pydantic.ValidationError`
   no lo capturaba nadie. Ahora da 422 con el detalle por campo.
3. **No había formulario.** El shortcode `[powergis_form]` no existía, así que
   no había forma de disparar el flujo desde el front sin JetFormBuilder.
4. **No había forma de probar el pago** sin exponer un webhook de Stripe a
   internet.

Ya están los cuatro. Y esto es lo que he verificado ejecutándolo de verdad,
no razonando sobre el código:

```
PostgreSQL 16 + PostGIS 3.4 reales   migración up ✓  y  downgrade ✓
Catálogo + seed                       96 indicadores · 72 geografías · 1.872 hechos
Redis + Celery reales                 3 ejecuciones completadas
API por HTTP                          10/10 comprobaciones de la prueba de humo
Flujo básico → avanzado               v1 [demografía] → v2 [las 5 secciones]
Lectura de otro usuario               403
Export XLSX firmado                   18 KB, «Microsoft Excel 2007+» válido
Paridad HMAC bash / Python / PHP      firma idéntica en los tres
```

---

## Paso 1 · Arrancar todo (una orden)

```bash
unzip powergis-backend.zip && cd powergis

docker compose -f docker-compose.dev.yml up -d --build
```

Levanta siete servicios: PostgreSQL+PostGIS, Redis, la API, un worker de
Celery, MariaDB, WordPress y el instalador. La primera vez tarda 2–4 minutos
construyendo la imagen del motor.

Comprueba que están todos arriba:

```bash
docker compose -f docker-compose.dev.yml ps
```

---

## Paso 2 · Preparar el motor

```bash
docker compose -f docker-compose.dev.yml exec api alembic upgrade head
docker compose -f docker-compose.dev.yml exec api powergis seed --demo
```

Deberías ver:

```
96 indicadores sincronizados
72 geografías cargadas
Perfiles de sector cargados
1872 hechos de demostración cargados
AVISO: los datos --demo son SINTÉTICOS. No los publiques como informe real.
```

> **`--demo` carga datos sintéticos**, no datos del INE. Sirven para ver el
> sistema funcionando hoy. Los reales se cargan en el paso 8.

Verifica el motor por su cuenta:

```bash
curl http://localhost:8000/ready
# {"status":"ok","database":true,"redis":true,...}
```

---

## Paso 3 · Preparar WordPress

```bash
docker compose -f docker-compose.dev.yml --profile setup run --rm wpcli
```

Instala WordPress, activa el plugin, arregla los enlaces permanentes (la REST
API los necesita), crea las dos páginas del flujo y un usuario no
administrador. Al terminar imprime:

```
 WordPress listo:  http://localhost:8080
   admin:    admin   / admin      (ve el simulador de pago)
   cliente:  cliente / cliente    (usuario normal)

 Formulario:     http://localhost:8080/nuevo-proyecto/
 Mis proyectos:  http://localhost:8080/mis-proyectos/
 Diagnóstico:    http://localhost:8080/wp-admin/edit.php?post_type=project&page=powergis-status
```

---

## Paso 4 · Comprobar que los dos lados se entienden

**Este es el paso que te ahorra una tarde.** Antes de tocar el front, verifica
el apretón de manos.

Entra como `admin` y abre:

```
http://localhost:8080/wp-json/saas/v1/dev/ping-engine
```

Lo que quieres ver:

```json
{
  "engine_url": "http://api:8000",
  "secret_length": 56,
  "health": 200,
  "hmac": "OK",
  "geo_hits": 1,
  "geo_first": "Comunidad de Madrid"
}
```

| Si ves… | Significa |
|---|---|
| `"hmac": "ERROR: ... invalid_signature"` | El `HMAC_SECRET` del motor y el `POWERGIS_HMAC_SECRET` de WordPress no coinciden. Son la misma cadena; en el compose de desarrollo ya vienen iguales. |
| `"health": "cURL error 7"` | WordPress no alcanza al motor. Comprueba que `api` está arriba. |
| `"secret_length": 0` | Falta `POWERGIS_HMAC_SECRET`. |

Y en **Proyectos → Diagnóstico** del escritorio tienes lo mismo con semáforos,
incluida la comprobación de que el CPT es privado.

---

## Paso 5 · El flujo completo

Entra como **`cliente` / `cliente`** (no como admin: así compruebas de paso que
los permisos funcionan).

### 5.1 · Crear el informe gratuito

`http://localhost:8080/nuevo-proyecto/`

Rellena y envía. Por defecto viene «Comunidad de Madrid», desagregada por
provincias, público objetivo 18-35, ambos géneros.

Al enviar te lleva a la página del proyecto. Verás:

- **Resumen ejecutivo** con población analizada, público objetivo y su peso.
- **Análisis demográfico** con sus KPIs, gráficos de ECharts y las **tablas
  avanzadas**: una fila por provincia, con las 3 mejores en verde y las 3
  peores en rojo. Ordenables y filtrables.
- **Cuatro secciones bloqueadas** (socioeconómico, competencia, clima, tráfico)
  como tarjetas con el CTA de desbloqueo.

**Comprueba lo importante:** abre el código fuente de la página (`Ctrl+U`) o la
pestaña Red del navegador y busca `eco.income` o `cmp.count`. **No aparecen.**
Las secciones de pago no viajan al navegador: llegan como
`{"available": false, "locked_reason": "tier"}` y nada más. No están ocultas
con CSS, no están.

### 5.2 · Ver que el segundo informe es instantáneo

Vuelve a `/nuevo-proyecto/` y crea otro proyecto **con el mismo ámbito**
(Comunidad de Madrid / provincias). Fíjate en el tiempo: el primero tardó unos
segundos, el segundo aparece casi al instante.

Es el argumento entero de la arquitectura: el segundo usuario que pide el mismo
ámbito **no toca ninguna fuente externa**, consulta el almacén.

Se ve en los logs:

```bash
docker compose -f docker-compose.dev.yml logs -f worker
```

### 5.3 · Desbloquear el informe avanzado (sin Stripe)

`http://localhost:8080/mis-proyectos/`

Aquí necesitas ser **admin** para ver el botón de simulación. Sal, entra como
`admin`, y abre «Mis proyectos». Verás los proyectos y, junto a cada uno,
**«Simular pago (dev)»**.

Ese botón hace *exactamente* lo mismo que hará el webhook real de Stripe:
llama a `POST /v1/reports/{uuid}/upgrade` en el motor y sube el `report_tier`.

Al volver al informe:

- Las cinco secciones disponibles.
- **PlaceRank** con su tabla y los cuatro deslizadores de pesos. Muévelos: el
  ranking se recalcula al instante, porque el motor reutiliza las dimensiones
  ya calculadas del snapshot en vez de volver a la base de datos.
- **GeoLens** con el panel de capas.
- Botones de **Excel, PDF y PowerPoint**.

### 5.4 · Verificar que el upgrade NO recalculó la demografía

Es la promesa central del modelo básico → avanzado. Míralo en la base de datos:

```bash
docker compose -f docker-compose.dev.yml exec postgres \
  psql -U powergis -d powergis -c \
  "SELECT run_id, tier, status, sections_done FROM report_run ORDER BY run_id;"
```

```
 run_id |   tier   | status |                    sections_done
--------+----------+--------+------------------------------------------------------
      1 | basico   | done   | {demografia}
      2 | avanzado | done   | {demografia,socioeconomico,competencia,clima,trafico}
```

Y los dos snapshots conviven — el v1 se conserva para auditoría:

```bash
docker compose -f docker-compose.dev.yml exec postgres \
  psql -U powergis -d powergis -c \
  "SELECT project_uuid, version, tier FROM report_snapshot ORDER BY version;"
```

---

## Paso 6 · Comprobar la seguridad tú mismo

### El agujero que ya no existe

```bash
# Coge un UUID de un proyecto real
docker compose -f docker-compose.dev.yml exec postgres \
  psql -U powergis -d powergis -tAc "SELECT project_uuid FROM project LIMIT 1;"

# Intenta leerlo sin firma, como haría cualquiera con la URL
curl -i "http://localhost:8000/v1/reports/PEGA-EL-UUID?wp_user_id=1"
# HTTP/1.1 401 Unauthorized   {"code":"invalid_signature"}
```

### Prueba de humo completa

```bash
./scripts/smoke-test.sh http://localhost:8000 \
  dev-secreto-compartido-cambialo-en-produccion-0123456789
```

Diez comprobaciones: que el motor responde, que rechaza lecturas y escrituras
sin firma, que acepta las firmadas, y que el informe básico no filtra nada de
pago.

### El CPT ya no es público

```bash
curl -s "http://localhost:8080/wp-json/wp/v2/project" | head -c 200
```

Sin sesión devuelve una lista vacía. En powergis.es hoy, esa misma URL lista
los proyectos de todos los usuarios.

---

## Paso 7 · Conectar tu formulario real (JetFormBuilder)

El shortcode `[powergis_form]` está para probar y para documentar el contrato.
Cuando conectes el tuyo, apúntalo a `POST /wp-json/saas/v1/projects/create` con
estos campos:

| Campo | Tipo | Obligatorio | Valores |
|---|---|---|---|
| `title` | texto | sí | máx. 200 |
| `scope_level` | texto | sí | `pais` `ccaa` `provincia` `municipio` |
| `scope_code` | texto | sí | código INE, o `ES` para nacional |
| `children_level` | texto | no | por debajo de `scope_level` |
| `age[]` | array | no | `18-35`, `65+`… |
| `sex[]` | array | no | `F` `M` |
| `sector` | texto | no | `restauracion`, `retail`… |
| `project_type` | texto | no | `apertura` `expansion` `reubicacion` |
| `avg_ticket`, `surface_m2`, `horizon_months` | número | no | |
| `company_name` | texto | no | |

Cabecera obligatoria: `X-WP-Nonce` con un nonce de `wp_rest`.

Respuesta 202:

```json
{ "post_id": 42, "project_uuid": "…", "status": "queued",
  "permalink": "http://…/proyecto/mi-cafeteria/", "poll_after": 2 }
```

El contrato exacto está en `includes/class-rest-projects.php::create_args()`.
Si mandas un campo mal, ahora recibes un 422 diciendo cuál.

---

## Paso 8 · Pasar de datos de demostración a datos reales del INE

Los datos `--demo` son sintéticos. Para los de verdad:

```bash
# 1. Comprueba qué contiene una tabla del INE ANTES de mapearla.
#    El INE renumera al republicar: no des los IDs por buenos.
docker compose -f docker-compose.dev.yml exec api powergis ine-discover 2879

# 2. Carga demografía real (tarda: son 8.100 municipios)
docker compose -f docker-compose.dev.yml exec api powergis ingest ine --level municipio

# 3. Recalcula los derivados
docker compose -f docker-compose.dev.yml exec api powergis derive --level provincia

# 4. ¿Qué indicadores del catálogo siguen sin colector?
docker compose -f docker-compose.dev.yml exec api powergis coverage
```

Si un ID no cuadra, se corrige por entorno sin desplegar: añade
`INE_TABLE_DEM_POP_TOTAL=<id>` al `environment` del servicio `api`.

---

## Paso 9 · Cuando quieras probar Stripe de verdad

En local, con Stripe CLI:

```bash
stripe login
stripe listen --forward-to http://localhost:8080/wp-json/saas/v1/stripe/webhook
# copia el whsec_… que imprime
```

Añade al `WORDPRESS_CONFIG_EXTRA` del compose:

```php
define( 'POWERGIS_STRIPE_SECRET',         'sk_test_…' );
define( 'POWERGIS_STRIPE_WEBHOOK_SECRET', 'whsec_…' );
define( 'POWERGIS_STRIPE_PRICE_ID',       'price_…' );
```

Reinicia WordPress y usa el botón normal de desbloqueo. Prueba con la tarjeta
`4242 4242 4242 4242`.

Después: `stripe trigger charge.refunded` — el informe debe volver a básico.

---

## Qué NO vas a ver funcionando todavía, y por qué

Honestidad por delante, para que no pierdas tiempo buscando fallos que no lo son:

| Qué | Por qué | Cómo se resuelve |
|---|---|---|
| **El mapa de GeoLens sale como tabla** | No hay teselas vectoriales generadas. Los datos de las capas sí están calculados, y el front los muestra como tabla en vez de dejar un hueco gris. | `infra/build-tiles.sh` con las geometrías del IGN |
| **Competencia y tráfico vacíos** | No hay extracto de OSM cargado. La sección lo dice en `warnings` en vez de inventar cifras. | Extracto de Geofabrik → PostGIS |
| **Clima parcial** | Sin `AEMET_API_KEY`. | API key gratuita de AEMET OpenData |
| **Socioeconómico con huecos** | Con datos `--demo` solo hay renta en algunas zonas. Ávila aparece como «no disponible», que es lo correcto: el ADRH no publica en municipios pequeños. | Carga real del ADRH |
| **Aviso «96 indicadores caducos»** | Los datos demo llevan fecha 2024 y el motor los considera caducos. Correcto, y lo dice en vez de callárselo. | Desaparece con datos reales |
| **Municipios en el desplegable** | El seed trae país + 19 CCAA + 52 provincias. Los 8.100 municipios necesitan la carga del INE. | Paso 8 |

Ninguna es un fallo: son datos que faltan, y el sistema lo declara en lugar de
rellenar huecos con ceros.

---

## Si algo falla

```bash
# Logs
docker compose -f docker-compose.dev.yml logs -f api worker
docker compose -f docker-compose.dev.yml exec wordpress tail -f /var/www/html/wp-content/debug.log

# Estado de las ejecuciones
docker compose -f docker-compose.dev.yml exec postgres psql -U powergis -d powergis \
  -c "SELECT run_id, tier, status, error FROM report_run ORDER BY run_id DESC LIMIT 5;"

# Empezar de cero (BORRA los datos)
docker compose -f docker-compose.dev.yml down -v
```

| Síntoma | Causa casi siempre |
|---|---|
| `401 invalid_signature` | Los dos secretos no coinciden. Míralo en `/dev/ping-engine`. |
| El informe se queda en «generando» | El worker está caído o sin broker: `logs worker`. Hay un sondeo horario que lo recupera solo. |
| `403 not_owner` | Estás mirando el proyecto de otro usuario. Es lo esperado. |
| `404` en las rutas REST | Faltan los enlaces permanentes: `wp rewrite flush --hard`. |
| `422 validation_error` | El formulario manda un campo mal. La respuesta dice cuál. |
| Docker sin memoria | El compose de desarrollo pide ~4 GB. Cierra otros stacks. |

---

## Los tests, sin Docker

```bash
cd engine
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q     # 222 tests en segundos
```

Corren sin base de datos porque los repositorios son `Protocol` y hay
implementaciones en memoria. `tests/test_architecture.py` recorre el AST del
dominio y falla si alguien importa SQLAlchemy dentro de `domain/`.

---

## Antes de tocar producción

```bash
docker compose exec api powergis check-config
```

Se niega a arrancar si `HMAC_SECRET` sigue siendo el de desarrollo, si `DEBUG`
está activo o si falta la clave interna.

Y lo más importante de todo:

```php
// wp-config.php de producción — NUNCA con esto puesto:
define( 'POWERGIS_DEV_MODE', true );
```

El simulador de pago desbloquea informes de pago sin pasar por Stripe. En
desarrollo es cómodo; en producción es regalar el producto.
