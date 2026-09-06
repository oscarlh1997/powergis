"""Catálogo de indicadores — la fuente de verdad del producto.

Añadir una métrica al informe (o una capa a GeoLens) es añadir una entrada
aquí y un colector que la sepa cargar. Ni una línea de código de sección.

Convención de códigos:  <prefijo_sección>.<familia>.<métrica>
    dem.*  demografía        eco.*  socioeconómico
    cmp.*  competencia       anc.*  anclas y atractivos
    sat.*  saturación        cli.*  clima
    tra.*  tráfico
"""

from __future__ import annotations

from .enums import Dimension, Direction, GeoLevel, Section, Tier, Unit
from .models import Indicator

_HB = Direction.HIGHER_IS_BETTER
_LB = Direction.LOWER_IS_BETTER
_NE = Direction.NEUTRAL

MUN = GeoLevel.MUNICIPIO
SEC = GeoLevel.SECCION
PRO = GeoLevel.PROVINCIA


def _i(
    code: str,
    subsection: str,
    label: str,
    unit: Unit,
    *,
    section: Section,
    direction: Direction = _NE,
    source: str = "",
    min_level: GeoLevel = MUN,
    tier: Tier = Tier.AVANZADO,
    dimension: Dimension | None = None,
    decimals: int = 2,
    formula: str | None = None,
    description: str = "",
) -> Indicator:
    return Indicator(
        code=code,
        section=section,
        subsection=subsection,
        label=label,
        unit=unit,
        direction=direction,
        source=source,
        min_level=min_level,
        tier=tier,
        dimension=dimension,
        decimals=decimals,
        formula=formula,
        description=description,
    )


# --------------------------------------------------------------------------- #
# FASE 1 · Demografía  (tier BÁSICO — es el informe gratuito)
# --------------------------------------------------------------------------- #

