# PowerGIS — motor de informes de geomarketing

> **El informe no es un documento que se genera. Es una consulta contra un
> almacén de indicadores que ya está precalculado.**

Esa frase es toda la arquitectura. Las «tablas avanzadas» del final de cada
sección —todas las provincias de una comunidad con sus totales por rango de
edad— **no son datos del proyecto del usuario**: son un recorte de una tabla de
hechos idéntica para todos los que pidan ese mismo ámbito. El proyecto solo
aporta *qué recorte*, *qué segmentos* y *qué pesos*.

Consecuencias, y son las que sostienen el negocio:

| | Generar informes | Almacén + consulta |
|---|---|---|
| Informe básico | 2–5 min | **< 3 s** |
| Coste marginal del gratuito | real | **≈ 0** |
| Corregir un KPI | regenerar N informes | un `UPDATE` |
| GeoLens y PlaceRank | features nuevas y caras | **dos vistas más** |
| Upgrade básico → avanzado | recalcular todo | **añadir lo que falta** |

---

## Qué hay aquí

```
powergis/
├── engine/                    Motor Python — FastAPI + Celery + PostGIS
│   ├── src/powergis/
│   │   ├── domain/            Núcleo: sin SQLAlchemy, sin FastAPI, sin red
│   │   ├── application/       Casos de uso
│   │   ├── adapters/          BD, colectores, LLM, exportadores, WordPress
│   │   ├── api/               FastAPI + firma HMAC
│   │   └── workers/           Celery: informes, ETL, narrativa
│   ├── alembic/               Migraciones
│   └── tests/                 222 tests, sin Docker, en segundos
├── wordpress/
│   └── powergis-connector/    Plugin: CPT, saas/v1 endurecido, Stripe, render
├── infra/                     PostgreSQL, nginx (teselas), backup
├── docker-compose.yml         Stack de producción (VPS KVM 4)
├── docker-compose.dev.yml     Entorno de PRUEBAS con WordPress incluido
├── scripts/                   setup de WordPress · prueba de humo
├── GUIA-DE-PRUEBAS.md         paso a paso para probarlo entero
├── docs/                      PDF de integración front ↔ back (+ su generador)
└── Makefile
```

**La frontera está verificada en CI**, no solo documentada: `tests/test_architecture.py`
falla el día que alguien importe SQLAlchemy dentro de `domain/`.

---

## Documentación

* **[docs/PowerGIS-Integracion-Front-Back.pdf](docs/PowerGIS-Integracion-Front-Back.pdf)** —
  20 páginas: inventario real de powergis.es, shortcodes, el formulario paso a
  paso, el mapa de campos formulario → motor, endpoints, seguridad y checklist
  de puesta en marcha.
* **[GUIA-DE-PRUEBAS.md](GUIA-DE-PRUEBAS.md)** — cómo levantarlo todo y probarlo.

---

## Probarlo entero, con WordPress incluido

```bash
make dev
```

Levanta motor + PostGIS + Redis + worker + **WordPress**, migra, carga datos de
demostración, instala WordPress y crea las páginas del flujo. Al terminar:

```
WordPress  http://localhost:8080   (admin/admin · cliente/cliente)
Motor      http://localhost:8000/docs
Empieza en http://localhost:8080/nuevo-proyecto/
```

El paso a paso completo —incluido cómo comprobar tú mismo que el informe
gratuito no filtra datos de pago— está en **[GUIA-DE-PRUEBAS.md](GUIA-DE-PRUEBAS.md)**.

---

## Arranque rápido del motor solo (producción)

```bash
cp .env.example .env
# Genera los secretos:
echo "HMAC_SECRET=$(openssl rand -hex 32)"       >> .env
echo "INTERNAL_API_KEY=$(openssl rand -hex 24)"  >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >> .env

make up            # Postgres+PostGIS, Redis, API, 3 workers, beat, n8n, teselas
make demo          # migraciones + catálogo + geografías + datos SINTÉTICOS
```

`make demo` carga datos **sintéticos** para que veas el sistema funcionando sin
esperar al INE. No publiques un informe con ellos.

Sin Docker, para desarrollar el dominio:

```bash
make setup && make test     # 222 tests, sin base de datos
make smoke                  # prueba de humo: firma HMAC de punta a punta
```

---

## Flujo de un informe

```
1. Usuario envía el formulario en WordPress
2. saas/v1/projects/create → valida, crea el CPT en draft, firma y encola
3. POST {MOTOR}/v1/reports    (HMAC-SHA256 + Idempotency-Key)
4. FastAPI valida el esquema, persiste report_run y encola en Celery
5. El worker mira qué indicadores del ámbito ya están frescos
   · frescos → CERO llamadas externas        ← aquí está todo el ahorro
   · caducos → encola ETL y sigue con lo que hay
6. Compone secciones → KPIs → tablas → top/bottom 3 → PlaceRank
7. Guarda report_snapshot (JSONB versionado)
8. Callback firmado a WordPress
9. WordPress publica el CPT, asigna report_tier / sector / location, purga caché
10. El front pide el payload y renderiza tablas, gráficos y mapa
```

