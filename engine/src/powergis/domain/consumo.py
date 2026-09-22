"""Gasto, frecuencia y ticket en el sector del cliente.

Es el único modelo del motor que depende del NEGOCIO y no sólo de la zona: el
mismo municipio gasta 280 € al mes en restaurantes y 150 € en «genérico».
Por eso no puede calcularse una vez en la carga y guardarse sin más: la carga
no sabe qué sector tiene el proyecto que va a leerlo.

Hasta ahora se guardaba calculado con el sector «genérico», y el informe de un
restaurante enseñaba el gasto de un negocio cualquiera. Ahora vive aquí, en
dominio, y lo usan las dos puntas:

* el colector de derivados, para dejar en el almacén un valor de referencia;
* el contexto del informe, que lo RECALCULA con el sector del proyecto antes
  de puntuar nada. Una sola fórmula, dos llamadas: si viviera en dos sitios,
  acabaría dando dos resultados.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Fact

MODELADO = "estimación modelada · elaboración propia"

#: Fracción de la renta disponible que un hogar destina al sector. Semilla de
#: la Encuesta de Presupuestos Familiares del INE (grupos COICOP).
SECTOR_COICOP: dict[str, float] = {
    "restauracion": 0.093,
    "cafeteria": 0.041,
    "alimentacion": 0.142,
    "retail": 0.052,
    "salud": 0.035,
    "belleza": 0.021,
    "fitness": 0.018,
    "servicios": 0.048,
    "generico": 0.050,
}

#: Visitas por hogar y semana.
SECTOR_FREQUENCY: dict[str, float] = {
    "restauracion": 1.6, "cafeteria": 3.2, "alimentacion": 3.8, "retail": 0.6,
    "salud": 0.3, "belleza": 0.4, "fitness": 2.1, "servicios": 0.5, "generico": 1.0,
}

SEMANAS_POR_MES = 4.33

#: Indicadores que dependen del sector. Ninguno más puede depender de él.
DEPENDEN_DEL_SECTOR = ("eco.sector_spend", "eco.consumer.frequency", "eco.consumer.ticket")


def sector_normalizado(sector: str | None) -> str:
    clave = (sector or "").strip().lower()
    return clave if clave in SECTOR_COICOP else "generico"


def consumo_del_sector(disponible_mensual: float | None, sector: str | None) -> dict[str, float]:
    """Gasto mensual, visitas semanales y ticket por visita en el sector.

    Sin renta disponible no hay nada: no se inventa un gasto sobre un hueco.
    """
    if disponible_mensual is None:
        return {}
    clave = sector_normalizado(sector)
    gasto = disponible_mensual * SECTOR_COICOP[clave]
    frecuencia = SECTOR_FREQUENCY[clave]
    out = {"eco.sector_spend": gasto, "eco.consumer.frequency": frecuencia}
    if gasto and frecuencia:
        out["eco.consumer.ticket"] = gasto / (frecuencia * SEMANAS_POR_MES)
    return out


def con_el_sector_del_proyecto(facts: Iterable[Fact], sector: str | None) -> list[Fact]:
    """Sustituye gasto, frecuencia y ticket por los del sector del proyecto.

    El almacén los guarda calculados con un sector de referencia. Aquí se tiran
    y se recalculan desde la renta disponible de cada zona —que sí es de la
    zona y no del negocio—, con su mismo periodo.
    """
    out: list[Fact] = []
    for f in facts:
        if f.indicator in DEPENDEN_DEL_SECTOR:
            continue
        out.append(f)
        if f.indicator == "eco.disposable.monthly" and not f.segment:
            for code, value in consumo_del_sector(f.value, sector).items():
                out.append(Fact(
                    geo_id=f.geo_id, indicator=code, period=f.period, value=value,
                    segment={}, source_ref=MODELADO, ingested_at=f.ingested_at,
                ))
    return out
