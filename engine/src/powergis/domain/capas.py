"""Capas territoriales que el cliente enciende o apaga en el formulario.

El formulario `[crear_proyecto_v6]` trae, desde octubre de 2026, un
interruptor por cada serie complementaria («Incluir resultados electorales»,
«Incluir nivel turístico»…) y los manda en `datos_territoriales` como
`incluir` / `excluir`. Aquí está la lista cerrada de esas capas, con los
mismos nombres que usa el formulario para que el mapeo sea evidente.

Una capa apagada desaparece del informe entero, no sólo de su sección: sus
indicadores no se piden al almacén, no salen en GeoLens ni en el glosario, y
la sección que se quede sin ninguna capa encendida no se pinta (ni siquiera
como bloqueada en el informe básico). Por defecto todas están encendidas: un
proyecto creado antes de que existieran los interruptores sale completo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .enums import Section


@dataclass(frozen=True, slots=True)
class Capa:
    key: str
    label: str
    section: Section


#: Las capas, en el orden del formulario.
CAPAS: tuple[Capa, ...] = (
    Capa("votaciones_politicas", "Resultados electorales", Section.CONTEXTO),
    Capa("traslados_entre_provincias", "Traslados entre provincias", Section.CONTEXTO),
    Capa("nivel_turistico", "Nivel turístico", Section.TURISMO),
    Capa("compra_venta_inmuebles", "Compraventa de viviendas", Section.INMOBILIARIO),
    Capa("viviendas_vacias_principales", "Viviendas vacías y principales", Section.INMOBILIARIO),
    Capa("precio_vivienda_historico", "Precio de la vivienda e histórico", Section.INMOBILIARIO),
    # Los locales del Catastro viven en «Competencia» (saturación comercial):
    # la capa los quita de allí.
    Capa("catastro_locales_cartografia", "Catastro: locales y cartografía", Section.COMPETENCIA),
    Capa("alquiler_vivienda_proxy", "Alquiler de vivienda", Section.INMOBILIARIO),
)

POR_CLAVE: dict[str, Capa] = {c.key: c for c in CAPAS}
CLAVES: tuple[str, ...] = tuple(c.key for c in CAPAS)

#: Indicador → capa a la que pertenece. Lo que no está aquí sale siempre.
INDICADOR_CAPA: dict[str, str] = {
    # Resultados electorales (Ministerio del Interior, Infoelectoral)
    "pol.turnout_pct": "votaciones_politicas",
    "pol.winner_share_pct": "votaciones_politicas",
    "pol.effective_parties": "votaciones_politicas",
    # Traslados entre provincias (INE, Estadística de Migraciones y Cambios de Residencia)
    "mov.interprov.in_rate": "traslados_entre_provincias",
    "mov.interprov.out_rate": "traslados_entre_provincias",
    "mov.interprov.net_rate": "traslados_entre_provincias",
    # Nivel turístico (INE, Encuesta de Ocupación Hotelera)
    "tur.hotel.travellers": "nivel_turistico",
    "tur.hotel.overnight": "nivel_turistico",
    "tur.hotel.stay_mean": "nivel_turistico",
    "tur.overnight_per_1000hab": "nivel_turistico",
    # Mercado inmobiliario
    "inm.sales.dwellings": "compra_venta_inmuebles",
    "inm.sales.per_1000hab": "compra_venta_inmuebles",
    "inm.dwellings.main_pct": "viviendas_vacias_principales",
    "inm.dwellings.empty_pct": "viviendas_vacias_principales",
    "inm.price.m2": "precio_vivienda_historico",
    "inm.price.yoy_change": "precio_vivienda_historico",
    "inm.rent.m2": "alquiler_vivienda_proxy",
    # Catastro: locales comerciales (ya existían, en Competencia)
    "sat.occupancy": "catastro_locales_cartografia",
    "sat.available_units": "catastro_locales_cartografia",
}

_SI = {"incluir", "incluida", "incluido", "si", "sí", "true", "1", "on", "yes", "mostrar"}
_NO = {"excluir", "excluida", "excluido", "no", "false", "0", "off", "ocultar"}


def a_booleano(valor: Any) -> bool | None:
    """`incluir`/`excluir`, booleanos o 1/0. None si no se entiende."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int | float):
        return bool(valor)
    texto = str(valor if valor is not None else "").strip().lower()
    if texto in _SI:
        return True
    if texto in _NO:
        return False
    return None


def normalizar(raw: Mapping[str, Any] | None) -> dict[str, bool]:
    """Las ocho capas, todas presentes. Lo que no viene, encendido."""
    raw = raw or {}
    out: dict[str, bool] = {}
    for clave in CLAVES:
        valor = a_booleano(raw.get(clave)) if clave in raw else None
        out[clave] = True if valor is None else valor
    return out


def ocultas(layers: Mapping[str, Any] | None) -> frozenset[str]:
    """Claves de las capas apagadas."""
    return frozenset(k for k, v in normalizar(layers).items() if not v)


def capa_de(code: str) -> str | None:
    return INDICADOR_CAPA.get(code)


def visibles(codes: Iterable[str], hidden: Iterable[str]) -> list[str]:
    """Los códigos que no pertenecen a una capa apagada, en su orden."""
    apagadas = set(hidden)
    return [c for c in codes if INDICADOR_CAPA.get(c) not in apagadas]


def capas_de_seccion(section: Section) -> tuple[str, ...]:
    return tuple(c.key for c in CAPAS if c.section is section)