El paso 5 es el que hace que el segundo usuario que pida «Comunidad de Madrid,
18-35» no toque el INE.

---

## Básico → Avanzado

Ni generar todo y ocultarlo, ni hacer dos llamadas independientes:

```
run #1  perfil BASIC     → [demografía]                → snapshot v1, tier=basico
   ↓  [webhook de Stripe]
run #2  perfil ADVANCED  → reutiliza demografía        → snapshot v2, tier=avanzado
                         + socioeconómico, competencia,
                           clima, tráfico, GeoLens,
                           PlaceRank, narrativa IA
```

**Por qué no «generar todo y ocultar»:** pagas el coste completo por cada usuario
gratuito; el dato oculto se lee en view-source y en la REST API, así que estás
publicando el producto de pago; y si el usuario paga tres meses después le
entregas datos de hace tres meses.

**Por qué no «dos llamadas»:** recalculas la demografía que ya tenías.

Las secciones bloqueadas viajan como `{"available": false}` **sin datos dentro**.
Hay un test que lo comprueba: `test_ninguna_seccion_bloqueada_filtra_datos`.

---

## Fuentes de datos

| Sección | Fuente | Granularidad | Refresco |
|---|---|---|---|
| Demografía | INE Padrón continuo / Censo (Tempus3) | Municipio | Mensual |
| Socioeconómico | **INE ADRH** | Municipio, distrito, **sección censal** | Mensual |
| Competencia y anclas | OSM (extracto Geofabrik en PostGIS propio) | Municipio | Semanal |
| Saturación | Catastro + INE/DIRCE | Municipio / provincia | Semestral |
| Clima | AEMET OpenData (normales 1991-2020) | Estación → municipio | Anual |
| Tráfico | OSM — **índice relativo, no aforo** | Municipio | Semanal |

Tres correcciones que el código implementa, no solo documenta:

* **Overpass no da datos económicos**, da POIs. La renta sale del **ADRH del INE**.
* La instancia pública de Overpass (~10.000 consultas/día) no aguanta carga
  comercial: en producción se usa el extracto de España en PostGIS propio
  (`USE_LOCAL_OSM=true`).
* El ADRH **no publica** en municipios pequeños por secreto estadístico. Un hueco
  se guarda como `NULL` y se muestra como «no disponible». Pintar un cero ahí es
  vender un análisis falso, y hay tests que lo impiden.

---

## Seguridad

| | |
|---|---|
| **HMAC bidireccional** | Firma sobre `timestamp + "\n" + cuerpo_crudo`, ventana de 300 s, `hash_equals` / `hmac.compare_digest`. Misma implementación en Python y en PHP; si cambias una, cambia la otra. |
| **Idempotencia** | `Idempotency-Key` al crear informes y `event.id` de Stripe al cobrar. Doble submit no duplica trabajo. |
| **Lecturas firmadas** | `GET /v1/reports/{uuid}` exige HMAC sobre `GET\\nruta?query`. Sin ello, `wp_user_id` lo pondría quien llama y un UUID filtrado abriría el informe de pago de otro. |
| **Propiedad** | Segunda barrera: el proyecto tiene que ser del usuario que lo pide. |
| **CPT privado** | El `project` pasa a `public => false`. Con el anterior `public => true`, `/wp-json/wp/v2/project` listaba los proyectos de todos a cualquiera. |
| **`permission_callback` real** | Nonce + sesión + propiedad en cada ruta de `saas/v1`. CI falla si aparece un `__return_true` fuera del webhook de Stripe. |
| **Secretos** | Variables de entorno del VPS y `wp-config.php`. Nunca en la tabla `options`. `powergis check-config` impide arrancar en producción con los valores por defecto. |
| **Stripe** | El desbloqueo lo hace el **webhook**, nunca `success_url` — esa URL la puede visitar cualquiera sin pagar. |

---

## Riesgos legales que hay que mirar antes de construir

1. **Valoraciones y reseñas de competidores.** Solo salen de Google Places, y los
   términos de Google Maps Platform restringen almacenar y reutilizar ese
   contenido fuera de un mapa de Google. Este código **no las calcula**: la
   sección de competencia se construye solo con OSM. Consúltalo con un abogado
   antes de añadirlas — no soy abogado y esto merece asesoramiento profesional.
2. **OSM es ODbL.** Atribución obligatoria en mapa e informe (ya está en los pies
   de tabla y en la atribución del mapa). El exportador saca **agregados**, no el
   listado de POIs: redistribuir la base de datos derivada activaría la cláusula
   de compartir-igual.
3. **INE y AEMET:** reutilización permitida citando la fuente. Está en el anexo
   de metodología y en cada pie de tabla.