_DEMO = [
    # -- estructura de edad -------------------------------------------------
    _i("dem.pop.total", "edad", "Población total", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       direction=_HB, source="INE:Padrón continuo", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, decimals=0),
    _i("dem.pop.density", "edad", "Densidad de población", Unit.INDICE, section=Section.DEMOGRAFIA,
       direction=_HB, source="derivado", tier=Tier.BASICO, dimension=Dimension.DEMOGRAFICO,
       formula="dem.pop.total / area_km2", decimals=1),
    _i("dem.pop.segment", "edad", "Población del segmento solicitado", Unit.PERSONAS,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:Padrón continuo", tier=Tier.BASICO,
       dimension=Dimension.MATCH, decimals=0,
       description="Población que cumple TODOS los segmentos elegidos por el usuario."),
    _i("dem.pop.segment_pct", "edad", "% del segmento sobre el total", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.MATCH, formula="dem.pop.segment / dem.pop.total * 100", decimals=1),
    _i("dem.age.mean", "edad", "Edad media", Unit.ANIOS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=1),
    _i("dem.age.0_15", "edad", "Población 0-15", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.age.16_64", "edad", "Población 16-64", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.age.65p", "edad", "Población 65 o más", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.dependency.total", "edad", "Tasa de dependencia total", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_LB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, formula="(0-15 + 65+) / 16-64 * 100", decimals=1),
    _i("dem.ageing.index", "edad", "Índice de envejecimiento", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_LB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, formula="65+ / 0-15 * 100", decimals=1),

    # -- género -------------------------------------------------------------
    _i("dem.sex.women", "genero", "Mujeres", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.sex.men", "genero", "Hombres", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.sex.women_pct", "genero", "% mujeres", Unit.PORCENTAJE, section=Section.DEMOGRAFIA,
       source="derivado", tier=Tier.BASICO, decimals=1),
    _i("dem.femininity.index", "genero", "Índice de feminidad", Unit.INDICE,
       section=Section.DEMOGRAFIA, source="derivado", tier=Tier.BASICO,
       formula="mujeres / hombres * 100", decimals=1),

    # -- estado civil y hogares --------------------------------------------
    _i("dem.civil.single_pct", "hogares", "% solteros", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.civil.married_pct", "hogares", "% casados o en pareja", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.birth.rate", "hogares", "Tasa bruta de natalidad", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:MNP", tier=Tier.BASICO,
       min_level=PRO, dimension=Dimension.DEMOGRAFICO, decimals=2),
    _i("dem.children.mean", "hogares", "Número medio de hijos", Unit.RATIO,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=2),
    _i("dem.household.size", "hogares", "Tamaño medio del hogar", Unit.RATIO,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=2),
    _i("dem.household.single_pct", "hogares", "% hogares unipersonales", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.household.with_children_pct", "hogares", "% hogares con hijos", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.household.monoparental_pct", "hogares", "% hogares monoparentales", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),

    # -- formación ----------------------------------------------------------
    _i("dem.edu.none_pct", "formacion", "% sin estudios", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_LB, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.primary_pct", "formacion", "% educación primaria", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.secondary_pct", "formacion", "% secundaria y FP", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.university_pct", "formacion", "% estudios universitarios", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:Censo", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, decimals=1),
    _i("dem.edu.postgrad_pct", "formacion", "% posgrado", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.qualification_index", "formacion", "Índice de cualificación", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_HB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO,
       formula="(universitarios + 1.5*posgrado) / población 25+ * 100", decimals=1),

    # -- nacionalidades -----------------------------------------------------
    _i("dem.nat.foreign_pct", "nacionalidades", "% población extranjera", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Padrón continuo", tier=Tier.BASICO, decimals=1),
    _i("dem.nat.diversity_index", "nacionalidades", "Índice de diversidad cultural", Unit.INDICE,
       section=Section.DEMOGRAFIA, source="derivado", tier=Tier.BASICO,
       formula="Shannon normalizado sobre nacionalidades", decimals=3),
    _i("dem.nat.count", "nacionalidades", "Nacionalidades presentes", Unit.UNIDADES,
       section=Section.DEMOGRAFIA, source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
]

# --------------------------------------------------------------------------- #
# FASE 4a · Socioeconómico
# --------------------------------------------------------------------------- #

_ECO = [
    _i("eco.nse.index", "nse", "Índice NSE", Unit.INDICE, section=Section.SOCIOECONOMICO,
       direction=_HB, source="derivado:ADRH+Censo", min_level=SEC, dimension=Dimension.ECONOMICO),
    _i("eco.nse.risk_pct", "nse", "% hogares en riesgo de exclusión", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_LB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=1),
    _i("eco.nse.upper_middle_pct", "nse", "% clase media-alta", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=1),
    _i("eco.gini", "nse", "Índice de Gini", Unit.INDICE, section=Section.SOCIOECONOMICO,
       direction=_LB, source="INE:ADRH", min_level=SEC, decimals=3),
    _i("eco.resilience.index", "nse", "Índice de resistencia económica", Unit.INDICE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado", dimension=Dimension.ECONOMICO,
       formula="renta mediana normalizada × (1 - Gini) × (1 - riesgo exclusión)"),
    _i("eco.class.high_pct", "nse", "% clase alta", Unit.PORCENTAJE, section=Section.SOCIOECONOMICO,
       source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.class.mid_pct", "nse", "% clase media", Unit.PORCENTAJE, section=Section.SOCIOECONOMICO,
       source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.class.lower_mid_pct", "nse", "% clase media-baja", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.class.low_pct", "nse", "% clase baja", Unit.PORCENTAJE, section=Section.SOCIOECONOMICO,
       direction=_LB, source="INE:ADRH", min_level=SEC, decimals=1),

    _i("eco.income.household.mean", "renta", "Renta bruta media por hogar", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=0),
    _i("eco.income.household.median", "renta", "Renta mediana por hogar", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=0),
    _i("eco.income.percapita", "renta", "Renta per cápita", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC, decimals=0),
    _i("eco.income.under15k_pct", "renta", "% hogares con menos de 15.000 €", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_LB, source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.income.over30k_pct", "renta", "% hogares por encima de 30.000 €", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.income.over60k_pct", "renta", "% hogares por encima de 60.000 €", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC, decimals=1),
    _i("eco.income.yoy", "renta", "Variación interanual de la renta", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado", min_level=SEC, decimals=1),

    _i("eco.disposable.monthly", "renta_disponible", "Renta mensual disponible", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado:ADRH+IRPF",
       dimension=Dimension.ECONOMICO, decimals=0),
    _i("eco.gross_monthly", "renta_disponible", "Renta bruta mensual", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado:ADRH", decimals=0),
    _i("eco.gross_net_gap", "renta_disponible", "Diferencial bruto-disponible", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_LB, source="derivado", decimals=0),
    _i("eco.financial_stress.index", "renta_disponible", "Índice de estrés financiero", Unit.INDICE,
       section=Section.SOCIOECONOMICO, direction=_LB, source="derivado",
       dimension=Dimension.ECONOMICO,
       formula="(gasto vivienda + básicos) / renta disponible × 100"),
    _i("eco.saving.rate", "renta_disponible", "Tasa de ahorro estimada", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado", decimals=1),
    _i("eco.sector_spend", "renta_disponible", "Gasto mensual estimado en el sector", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado:ECPF",
       dimension=Dimension.MATCH, decimals=0,
       formula="renta disponible × coeficiente COICOP del sector"),

    _i("eco.consumer.ticket", "consumo", "Ticket medio estimado", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado", dimension=Dimension.MATCH,
       decimals=2),
    _i("eco.consumer.frequency", "consumo", "Frecuencia de compra semanal", Unit.RATIO,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado:ECPF", decimals=2),
    _i("eco.consumer.online_pct", "consumo", "% con hábito de compra online", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, source="INE:TIC-H", min_level=PRO, decimals=1),
    _i("eco.consumer.local_pref", "consumo", "Preferencia por comercio local", Unit.INDICE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado"),
    _i("eco.consumer.loyalty", "consumo", "Índice de fidelización", Unit.INDICE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado"),
]

# --------------------------------------------------------------------------- #
# FASE 4b · Competencia, anclas y saturación
# --------------------------------------------------------------------------- #

_CMP = [
    _i("cmp.count", "competencia", "Competidores directos", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_LB, source="OSM", dimension=Dimension.MATCH, decimals=0),
    _i("cmp.count_indirect", "competencia", "Competidores indirectos", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_LB, source="OSM", decimals=0),
    _i("cmp.density_km2", "competencia", "Densidad competitiva", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_LB, source="derivado", dimension=Dimension.MATCH,
       formula="competidores / km²"),
    _i("cmp.per_1000hab", "competencia", "Competidores por 1.000 habitantes", Unit.RATIO,
       section=Section.COMPETENCIA, direction=_LB, source="derivado"),
    _i("cmp.hhi", "competencia", "Índice de concentración (HHI)", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_LB, source="derivado", decimals=3),
    _i("cmp.age.mean", "competencia", "Antigüedad media del competidor", Unit.ANIOS,
       section=Section.COMPETENCIA, source="OSM:start_date", decimals=1),
    _i("cmp.opportunity.index", "competencia", "Índice de oportunidad competitiva", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_HB, source="derivado", dimension=Dimension.MATCH,
       formula="demanda potencial / (1 + densidad competitiva)"),

    _i("anc.supermarkets", "anclas", "Supermercados", Unit.UNIDADES, section=Section.COMPETENCIA,
       direction=_HB, source="OSM", decimals=0),
    _i("anc.schools", "anclas", "Equipamientos educativos", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_HB, source="OSM", decimals=0),
    _i("anc.health", "anclas", "Centros de salud", Unit.UNIDADES, section=Section.COMPETENCIA,
       direction=_HB, source="OSM", decimals=0),
    _i("anc.green", "anclas", "Zonas verdes", Unit.UNIDADES, section=Section.COMPETENCIA,
       direction=_HB, source="OSM", decimals=0),
    _i("anc.admin", "anclas", "Administraciones públicas", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_HB, source="OSM", decimals=0),
    _i("anc.hotels", "anclas", "Alojamientos turísticos", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_HB, source="OSM", decimals=0),
    _i("anc.poi.count", "anclas", "Puntos de interés", Unit.UNIDADES, section=Section.COMPETENCIA,
       direction=_HB, source="OSM", decimals=0),
    _i("anc.diversity.index", "anclas", "Índice de diversidad de servicios", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_HB, source="derivado", decimals=3,
       formula="Shannon normalizado sobre categorías de POI"),
    _i("anc.attraction.index", "anclas", "Índice de atracción de zona", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_HB, source="derivado", dimension=Dimension.MATCH,
       formula="Σ (POIs ponderados por capacidad de generar tráfico) / km²"),

    _i("sat.isc", "saturacion", "Índice de saturación comercial", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_LB, source="derivado", dimension=Dimension.MATCH,
       formula="oferta comercial del sector / demanda potencial estimada"),
    _i("sat.demand_supply", "saturacion", "Ratio demanda / oferta", Unit.RATIO,
       section=Section.COMPETENCIA, direction=_HB, source="derivado"),
    _i("sat.occupancy", "saturacion", "Tasa de ocupación comercial", Unit.PORCENTAJE,
       section=Section.COMPETENCIA, direction=_HB, source="Catastro", decimals=1),
    _i("sat.available_units", "saturacion", "Locales disponibles", Unit.UNIDADES,
       section=Section.COMPETENCIA, direction=_HB, source="Catastro", decimals=0),
    _i("sat.rent_m2", "saturacion", "Precio de alquiler por m²", Unit.EUROS,
       section=Section.COMPETENCIA, direction=_LB, source="estimación modelada", decimals=2,
       description="ESTIMACIÓN. No existe fuente abierta con esta granularidad; se marca como modelado."),
    _i("sat.turnover", "saturacion", "Tasa de rotación comercial", Unit.PORCENTAJE,
       section=Section.COMPETENCIA, direction=_LB, source="INE:DIRCE", min_level=PRO, decimals=1),
    _i("sat.survival3y", "saturacion", "Supervivencia empresarial a 3 años", Unit.PORCENTAJE,
       section=Section.COMPETENCIA, direction=_HB, source="INE:Demografía empresarial",
       min_level=PRO, decimals=1),
    _i("sat.opportunity.index", "saturacion", "Índice de oportunidad de mercado", Unit.INDICE,
       section=Section.COMPETENCIA, direction=_HB, source="derivado", dimension=Dimension.MATCH),
]

# --------------------------------------------------------------------------- #
# FASE 4c · Clima
# --------------------------------------------------------------------------- #

_CLI = [
    _i("cli.temp.annual", "clima", "Temperatura media anual", Unit.GRADOS_C, section=Section.CLIMA,
       source="AEMET", dimension=Dimension.AMBIENTAL, decimals=1),
    _i("cli.temp.month", "clima", "Temperatura media mensual", Unit.GRADOS_C, section=Section.CLIMA,
       source="AEMET", decimals=1, description="Segmentado por mes (segment={'month':'01'..'12'})."),
    _i("cli.precip.annual", "clima", "Precipitación anual", Unit.MM, section=Section.CLIMA,
       source="AEMET", decimals=0),
    _i("cli.precip.month", "clima", "Precipitación mensual", Unit.MM, section=Section.CLIMA,
       source="AEMET", decimals=1),
    _i("cli.rain.days", "clima", "Días de lluvia al año", Unit.DIAS, section=Section.CLIMA,
       direction=_LB, source="AEMET", dimension=Dimension.AMBIENTAL, decimals=0),
    _i("cli.sun.days", "clima", "Días de sol al año", Unit.DIAS, section=Section.CLIMA,
       direction=_HB, source="AEMET", dimension=Dimension.AMBIENTAL, decimals=0),
    _i("cli.comfort.index", "clima", "Índice de confort climático", Unit.INDICE,
       section=Section.CLIMA, direction=_HB, source="derivado", dimension=Dimension.AMBIENTAL,
       formula="días con T entre 15-27 °C y sin precipitación / 365 × 100"),
    _i("cli.seasonality.index", "clima", "Índice de estacionalidad", Unit.INDICE,
       section=Section.CLIMA, direction=_LB, source="derivado",
       formula="desviación típica mensual de temperatura normalizada"),
]

# --------------------------------------------------------------------------- #
# FASE 4d · Tráfico  (índices RELATIVOS; la metodología va en el anexo)
# --------------------------------------------------------------------------- #

_TRA = [
    _i("tra.pedestrian.index", "peatonal", "Índice de tráfico peatonal", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="derivado:OSM", dimension=Dimension.MATCH,
       formula="POIs generadores + paradas de transporte + viario peatonal, normalizado",
       description="ÍNDICE RELATIVO dentro del ámbito. No es un aforo."),
    _i("tra.vehicle.index", "vehicular", "Índice de tráfico vehicular", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="derivado:OSM", dimension=Dimension.MATCH,
       formula="km de viario primario/secundario ponderado por jerarquía",
       description="ÍNDICE RELATIVO dentro del ámbito. No es un aforo."),
    _i("tra.transit.stops", "peatonal", "Paradas de transporte público", Unit.UNIDADES,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=0),
    _i("tra.road.primary_km", "vehicular", "Viario primario", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=1),
    _i("tra.parking.capacity", "vehicular", "Plazas de aparcamiento", Unit.UNIDADES,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=0),
    _i("tra.accessibility.index", "peatonal", "Índice de accesibilidad", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="derivado", dimension=Dimension.AMBIENTAL),
]


CATALOG: list[Indicator] = [*_DEMO, *_ECO, *_CMP, *_CLI, *_TRA]

BY_CODE: dict[str, Indicator] = {i.code: i for i in CATALOG}


def by_section(section: Section, tier: Tier | None = None) -> list[Indicator]:
    out = [i for i in CATALOG if i.section is section]
    if tier is not None:
        allowed = tier.includes
        out = [i for i in out if i.tier in allowed]
    return out


def by_tier(tier: Tier) -> list[Indicator]:
    allowed = tier.includes
    return [i for i in CATALOG if i.tier in allowed]


def sections_for_tier(tier: Tier) -> list[Section]:
    """Secciones que el tier desbloquea, en orden de presentación."""
    if tier is Tier.BASICO:
        return [Section.DEMOGRAFIA]
    return [
        Section.DEMOGRAFIA,
        Section.SOCIOECONOMICO,
        Section.COMPETENCIA,
        Section.CLIMA,
        Section.TRAFICO,
    ]


def scoring_indicators() -> list[Indicator]:
    """Los que participan en el PlaceRank: tienen dimensión y dirección."""
    return [i for i in CATALOG if i.dimension is not None and i.direction is not Direction.NEUTRAL]


def resolve(codes: list[str]) -> list[Indicator]:
    return [BY_CODE[c] for c in codes if c in BY_CODE]


GLOSSARY: list[dict[str, str]] = [
    {"term": i.label, "code": i.code, "definition": i.description or (i.formula or ""), "unit": str(i.unit)}
    for i in CATALOG
    if i.description or i.formula
]
