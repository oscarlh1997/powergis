"""CLI de operación.

    powergis init-db                        crea extensiones y tablas
    powergis sync-catalog                   vuelca el catálogo a dim_indicator
    powergis seed [--demo]                  geografías (+ datos de ejemplo)
    powergis ingest ine --level municipio   ingesta manual
    powergis derive                         recalcula indicadores derivados
    powergis ine-discover 56934             inspecciona una tabla del INE
    powergis coverage                       indicadores sin colector
    powergis build <uuid>                   construye un informe a mano
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import typer

from .config import get_settings
from .logging_setup import setup_logging

app = typer.Typer(help="PowerGIS · motor de informes de geomarketing", no_args_is_help=True)
log = logging.getLogger("powergis.cli")

SEED_DIR = Path(__file__).parent / "seed"


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    cfg = get_settings()
    setup_logging("DEBUG" if verbose else cfg.log_level, as_json=False)


# --------------------------------------------------------------------------- #


@app.command("init-db")
def init_db() -> None:
    """Crea extensiones PostGIS/pg_trgm y todas las tablas."""
    from sqlalchemy import text

    from .adapters.db.orm import Base
    from .adapters.db.session import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        for ext in ("postgis", "pg_trgm"):
            conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
        Base.metadata.create_all(conn)
    typer.secho("Base de datos preparada", fg=typer.colors.GREEN)


@app.command("sync-catalog")
def sync_catalog() -> None:
    """El catálogo del código es la fuente de verdad; esto lo vuelca a la BD."""
    from .adapters.db.session import uow_factory
    from .domain import indicators as catalog_mod

    with uow_factory() as uow:
        written = uow.indicators.upsert_many(catalog_mod.CATALOG)
        uow.commit()
    typer.secho(f"{written} indicadores sincronizados", fg=typer.colors.GREEN)


@app.command()
def seed(
    demo: bool = typer.Option(False, "--demo", help="Añade hechos de ejemplo para arrancar sin INE"),
    path: str | None = typer.Option(None, help="Fichero de geografías (JSON)"),
) -> None:
    """Carga geografías, perfiles de sector y (opcional) datos de demostración."""
    result = load_geographies(path)
    typer.secho(f"{result['geos']} geografías cargadas", fg=typer.colors.GREEN)

    load_sector_profiles()
    typer.secho("Perfiles de sector cargados", fg=typer.colors.GREEN)

    sync_catalog()

    if demo:
        count = load_demo_facts()
        typer.secho(f"{count} hechos de demostración cargados", fg=typer.colors.YELLOW)
        typer.secho(
            "AVISO: los datos --demo son SINTÉTICOS. No los publiques como informe real.",
            fg=typer.colors.RED, bold=True,
        )


@app.command()
def ingest(
    collector: str,
    level: str = "municipio",
    parent: str | None = None,
    indicators: str | None = typer.Option(None, help="Códigos separados por coma"),
    period: str | None = None,
) -> None:
    """Ingesta manual, en el proceso actual (sin cola)."""
    from .adapters.collectors.registry import build_registry
    from .adapters.db.session import uow_factory
    from .application.ingest import IngestData
    from .domain.enums import GeoLevel

    codes = [c.strip() for c in indicators.split(",")] if indicators else []
    with uow_factory() as uow:
        registry = build_registry(session=uow.session)
        service = IngestData(uow_factory, registry)
        report = service.by_collector(
            collector, codes, GeoLevel(level), parent,
            date.fromisoformat(period) if period else None,
        )
    typer.echo(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))


@app.command()
def derive(level: str = "municipio", parent: str | None = None) -> None:
    """Recalcula los indicadores derivados."""
    from .adapters.db.session import uow_factory
    from .application.ingest import ComputeDerived
    from .domain.enums import GeoLevel

    written = ComputeDerived(uow_factory)(GeoLevel(level), parent)
    typer.secho(f"{written} indicadores derivados escritos", fg=typer.colors.GREEN)


@app.command("ine-discover")
def ine_discover(table_id: str) -> None:
    """Variables y valores de una tabla del INE. Úsalo ANTES de mapearla."""
    from .adapters.collectors.ine import IneCollector

    collector = IneCollector()
    typer.echo(json.dumps(collector.discover(table_id), indent=2, ensure_ascii=False))
    typer.secho("\nSeries de ejemplo:", bold=True)
    for name in collector.sample(table_id):
        typer.echo(f"  · {name}")


@app.command("load-municipios")
def load_municipios(
    dry_run: bool = typer.Option(False, help="Descarga y comprueba, pero no escribe"),
    min_expected: int = typer.Option(7800, help="Mínimo de municipios para dar por buena la carga"),
) -> None:
    """Carga los ~8.100 municipios en `dim_geo` desde el INE.

    La semilla que trae el repositorio sólo llega a provincia. Sin este paso
    el almacén no tiene nivel municipal: la ingestión del Padrón descarta cada
    fila porque no encuentra la geografía, y los informes salen vacíos sin dar
    un solo error.

    Se ejecuta UNA vez al montar el sistema, y después sólo cuando el INE
    publica altas/bajas de municipios (un puñado al año).
    """
    from .adapters.collectors.ine import IneCollector
    from .adapters.db.session import uow_factory
    from .domain.enums import GeoLevel
    from .domain.models import Geo

    collector = IneCollector()

    variable_id = collector.municipality_variable_id()
    typer.echo(f"Variable de municipios en el INE: {variable_id}")

    rows = collector.municipalities(variable_id)
    typer.echo(f"El INE devuelve {len(rows)} municipios")

    # Un fichero truncado o una variable equivocada se parecen mucho a una
    # carga correcta si nadie mira el número.
    if len(rows) < min_expected:
        typer.secho(
            f"Sólo {len(rows)} municipios, se esperaban al menos {min_expected}. "
            "No se escribe nada: revisa la variable antes de insistir.",
            fg=typer.colors.RED, bold=True,
        )
        raise typer.Exit(1)

    with uow_factory() as uow:
        provinces = {
            g.ine_code: g.geo_id
            for g in uow.geos.by_level(GeoLevel.PROVINCIA)
        }

    if not provinces:
        typer.secho(
            "No hay provincias en dim_geo. Ejecuta `powergis seed` primero: "
            "los municipios cuelgan de ellas.",
            fg=typer.colors.RED, bold=True,
        )
        raise typer.Exit(1)

    orphans = sorted({r["province_code"] for r in rows} - set(provinces))
    if orphans:
        typer.secho(
            f"Códigos de provincia sin padre en dim_geo: {', '.join(orphans)}",
            fg=typer.colors.RED, bold=True,
        )
        raise typer.Exit(1)

    if dry_run:
        typer.secho(
            f"Comprobado: {len(rows)} municipios, todos con provincia. No se ha escrito nada.",
            fg=typer.colors.YELLOW,
        )
        return

    geos = [
        Geo(
            geo_id=0,
            level=GeoLevel.MUNICIPIO,
            ine_code=row["ine_code"],
            name=row["name"],
            parent_id=provinces[row["province_code"]],
        )
        for row in rows
    ]

    with uow_factory() as uow:
        written = uow.geos.upsert_many(geos)
        uow.commit()

    typer.secho(f"{written} municipios cargados en dim_geo", fg=typer.colors.GREEN)
    typer.echo("Siguiente paso:  powergis ine-verify  →  powergis ingest ine --level municipio")


@app.command("ine-verify")
def ine_verify(json_out: bool = False) -> None:
    """Comprueba que los IDs de tabla y los filtros del INE siguen valiendo.

    Ejecútalo en el VPS antes de la primera carga y después de cada aviso de
    republicación del INE. Sale con código 1 si algo está roto, así que sirve
    para bloquear un despliegue:

        powergis ine-verify || echo "no cargues hasta arreglar esto"
    """
    from .adapters.collectors.ine import IneCollector

    report = IneCollector().verify()

    if json_out:
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
        raise typer.Exit(1 if report["broken"] else 0)

    colours = {
        "OK": typer.colors.GREEN,
        "NO_MATCH": typer.colors.YELLOW,
        "LEVEL_MISMATCH": typer.colors.YELLOW,
        "EMPTY": typer.colors.RED,
        "UNREACHABLE": typer.colors.RED,
    }

    for row in report["results"]:
        status = row["status"]
        mark = "OK " if status == "OK" else "!! "
        typer.secho(
            f"{mark}{row['indicator']:<28} tabla {row['table']:<7}"
            f" series={row.get('series', 0):<6} coinciden={row.get('matched', 0)}",
            fg=colours.get(status, typer.colors.WHITE),
        )
        if row["detail"]:
            typer.echo(f"     → {row['detail']}")
        if status != "OK":
            for name in row.get("sample", []):
                typer.echo(f"       ej.: {name}")
        if row.get("overridden"):
            typer.echo("     (ID sobreescrito por variable de entorno)")

    typer.echo("")
    if report["broken"]:
        typer.secho(
            f"{report['broken']} de {report['checked']} comprobaciones fallan. "
            "Corrige el ID con la variable de entorno correspondiente "
            "(INE_TABLE_<INDICADOR>) o ajusta el filtro `match` antes de cargar.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(1)

    typer.secho(f"Las {report['checked']} tablas del INE responden y mapean.", fg=typer.colors.GREEN)


@app.command()
def coverage() -> None:
    """Indicadores del catálogo sin colector asignado."""
    from .adapters.collectors.registry import build_registry, coverage_report
    from .domain import indicators as catalog_mod

    registry = build_registry()
    report = coverage_report(registry)
    typer.echo(f"Catálogo: {len(catalog_mod.CATALOG)} indicadores")
    typer.echo(f"Con colector: {len(report['routed'])}")
    if report["orphans"]:
        typer.secho(f"SIN COLECTOR ({len(report['orphans'])}):", fg=typer.colors.YELLOW, bold=True)
        for code in report["orphans"]:
            typer.echo(f"  · {code}")
    else:
        typer.secho("Todos los indicadores tienen colector", fg=typer.colors.GREEN)


@app.command()
def build(project_uuid: str, tier: str = "basico") -> None:
    """Construye un informe en el proceso actual. Útil para depurar."""
    from uuid import UUID

    from .adapters.db.session import uow_factory
    from .application.build_report import BuildReport
    from .domain.enums import RunStatus, Tier
    from .domain.models import ReportRun

    cfg = get_settings()
    uid = UUID(project_uuid)
    with uow_factory() as uow:
        project = uow.projects.get(uid)
        if project is None:
            typer.secho("Proyecto no encontrado", fg=typer.colors.RED)
            raise typer.Exit(1)
        run = uow.runs.create(ReportRun(
            run_id=None, project_uuid=uid, tier=Tier(tier), status=RunStatus.QUEUED,
            engine_version=cfg.engine_version, input_hash=project.input_hash(Tier(tier)),
        ))
        uow.commit()

    if run.run_id is None:
        # No debería ocurrir tras el commit, pero si el repositorio cambiara y
        # dejara de devolver el id, esto lo dice en vez de fallar más abajo con
        # un error que no menciona la causa.
        typer.secho("La ejecución se creó sin id", fg=typer.colors.RED)
        raise typer.Exit(1)

    result = BuildReport(uow_factory, cfg.engine_version)(run.run_id)
    typer.secho(
        f"Informe v{result.version} · estado {result.run.status} · "
        f"{len(result.missing_indicators)} indicadores caducos",
        fg=typer.colors.GREEN,
    )


@app.command()
def doctor() -> None:
    """Diagnostica el motor desde dentro del contenedor.

    Existe porque las pruebas de humo escritas en bash no sirven en Windows, y
    porque desde fuera todos los fallos se parecen: «no va». Esto los separa.

        docker compose -f docker-compose.dev.yml exec api powergis doctor
    """
    ok, ko = 0, 0

    def si(msg: str) -> None:
        nonlocal ok
        ok += 1
        typer.secho(f"  ok  {msg}", fg=typer.colors.GREEN)

    def no(msg: str, pista: str = "") -> None:
        nonlocal ko
        ko += 1
        typer.secho(f"  XX  {msg}", fg=typer.colors.RED)
        if pista:
            typer.echo(f"        → {pista}")

    cfg = get_settings()
    typer.secho("\nConfiguración", bold=True)
    typer.echo(f"  entorno: {cfg.env} · debug: {cfg.debug}")
    if cfg.hmac_secret:
        si(f"HMAC_SECRET definido ({len(cfg.hmac_secret)} caracteres)")
    else:
        no("HMAC_SECRET vacío", "sin él, WordPress recibe 401 en todo")

    # -- base de datos ---------------------------------------------------- #
    typer.secho("\nBase de datos", bold=True)
    try:
        from sqlalchemy import func, select

        from .adapters.db.orm import FactRow, GeoRow, IndicatorRow
        from .adapters.db.session import uow_factory

        with uow_factory() as uow:
            geos = uow.session.scalar(select(func.count()).select_from(GeoRow)) or 0
            inds = uow.session.scalar(select(func.count()).select_from(IndicatorRow)) or 0
            facts = uow.session.scalar(select(func.count()).select_from(FactRow)) or 0
            municipios = uow.session.scalar(
                select(func.count()).select_from(GeoRow).where(GeoRow.level == "municipio")
            ) or 0

        si("PostgreSQL responde")

        if inds:
            si(f"catálogo: {inds} indicadores")
        else:
            no("catálogo vacío", "powergis sync-catalog")

        if geos:
            si(f"geografías: {geos}")
        else:
            no("dim_geo vacío", "powergis seed")

        if municipios:
            si(f"municipios: {municipios}")
        else:
            no(
                "sin municipios en dim_geo",
                "powergis load-municipios — sin esto, el formulario no puede "
                "resolver la ubicación y toda creación de proyecto falla",
            )

        if facts:
            si(f"hechos: {facts}")
        else:
            no("almacén sin datos", "powergis seed --demo (falsos) o ingest ine (reales)")

    except Exception as exc:  # el doctor nunca se cae
        no(f"PostgreSQL: {exc}", "¿está arriba el servicio `postgres`?")

    # -- redis / celery ---------------------------------------------------- #
    typer.secho("\nCola", bold=True)
    try:
        import redis

        redis.from_url(cfg.redis_url).ping()
        si("Redis responde")
    except Exception as exc:
        no(f"Redis: {exc}", "¿está arriba el servicio `redis`?")

    try:
        from .workers.celery_app import app as celery

        replies = celery.control.ping(timeout=2.0) or []
        if replies:
            si(f"worker vivo ({len(replies)}): {', '.join(k for r in replies for k in r)}")
        else:
            no(
                "ningún worker contesta",
                "el informe se encolará y no lo calculará nadie. "
                "Mira: docker compose -f docker-compose.dev.yml logs worker",
            )
    except Exception as exc:
        no(f"Celery: {exc}")

    typer.echo("")
    if ko:
        typer.secho(f"{ko} problema(s), {ok} correcto(s).", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    typer.secho(f"Las {ok} comprobaciones pasan.", fg=typer.colors.GREEN, bold=True)


@app.command()
def smoke(base_url: str = "http://localhost:8000") -> None:
    """Prueba de humo de punta a punta, en Python (sirve en Windows).

    Equivale a `scripts/smoke-test.sh`, pero sin bash ni openssl: se ejecuta
    dentro del contenedor, así que funciona igual en Windows, macOS y Linux.

        docker compose -f docker-compose.dev.yml exec api powergis smoke
    """
    import hashlib
    import hmac as hmac_mod
    import urllib.error
    import urllib.request
    from uuid import uuid4

    cfg = get_settings()
    secret = cfg.hmac_secret.encode()
    ok, ko = 0, 0

    def si(msg: str) -> None:
        nonlocal ok
        ok += 1
        typer.secho(f"  ok  {msg}", fg=typer.colors.GREEN)

    def no(msg: str) -> None:
        nonlocal ko
        ko += 1
        typer.secho(f"  XX  {msg}", fg=typer.colors.RED)

    def post(path: str, payload: dict) -> int:
        body = json.dumps(payload, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        sig = hmac_mod.new(secret, ts.encode() + b"\n" + body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            base_url + path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-PG-Timestamp": ts,
                "X-PG-Signature": sig,
                "Idempotency-Key": str(uuid4()),
            },
        )
        return urllib.request.urlopen(req, timeout=20).status

    def get(path: str, query: str, *, sign: bool = True) -> tuple[int, dict]:
        headers = {}
        if sign:
            ts = str(int(time.time()))
            canonical = f"{ts}\nGET\n{path}?{query}"
            headers = {
                "X-PG-Timestamp": ts,
                "X-PG-Signature": hmac_mod.new(
                    secret, canonical.encode(), hashlib.sha256
                ).hexdigest(),
            }
        req = urllib.request.Request(f"{base_url}{path}?{query}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    typer.secho("\nPrueba de humo", bold=True)

    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
            si(f"el motor responde ({resp.status})")
    except Exception as exc:
        typer.secho(f"  XX  el motor no responde: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    uuid = str(uuid4())
    payload = {
        "project_uuid": uuid,
        "wp_user_id": 1,
        "tier": "basico",
        "scope": {"level": "ccaa", "ine_code": "13", "children_level": "provincia"},
        "segments": {"age": ["25-34"], "sex": []},
        "business": {"sector": "restauracion"},
    }

    try:
        si(f"creación firmada aceptada ({post('/v1/reports', payload)})")
    except Exception as exc:
        no(f"la creación falló: {exc}")
        raise typer.Exit(1) from exc

    # El agujero que NO debe existir: leer un informe sin firmar.
    status, _ = get(f"/v1/reports/{uuid}", "wp_user_id=1", sign=False)
    if status in (401, 403):
        si(f"una lectura SIN firma se rechaza ({status})")
    else:
        no(f"una lectura sin firma devolvió {status} — cualquier UUID filtrado abre el informe")

    data: dict = {}
    for _ in range(20):
        time.sleep(2)
        status, data = get(f"/v1/reports/{uuid}", "wp_user_id=1")
        if status == 200:
            break

    if status != 200:
        no(f"el informe no llegó a estar listo (último estado {status})")
        typer.echo("        → casi siempre es el worker: mira sus logs")
        raise typer.Exit(1)

    si("lectura firmada correcta")

    crudo = json.dumps(data)
    if data.get("placerank"):
        no("PlaceRank viaja en un informe básico — FUGA")
    else:
        si("PlaceRank ausente del básico")

    if "eco.income.household.mean" in crudo:
        no("hay datos socioeconómicos en un informe básico — FUGA")
    else:
        si("las secciones de pago no viajan en el básico")

    typer.echo("")
    if ko:
        typer.secho(f"{ko} fallo(s), {ok} correcto(s).", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    typer.secho(f"Las {ok} comprobaciones pasan.", fg=typer.colors.GREEN, bold=True)


@app.command()
def endpoints(
    base_url: str = "http://localhost:8000",
    fixtures: str | None = typer.Option(None, help="Ruta a fixtures.json"),
    grupo: str | None = typer.Option(None, help="salud|catalogo|geografia|informes|operacion|seguridad"),
    con_red: bool = typer.Option(False, "--con-red", help="Exige también los casos que salen a internet"),
    verbose: bool = typer.Option(False, "--verbose", help="Enseña un trozo de cada respuesta"),
) -> None:
    """Dispara TODOS los endpoints con datos de prueba y comprueba la respuesta.

    Los datos viven en `scripts/fixtures.json`, editable. Aquí sólo se firma y
    se llama, en orden de dependencia: primero se crea un informe, se espera a
    que esté, y luego se prueban las rutas que lo necesitan.

        docker compose -f docker-compose.dev.yml exec api powergis endpoints
    """
    import hashlib
    import hmac as hmac_mod
    import urllib.error
    import urllib.request
    from uuid import uuid4

    cfg = get_settings()
    secret = cfg.hmac_secret.encode()
    base_url = base_url.rstrip("/")

    path = Path(fixtures) if fixtures else Path("/scripts/fixtures.json")
    if not path.exists():
        path = Path(__file__).resolve().parents[3] / "scripts" / "fixtures.json"
    if not path.exists():
        typer.secho(f"No encuentro fixtures.json (probado en {path})", fg=typer.colors.RED)
        raise typer.Exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    # `owner` cambia en cada tanda a propósito. El tier gratuito permite 3
    # informes por hora y usuario, así que repetir el mismo wp_user_id haría
    # fallar la segunda ejecución con un 429 que no es un fallo del motor.
    owner = 10_000 + int(uuid4().int % 80_000)
    uuid = str(uuid4())
    sust = {
        "{uuid}": uuid,
        "{uuid2}": str(uuid4()),
        "{uuid3}": str(uuid4()),
        "{owner}": str(owner),
    }

    def resolver(texto: str) -> str:
        for clave, valor in sust.items():
            texto = texto.replace(clave, valor)
        return texto

    ok, ko = 0, 0
    version_vista = 0   # última versión confirmada del informe principal

    def llamar(caso: dict) -> tuple[int, bytes]:
        ruta = resolver(str(caso["ruta"]))
        query = resolver(str(caso.get("query", "")))
        auth = str(caso.get("auth", ""))
        metodo = str(caso["metodo"])

        cuerpo = caso.get("cuerpo")
        raw = b""
        if cuerpo is not None:
            texto = json.dumps(cuerpo, separators=(",", ":"), ensure_ascii=False)
            raw = resolver(texto).encode()

        headers: dict[str, str] = {}
        ts = str(int(time.time()))

        if auth.startswith("firma sobre el cuerpo"):
            headers["Content-Type"] = "application/json"
            headers["X-PG-Timestamp"] = ts
            headers["X-PG-Signature"] = hmac_mod.new(
                secret, ts.encode() + b"\n" + raw, hashlib.sha256
            ).hexdigest()
            headers["Idempotency-Key"] = str(uuid4())
        elif auth.startswith("firma sobre método"):
            canonical = f"{ts}\nGET\n{ruta}?{query}" if query else f"{ts}\nGET\n{ruta}?"
            headers["X-PG-Timestamp"] = ts
            headers["X-PG-Signature"] = hmac_mod.new(
                secret, canonical.encode(), hashlib.sha256
            ).hexdigest()
        elif auth.startswith("firma con timestamp"):
            viejo = str(int(time.time()) - 3600)
            canonical = f"{viejo}\nGET\n{ruta}?{query}"
            headers["X-PG-Timestamp"] = viejo
            headers["X-PG-Signature"] = hmac_mod.new(
                secret, canonical.encode(), hashlib.sha256
            ).hexdigest()
        elif auth.startswith("firma válida de OTRO"):
            otro = b'{"project_uuid":"00000000-0000-0000-0000-000000000000"}'
            headers["Content-Type"] = "application/json"
            headers["X-PG-Timestamp"] = ts
            headers["X-PG-Signature"] = hmac_mod.new(
                secret, ts.encode() + b"\n" + otro, hashlib.sha256
            ).hexdigest()
            raw = b'{"project_uuid":"11111111-1111-1111-1111-111111111111"}'
        elif auth.startswith("firma válida"):
            canonical = f"{ts}\nGET\n{ruta}?{query}"
            headers["X-PG-Timestamp"] = ts
            headers["X-PG-Signature"] = hmac_mod.new(
                secret, canonical.encode(), hashlib.sha256
            ).hexdigest()
        elif auth.startswith("X-Internal-Key"):
            headers["X-Internal-Key"] = cfg.internal_api_key
            headers["Content-Type"] = "application/json"

        url = f"{base_url}{ruta}" + (f"?{query}" if query else "")
        req = urllib.request.Request(
            url, data=raw if metodo == "POST" else None, headers=headers, method=metodo
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()[:400]
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:400]
        except Exception as exc:
            return 0, str(exc).encode()[:400]

    grupos = [grupo] if grupo else [k for k in data if not k.startswith("_")]

    for nombre_grupo in grupos:
        casos = data.get(nombre_grupo)
        if not isinstance(casos, list):
            continue

        typer.secho(f"\n{nombre_grupo.upper()}", bold=True)

        for caso in casos:
            # Algunos casos salen a internet (el INE). Sin salida no son un
            # fallo del motor, así que se saltan salvo que se pidan.
            if caso.get("requiere_proyecto") and version_vista == 0:
                typer.secho(
                    f"  --  ...  {caso['metodo']:<5} {caso['nombre']}"
                    "  (necesita el proyecto del grupo `informes`)",
                    fg=typer.colors.YELLOW,
                )
                continue

            if caso.get("requiere_red") and not con_red:
                typer.secho(
                    f"  --  ...  {caso['metodo']:<5} {caso['nombre']}  (necesita red)",
                    fg=typer.colors.YELLOW,
                )
                continue

            esperado = caso["espera"]
            validos = esperado if isinstance(esperado, list) else [esperado]
            status, cuerpo = llamar(caso)

            # Tras crear el primer informe, esperar a que el worker lo termine.
            if caso["ruta"] == "/v1/reports" and status == 202 and "{uuid}" in str(caso.get("cuerpo", "")):
                pass

            if status in validos:
                ok += 1
                typer.secho(
                    f"  ok  {status}  {caso['metodo']:<5} {caso['nombre']}",
                    fg=typer.colors.GREEN,
                )
            else:
                ko += 1
                typer.secho(
                    f"  XX  {status}  {caso['metodo']:<5} {caso['nombre']}"
                    f"  (esperaba {esperado})",
                    fg=typer.colors.RED,
                )
                typer.echo(f"        {cuerpo.decode('utf-8', 'replace')[:200]}")

            if verbose and status in validos and cuerpo:
                typer.echo(f"        {cuerpo.decode('utf-8', 'replace')[:160]}")

            # Los 202 son asíncronos: el cálculo va a una cola y lo que viene
            # detrás lo necesita terminado. El caso lo declara con `esperar`,
            # que además dice a QUÉ nivel hay que esperar: tras un upgrade no
            # basta con que el informe exista, tiene que ser ya el avanzado.
            nivel = caso.get("esperar")
            if nivel and status == 202:
                # Se espera a que suba la VERSIÓN, no a que cambie el `tier`.
                # El upgrade marca el proyecto como avanzado en el acto y sólo
                # después encola el cálculo, así que mirar el tier da por
                # terminado algo que no ha empezado: el PlaceRank de la v2
                # todavía no existe y lo siguiente falla con un 409 que parece
                # un fallo del motor y es del reloj.
                typer.echo(f"        esperando a la versión {version_vista + 1} ({nivel})…")
                objetivo = version_vista + 1
                logrado = False

                for _ in range(30):
                    time.sleep(2)
                    ts2 = str(int(time.time()))
                    q = f"wp_user_id={owner}"
                    canonical = f"{ts2}\nGET\n/v1/reports/{uuid}?{q}"
                    req = urllib.request.Request(
                        f"{base_url}/v1/reports/{uuid}?{q}",
                        headers={
                            "X-PG-Timestamp": ts2,
                            "X-PG-Signature": hmac_mod.new(
                                secret, canonical.encode(), hashlib.sha256
                            ).hexdigest(),
                        },
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            actual = int(json.loads(resp.read()).get("version", 0))
                    except Exception:  # noqa: S112 — el error aquí es "aún no"
                        continue
                    if actual >= objetivo:
                        version_vista = actual
                        logrado = True
                        break

                if not logrado:
                    typer.secho(
                        f"        el informe no llegó a la versión {objetivo} en 60 s. "
                        "Casi siempre es el worker: o no está vivo, o tiene la "
                        "cola ocupada por una ingesta larga.",
                        fg=typer.colors.YELLOW,
                    )

    typer.echo("")
    if ko:
        typer.secho(f"{ko} fallo(s), {ok} correcto(s).", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    typer.secho(f"Los {ok} endpoints responden lo esperado.", fg=typer.colors.GREEN, bold=True)


@app.command("check-config")
def check_config() -> None:
    """Verifica que la configuración es apta para producción."""
    cfg = get_settings()
    problems = cfg.check_production_ready()
    if problems:
        for problem in problems:
            typer.secho(f"  ✗ {problem}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("Configuración correcta", fg=typer.colors.GREEN)


# --------------------------------------------------------------------------- #
# Cargas
# --------------------------------------------------------------------------- #


def load_geographies(path: str | None = None) -> dict[str, Any]:
    """Carga `dim_geo` respetando la jerarquía (padres antes que hijos)."""
    from .adapters.db.session import uow_factory
    from .domain.enums import GeoLevel
    from .domain.models import Geo

    source = Path(path) if path else SEED_DIR / "geographies.json"
    if not source.exists():
        raise FileNotFoundError(
            f"No existe {source}. Genera el fichero con las geometrías del IGN "
            "o pasa --path."
        )

    data = json.loads(source.read_text(encoding="utf-8"))
    order = [GeoLevel.PAIS, GeoLevel.CCAA, GeoLevel.PROVINCIA,
             GeoLevel.MUNICIPIO, GeoLevel.DISTRITO, GeoLevel.SECCION]
    written = 0

    with uow_factory() as uow:
        ids: dict[tuple[str, str], int] = {}
        for level in order:
            rows = [r for r in data if r.get("level") == str(level)]
            if not rows:
                continue
            geos = [
                Geo(
                    geo_id=0,
                    level=level,
                    ine_code=str(row["ine_code"]),
                    name=row["name"],
                    parent_id=ids.get((row.get("parent_level", ""), str(row.get("parent_code", "")))),
                    population=row.get("population"),
                    area_km2=row.get("area_km2"),
                )
                for row in rows
            ]
            uow.geos.upsert_many(geos)
            uow.commit()
            for row in rows:
                stored = uow.geos.get(level, str(row["ine_code"]))
                if stored:
                    ids[(str(level), str(row["ine_code"]))] = stored.geo_id
            written += len(geos)
        uow.commit()

    return {"geos": written, "source": str(source)}


def load_sector_profiles() -> int:
    """Vuelca los perfiles integrados a `sector_profile` / `sector_dimension`."""
    from .adapters.db.session import uow_factory
    from .domain.placerank import BUILTIN_PROFILES

    with uow_factory() as uow:
        for profile in BUILTIN_PROFILES.values():
            uow.sector_profiles.save(profile)
        uow.commit()
    return len(BUILTIN_PROFILES)


def load_demo_facts() -> int:
    """Hechos SINTÉTICOS para poder ver el sistema funcionando sin red.

    Deterministas (semilla fija) para que los tests sean reproducibles.
    """
    import random

    from .adapters.db.session import uow_factory
    from .domain import indicators as catalog_mod
    from .domain.enums import GeoLevel
    from .domain.models import Fact

    random.seed(42)
    period = date(2024, 1, 1)

    with uow_factory() as uow:
        root = uow.geos.get(GeoLevel.PAIS, "ES")
        if root is None:
            raise RuntimeError("Carga primero las geografías (`powergis seed`)")
        geos = (
            uow.geos.descendants(root.geo_id, GeoLevel.PROVINCIA)
            + uow.geos.descendants(root.geo_id, GeoLevel.CCAA)
            + [root]
        )

        facts: list[Fact] = []
        for geo in geos:
            population = geo.population or random.randint(50_000, 3_000_000)
            base = {
                "dem.pop.total": population,
                "dem.age.0_15": population * random.uniform(0.12, 0.18),
                "dem.age.16_64": population * random.uniform(0.60, 0.68),
                "dem.age.65p": population * random.uniform(0.16, 0.26),
                "dem.sex.women": population * random.uniform(0.49, 0.52),
                "dem.age.mean": random.uniform(38.0, 50.0),
                "dem.edu.university_pct": random.uniform(12.0, 38.0),
                "dem.edu.secondary_pct": random.uniform(20.0, 40.0),
                "dem.edu.primary_pct": random.uniform(15.0, 35.0),
                "dem.edu.none_pct": random.uniform(1.0, 8.0),
                "dem.nat.foreign_pct": random.uniform(2.0, 22.0),
                "dem.household.size": random.uniform(2.1, 2.9),
                "dem.household.single_pct": random.uniform(18.0, 32.0),
                "eco.income.household.mean": random.uniform(22_000, 48_000),
                "eco.income.household.median": random.uniform(19_000, 42_000),
                "eco.gini": random.uniform(0.26, 0.38),
                "eco.nse.risk_pct": random.uniform(8.0, 32.0),
                "cli.temp.annual": random.uniform(11.0, 19.0),
                "cli.rain.days": random.uniform(45, 130),
                "cli.sun.days": random.uniform(90, 210),
                "cmp.count": random.randint(20, 900),
            }
            base["dem.sex.men"] = population - base["dem.sex.women"]
            for code, value in base.items():
                if code not in catalog_mod.BY_CODE:
                    continue
                facts.append(Fact(
                    geo_id=geo.geo_id, indicator=code, period=period,
                    value=float(value), segment={}, source_ref="DEMO-SINTÉTICO",
                ))
            # Segmento de edad, para que la tabla avanzada tenga contenido.
            for age in ("18-35", "36-55", "65+"):
                facts.append(Fact(
                    geo_id=geo.geo_id, indicator="dem.pop.segment", period=period,
                    value=population * random.uniform(0.12, 0.30),
                    segment={"age": age}, source_ref="DEMO-SINTÉTICO",
                ))
            facts.append(Fact(
                geo_id=geo.geo_id, indicator="dem.pop.segment", period=period,
                value=population * random.uniform(0.20, 0.45),
                segment={}, source_ref="DEMO-SINTÉTICO",
            ))

        written = uow.facts.upsert_many(facts)
        uow.commit()

    from .application.ingest import ComputeDerived

    ComputeDerived(uow_factory)(GeoLevel.PROVINCIA)
    return written


@app.command()
def firmar(
    cuerpo: str = typer.Option(
        "",
        "--cuerpo",
        "-c",
        help="Fichero con el cuerpo JSON a firmar (para POST).",
    ),
    get: str = typer.Option(
        "",
        "--get",
        "-g",
        help="Ruta a firmar para un GET, p.ej. /v1/reports/<uuid>",
    ),
    query: str = typer.Option("", "--query", "-q", help="Query del GET, sin el '?'."),
) -> None:
    """Calcula las cabeceras de firma para pegarlas en Swagger.

    Existe porque firmar a mano en Windows es donde más se falla: la firma se
    calcula sobre los BYTES EXACTOS del cuerpo, y entre las comillas de cmd,
    los saltos de línea de Windows y un espacio de más al copiar, es fácil
    firmar algo distinto de lo que se acaba enviando. Leyendo el cuerpo de un
    fichero, eso no puede pasar.

        # POST — el cuerpo va en un fichero de ./scripts
        powergis firmar --cuerpo /scripts/cuerpo.json

        # GET — se firma «GET\\nruta?query», no el cuerpo
        powergis firmar --get /v1/reports/<uuid> --query "wp_user_id=1"

    Recuerda que la ventana es de 300 s: firma y envía seguido.
    """
    from .api.security import HEADER_SIGNATURE, HEADER_TIMESTAMP, sign, sign_get

    cfg = get_settings()

    if get:
        # Se admite la «Request URL» entera que enseña Swagger. Es el camino
        # recomendado: en un GET el ORDEN de los parámetros forma parte de la
        # firma, y copiarlos a mano es donde se falla.
        if get.startswith(("http://", "https://")):
            from urllib.parse import urlsplit

            partes = urlsplit(get)
            ruta, consulta = partes.path, partes.query
        else:
            ruta, consulta = get, query.lstrip("?")

        if not ruta.startswith("/"):
            typer.secho(
                "La ruta tiene que empezar por '/', o pega la Request URL entera.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        firmado = sign_get(ruta, consulta)
        destino = ruta + (f"?{consulta}" if consulta else "")
        cuerpo_txt = None
    else:
        if not cuerpo:
            typer.secho("Indica --cuerpo <fichero> o --get <ruta>", fg=typer.colors.RED)
            raise typer.Exit(1)
        fichero = Path(cuerpo)
        if not fichero.is_file():
            typer.secho(f"No encuentro {fichero}", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Se leen BYTES, no texto: reescribir el fichero con otro final de
        # línea cambiaría la firma sin que se note al mirarlo.
        crudo = fichero.read_bytes()

        try:
            json.loads(crudo)
        except json.JSONDecodeError as exc:
            typer.secho(f"El fichero no es JSON válido: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        if b"\r\n" in crudo:
            typer.secho(
                "AVISO: el fichero tiene saltos de línea de Windows (CRLF).\n"
                "       Se firma tal cual, así que Swagger tiene que recibir "
                "EXACTAMENTE\n       estos mismos bytes. Si al pegarlo el editor "
                "los convierte, la\n       firma no casará. Guárdalo con saltos "
                "Unix (LF) para evitarlo.",
                fg=typer.colors.YELLOW,
            )

        firmado = sign(crudo)
        destino = None
        cuerpo_txt = crudo.decode("utf-8")

    typer.secho("\nCabeceras — pégalas en «Authorize» o en el curl", bold=True)
    typer.echo(f"  {HEADER_TIMESTAMP}: {firmado.timestamp}")
    typer.echo(f"  {HEADER_SIGNATURE}: {firmado.signature}")

    if destino:
        typer.secho("\nSe ha firmado esta cadena canónica", bold=True)
        typer.echo(f"  GET\\n{destino}")
    else:
        typer.secho("\nCuerpo firmado — pega EXACTAMENTE esto", bold=True)
        typer.echo(cuerpo_txt)

    caduca = int(firmado.timestamp) + cfg.hmac_window_seconds
    restante = caduca - int(time.time())
    typer.secho(
        f"\nVálida durante {restante} s. Pasado ese punto: 401 fuera de ventana.",
        fg=typer.colors.YELLOW,
    )


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