4. **RGPD:** los indicadores son agregados; el riesgo está en los datos del
   formulario. `delete-account` tiene que borrar de verdad, también del motor.

---

## Instalar el plugin de WordPress

1. Copia `wordpress/powergis-connector/` a `wp-content/plugins/` y actívalo.
2. En `wp-config.php`:

```php
define( 'POWERGIS_ENGINE_URL',            'https://motor.powergis.es' );
define( 'POWERGIS_HMAC_SECRET',           '…el MISMO valor que HMAC_SECRET del motor…' );
define( 'POWERGIS_STRIPE_SECRET',         'sk_live_…' );
define( 'POWERGIS_STRIPE_WEBHOOK_SECRET', 'whsec_…' );
define( 'POWERGIS_STRIPE_PRICE_ID',       'price_…' );
```

3. En el panel de Stripe, apunta el webhook a
   `https://powergis.es/wp-json/saas/v1/stripe/webhook` con los eventos
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `charge.refunded` y
   `charge.dispute.created`.
4. Comprueba todo en **Proyectos → Diagnóstico**.
5. Shortcodes: `[powergis_report]` (se inyecta solo en el CPT) y
   `[powergis_my_projects]`.

El informe se renderiza desde el payload JSON con ECharts, MapLibre GL y tablas
propias. **Graphina queda fuera del informe**: guarda los datos de cada gráfico
dentro del widget de Elementor, y con 30-60 gráficos por informe habría que
escribir JSON de Elementor por programa.

---

## Comandos

```bash
make help              # todas las tareas
make test              # 199 tests, sin Docker
make lint              # ruff + mypy
make bootstrap         # migraciones + catálogo + geografías
make ingest-ine        # carga demográfica real (va a la cola etl)
make coverage-report   # indicadores del catálogo sin colector
make check-config      # ¿la configuración es apta para producción?
make backup            # copia cifrada
make restore-test      # PRUEBA la restauración — hazlo al menos una vez
```

```bash
powergis ine-discover 56934    # variables de una tabla del INE antes de mapearla
```

Los IDs de tabla del INE se sobreescriben por entorno
(`INE_TABLE_DEM_POP_TOTAL=2879`): el INE los renumera al republicar una
operación y eso no debería costar un despliegue.

---

## Infraestructura

Pensado para un **Hostinger KVM 4** (4 vCPU / 16 GB / 200 GB NVMe). WordPress se
queda fuera del VPS: mezclar su ciclo de vida con el del motor significa que el
día que un worker se coma la RAM se cae la tienda.

Detalles que duelen si se olvidan y que están resueltos en `docker-compose.yml`:

* **Colas separadas** — una carga del INE no puede dejar a un cliente esperando.
* **Límites de memoria por servicio** — sin ellos, una ingesta con pandas
  dispara el OOM killer y se lleva PostgreSQL por delante.
* **PostgreSQL afinado** para 16 GB (`shared_buffers=4GB`, `random_page_cost=1.1`
  porque es NVMe, no disco giratorio).
* **Postgres y Redis sin puertos publicados.** Solo red interna de Docker.
* **Backup cifrado a almacenamiento externo** + `make restore-test`. Los
  snapshots del VPS no son backup de base de datos.

---

## Estado por fases

| Fase | Estado |
|---|---|
| 0 · Cimientos | Docker, PostGIS, Alembic, CI, backups |
| 1 · Almacén demográfico | Catálogo (96 indicadores), colectores INE, ETL programado |
| 2 · Motor de informes | API, payload, secciones, tablas, KPIs |
| 3 · Monetización | Stripe Checkout, webhook, upgrade incremental |
| 4 · Secciones avanzadas | ADRH, OSM, AEMET, Catastro/DIRCE, tráfico |
| 5 · GeoLens | Capas por catálogo, PMTiles, MapLibre |
| 6 · PlaceRank | Pesos por sector en BD, normalización por percentiles |
| 7 · IA narrativa | Salida validada + verificación de cifras + plantilla de respaldo |
| 8 · Exportaciones | Excel, PDF (WeasyPrint), PPTX |

**Verificado ejecutándolo**, no razonando sobre el código: migración up y down
contra PostGIS 3.4 real, 96 indicadores y 72 geografías cargadas, 3 ejecuciones
completadas con Redis y Celery reales, flujo básico → avanzado por HTTP con
firma, 403 al leer el informe de otro, y un XLSX de 18 KB válido. La firma HMAC
da el mismo resultado en bash, Python y PHP.

Lo que queda por rellenar con trabajo de campo, no de arquitectura: verificar los
IDs de tabla del INE con `powergis ine-discover`, cargar el extracto de OSM y las
geometrías del IGN, y generar las teselas.

---

## Fuentes

INE (Tempus3, ADRH) · OpenStreetMap © contribuidores, ODbL · AEMET OpenData ·
Dirección General del Catastro · INE/DIRCE
