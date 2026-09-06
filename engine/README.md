# PowerGIS · motor

Núcleo de cálculo. Ver el `README.md` de la raíz para el contexto completo.

## Arquitectura hexagonal, verificada

```
domain/       ← solo stdlib. Ni SQLAlchemy, ni FastAPI, ni httpx.
application/  ← casos de uso; orquesta puertos
adapters/     ← implementaciones: PostGIS, INE, AEMET, OSM, LLM, Stripe, WP
api/ workers/ ← entradas: HTTP y colas
```

`tests/test_architecture.py` recorre el AST de cada fichero de `domain/` y falla
si aparece un import prohibido. Es la razón práctica de que los 199 tests corran
en segundos sin levantar nada.

## Añadir un indicador nuevo

1. Una entrada en `domain/indicators.py` (código, sección, unidad, dirección,
   tier, dimensión).
2. Añadir su código a `PROVIDES` del colector que lo sepa cargar.
3. Ya está: aparece en su sección, en su tabla, en GeoLens y —si tiene
   `dimension`— en el PlaceRank.

No hay que tocar las secciones. `make coverage-report` lista los indicadores del
catálogo que aún no tienen colector.

## Añadir una sección nueva

```python
@register
class MiSeccion(SectionBuilder):
    section = Section.LO_QUE_SEA
    title = "…"
    tier = Tier.AVANZADO

    def subsections(self, ctx):
        return [Subsection(id="…", title="…",
                           kpis=[kpi_from(ctx, "codigo")],
                           tables=[build_table(ctx, "id", "título", codes)])]
```

El registro es automático; el orden de import en `sections/__init__.py` fija el
orden de presentación.

## Mapear una tabla del INE

```bash
powergis ine-discover 56934
```

Devuelve las variables de filtrado, sus valores y series de ejemplo. Con eso se
escribe el `TableSpec`. **No adivines los IDs**: el INE renumera al republicar,
y por eso son sobreescribibles por entorno (`INE_TABLE_<CODIGO>`).
