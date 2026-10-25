"""Catálogo de indicadores — la fuente de verdad del producto.

Añadir una métrica al informe (o una capa a GeoLens) es añadir una entrada
aquí y un colector que la sepa cargar. Ni una línea de código de sección.

Convención de códigos:  <prefijo_sección>.<familia>.<métrica>
    dem.*  demografía        eco.*  socioeconómico
    cmp.*  competencia       anc.*  anclas y atractivos
    sat.*  saturación        cli.*  clima
    tra.*  tráfico           pol.*  resultados electorales
    mov.*  traslados         tur.*  turismo
    inm.*  vivienda
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
CCAA = GeoLevel.CCAA

#: Fuente de lo que rellena a mano el equipo de datos (ver `collectors.plantilla`).
EQUIPO = "Equipo de datos (plantilla)"


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
       source="INE:Atlas de renta", tier=Tier.BASICO, decimals=1),
    _i("dem.age.0_15", "edad", "Población 0-15", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.age.16_64", "edad", "Población 16-64", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
    _i("dem.age.65p", "edad", "Población 65 o más", Unit.PERSONAS, section=Section.DEMOGRAFIA,
       source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),

    # -- edad en porcentaje: los tramos que el INE publica por municipio -----
    #
    # Los tres de arriba van en PERSONAS y cortan en 15/16. La única fuente
    # municipal con cobertura nacional —el Atlas de renta— da PORCENTAJES y
    # corta en 18. No se reutilizan aquellos códigos: meter «% menor de 18»
    # donde pone «Población 0-15» sería un dato correcto en el sitio
    # equivocado —cambia la unidad y cambia el tramo— y nadie que leyera el
    # informe podría notarlo.
    _i("dem.age.u18_pct", "edad", "% menores de 18 años", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Atlas de renta", tier=Tier.BASICO,
       decimals=1),
    _i("dem.age.65p_pct", "edad", "% de 65 y más años", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Atlas de renta", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, decimals=1),
    _i("dem.age.18_64_pct", "edad", "% de 18 a 64 años", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="derivado", tier=Tier.BASICO,
       formula="100 - %<18 - %65+", decimals=1,
       description="Población en edad de trabajar. Se obtiene por resta, que es "
                   "exacta: los tres tramos suman el total."),
    _i("dem.dependency.total", "edad", "Tasa de dependencia total", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_LB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, formula="(jóvenes + 65+) / edad activa * 100", decimals=1,
       description="Con los tramos en personas (0-15, 16-64) si existen; si no, "
                   "con los del Atlas (<18, 18-64). Es un cociente entre tramos, "
                   "así que sale igual en personas que en porcentaje; nunca se "
                   "mezclan los dos cortes en la misma cuenta."),
    _i("dem.ageing.index", "edad", "Índice de envejecimiento", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_LB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO, formula="65+ / jóvenes * 100", decimals=1),

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
       section=Section.DEMOGRAFIA, source="INE:Censo anual (estado civil)", tier=Tier.BASICO,
       decimals=1, formula="solteros de 16+ / población de 16+ × 100",
       description="Estado civil legal, no convivencia. Municipios de 500 o más "
                   "habitantes; el resto, si lo aporta el equipo de datos."),
    _i("dem.civil.married_pct", "hogares", "% casados", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo anual (estado civil)", tier=Tier.BASICO,
       decimals=1, formula="casados de 16+ / población de 16+ × 100"),
    _i("dem.birth.rate", "hogares", "Tasa bruta de natalidad", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:MNP", tier=Tier.BASICO,
       min_level=PRO, dimension=Dimension.DEMOGRAFICO, decimals=2),
    _i("dem.children.mean", "hogares", "Número medio de hijos por hogar", Unit.RATIO,
       section=Section.DEMOGRAFIA, source=EQUIPO, tier=Tier.BASICO, decimals=2,
       description="No hay serie oficial anual para todos los municipios (la ECEPOV "
                   "2021 sólo cubre CCAA, provincias y municipios grandes). Lo aporta "
                   "el equipo de datos: todos los hijos del hogar, sin límite de edad "
                   "(nº total de hijos / nº de hogares)."),
    _i("dem.household.size", "hogares", "Tamaño medio del hogar", Unit.RATIO,
       section=Section.DEMOGRAFIA, source="INE:Atlas de renta", tier=Tier.BASICO, decimals=2),
    _i("dem.household.single_pct", "hogares", "% hogares unipersonales", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Atlas de renta", tier=Tier.BASICO, decimals=1),
    _i("dem.household.with_children_pct", "hogares", "% hogares con hijos", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.household.monoparental_pct", "hogares", "% hogares monoparentales", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),

    # -- formación ----------------------------------------------------------
    _i("dem.edu.primary_or_less_pct", "formacion", "% sin estudios o con estudios primarios",
       Unit.PORCENTAJE, section=Section.DEMOGRAFIA, direction=_LB,
       source="INE:Censo anual (educación)", tier=Tier.BASICO, decimals=1,
       formula="población 15+ con educación primaria o inferior / población 15+ × 100",
       description="El Censo anual publica primaria e inferior como un solo nivel. "
                   "Por tramo de edad se guarda como segmento {age}."),
    _i("dem.edu.none_pct", "formacion", "% sin estudios", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_LB, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.primary_pct", "formacion", "% educación primaria", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.secondary_pct", "formacion", "% secundaria y FP", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.university_pct", "formacion", "% con estudios superiores", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:Censo anual (educación)",
       tier=Tier.BASICO, dimension=Dimension.DEMOGRAFICO, decimals=1,
       formula="población 15+ con educación superior / población 15+ × 100",
       description="Índice de cualificación universitaria. Por tramo de edad se "
                   "guarda como segmento {age}."),
    _i("dem.edu.postgrad_pct", "formacion", "% posgrado", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, direction=_HB, source="INE:Censo", tier=Tier.BASICO, decimals=1),
    _i("dem.edu.qualification_index", "formacion", "Índice de cualificación", Unit.INDICE,
       section=Section.DEMOGRAFIA, direction=_HB, source="derivado", tier=Tier.BASICO,
       dimension=Dimension.DEMOGRAFICO,
       formula="(universitarios + 1.5*posgrado) / población 25+ * 100", decimals=1),

    # -- nacionalidades -----------------------------------------------------
    _i("dem.nat.foreign_pct", "nacionalidades", "% población extranjera", Unit.PORCENTAJE,
       section=Section.DEMOGRAFIA, source="INE:Censo anual (nacionalidad)", tier=Tier.BASICO,
       decimals=1, formula="nacionalidad extranjera / población total × 100",
       description="Por nacionalidad, no por país de nacimiento."),
    _i("dem.nat.diversity_index", "nacionalidades", "Índice de diversidad cultural", Unit.INDICE,
       section=Section.DEMOGRAFIA, source=EQUIPO, tier=Tier.BASICO,
       formula="Simpson/Blau: 1 − Σ pᵢ² sobre grupos de nacionalidad", decimals=3,
       description="Índice propio, no oficial del INE: 0 = todos del mismo grupo, "
                   "cerca de 1 = muy diverso. Lo calcula el equipo de datos."),
    _i("dem.nat.count", "nacionalidades", "Nacionalidades presentes", Unit.UNIDADES,
       section=Section.DEMOGRAFIA, source="INE:Padrón continuo", tier=Tier.BASICO, decimals=0),
]

# --------------------------------------------------------------------------- #
# FASE 4a · Socioeconómico
# --------------------------------------------------------------------------- #

_ECO = [
    _i("eco.poverty.risk_pct", "desigualdad", "% hogares en riesgo de exclusión", Unit.PORCENTAJE,
       section=Section.SOCIOECONOMICO, direction=_LB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=1),
    _i("eco.gini", "desigualdad", "Índice de Gini", Unit.INDICE, section=Section.SOCIOECONOMICO,
       direction=_LB, source="INE:ADRH", min_level=SEC, decimals=3),
    _i("eco.resilience.index", "desigualdad", "Índice de resistencia económica", Unit.INDICE,
       section=Section.SOCIOECONOMICO, direction=_HB, source="derivado", dimension=Dimension.ECONOMICO,
       formula="renta mediana normalizada × (1 - Gini) × (1 - riesgo exclusión)"),

    _i("eco.income.household.mean", "renta", "Renta bruta media por hogar", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC,
       dimension=Dimension.ECONOMICO, decimals=0,
       description="Bruta: antes de IRPF y cotizaciones. Es la que el formulario "
                   "pregunta como renta anual."),
    _i("eco.income.household.net", "renta", "Renta neta media por hogar", Unit.EUROS,
       section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH", min_level=SEC,
       decimals=0,
       description="Bruta menos IRPF y cotizaciones, MEDIDA por el Atlas. Es la "
                   "base de la renta disponible mensual cuando existe; sin ella, "
                   "la disponible se modela con un tipo efectivo supuesto."),
    # El código dice «household» por historia; el dato NO es por hogar. El
    # Atlas publica la mediana por UNIDAD DE CONSUMO (renta equivalente: el
    # primer adulto cuenta 1, cada adulto más 0,5, cada menor 0,3). Se deja el
    # código para no romper referencias y se corrige lo que ve el cliente,
    # que es la etiqueta.
    _i("eco.income.household.median", "renta", "Renta mediana por unidad de consumo",
       Unit.EUROS, section=Section.SOCIOECONOMICO, direction=_HB, source="INE:ADRH",
       min_level=SEC, dimension=Dimension.ECONOMICO, decimals=0,
       description="Mediana de la renta por unidad de consumo. Corrige el tamaño "
                   "del hogar, así que compara bien zonas con hogares grandes y "
                   "pequeños; no es una renta por hogar."),
    _i("eco.income.percapita", "renta", "Renta neta media por persona", Unit.EUROS,
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
       section=Section.SOCIOECONOMICO, source="INE:TIC-H", decimals=1,
       description="Personas de 16 a 74 años que compraron por Internet en los "
                   "últimos 3 meses. El INE lo publica por comunidad autónoma: "
                   "provincias y municipios llevan el dato de su comunidad."),
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
    # Las dos que dio de alta el equipo de datos en la plantilla del 18/10/2026.
    _i("cli.humidity.annual", "clima", "Humedad relativa media anual", Unit.PORCENTAJE,
       section=Section.CLIMA, source="AEMET", decimals=1,
       description="Aproximación del equipo de datos: media entre la humedad del mes más "
                   "húmedo y la del más seco de cada capital (CTE DB-SE-M, anejo F). No es "
                   "una media de los doce meses."),
    _i("cli.sun.hours.annual", "clima", "Horas de sol al año", Unit.HORAS,
       section=Section.CLIMA, direction=_HB, source="AEMET", decimals=0,
       description="Horas de sol anuales (no días de sol: no es intercambiable con "
                   "«Días de sol al año»)."),
]

# --------------------------------------------------------------------------- #
# Capas complementarias (formulario de octubre de 2026)
#
# Cada indicador pertenece a una capa que el cliente enciende o apaga en el
# formulario (`domain.capas`). Ninguno puntúa en el PlaceRank: son contexto,
# no criterio. Todos llegan, de momento, por la plantilla del equipo de datos:
# las fuentes oficiales no tienen una API estable para automatizarlos (ver la
# hoja «Fuentes nuevas» de la investigación del equipo de datos).
# --------------------------------------------------------------------------- #

INTERIOR = "Ministerio del Interior: Infoelectoral"

_CTX = [
    _i("pol.turnout_pct", "electoral", "Participación electoral", Unit.PORCENTAJE,
       section=Section.CONTEXTO, source=INTERIOR, decimals=1,
       description="Votantes sobre censo electoral en la última convocatoria indicada en la "
                   "plantilla (tipo y fecha de la elección en la columna Fuente)."),
    _i("pol.winner_share_pct", "electoral", "Voto a la candidatura más votada", Unit.PORCENTAJE,
       section=Section.CONTEXTO, source=INTERIOR, decimals=1,
       description="Porcentaje de votos válidos de la candidatura más votada. Mide "
                   "concentración del voto, no la orientación de ninguna persona."),
    _i("pol.effective_parties", "electoral", "Número efectivo de partidos", Unit.RATIO,
       section=Section.CONTEXTO, source=INTERIOR, decimals=2,
       formula="1 / Σ pᵢ² con pᵢ = cuota de voto válido de cada candidatura (Laakso-Taagepera)"),
    _i("mov.interprov.in_rate", "traslados", "Llegadas desde otras provincias (‰)", Unit.POR_MIL,
       section=Section.CONTEXTO, source="INE:EMCR", decimals=1,
       formula="altas por cambio de residencia con origen en otra provincia / población × 1.000"),
    _i("mov.interprov.out_rate", "traslados", "Salidas hacia otras provincias (‰)", Unit.POR_MIL,
       section=Section.CONTEXTO, source="INE:EMCR", decimals=1,
       formula="bajas por cambio de residencia con destino en otra provincia / población × 1.000"),
    _i("mov.interprov.net_rate", "traslados", "Saldo de traslados entre provincias (‰)",
       Unit.POR_MIL, section=Section.CONTEXTO, source="INE:EMCR", decimals=1,
       formula="(llegadas − salidas) / población × 1.000"),
]

_TUR = [
    _i("tur.hotel.travellers", "turismo", "Viajeros alojados en hoteles (año)", Unit.PERSONAS,
       section=Section.TURISMO, source="INE:EOH", decimals=0,
       description="Encuesta de Ocupación Hotelera. Por municipio sólo en los puntos "
                   "turísticos del INE: el resto queda en blanco, nunca a cero."),
    _i("tur.hotel.overnight", "turismo", "Pernoctaciones hoteleras (año)", Unit.UNIDADES,
       section=Section.TURISMO, source="INE:EOH", decimals=0),
    _i("tur.hotel.stay_mean", "turismo", "Estancia media en hoteles (días)", Unit.RATIO,
       section=Section.TURISMO, source="INE:EOH", decimals=2,
       formula="pernoctaciones / viajeros"),
    _i("tur.overnight_per_1000hab", "turismo", "Pernoctaciones hoteleras por 1.000 habitantes",
       Unit.POR_MIL, section=Section.TURISMO, source="INE:EOH", decimals=0,
       formula="pernoctaciones / población × 1.000"),
    # Índice propio y desglose nacional / internacional (decisión de Aldo, 20/10/2026).
    _i("tur.index", "turismo", "Índice de intensidad turística (España = 100)", Unit.INDICE,
       section=Section.TURISMO, source="derivado:INE EOH", decimals=0,
       formula="pernoctaciones por 1.000 hab. de la zona / las de España × 100",
       description="Índice propio de PowerGIS: 100 es la media de España; 200, el doble de "
                   "pernoctaciones por habitante. Se marca como estimado."),
    _i("tur.hotel.travellers.resident", "turismo", "Viajeros residentes en España (turismo "
       "nacional)", Unit.PERSONAS, section=Section.TURISMO, source="INE:EOH", decimals=0,
       description="Encuesta de Ocupación Hotelera por lugar de residencia del viajero."),
    _i("tur.hotel.travellers.foreign", "turismo", "Viajeros residentes en el extranjero "
       "(turismo internacional)", Unit.PERSONAS, section=Section.TURISMO, source="INE:EOH",
       decimals=0),
    _i("tur.hotel.foreign_pct", "turismo", "% de viajeros internacionales", Unit.PORCENTAJE,
       section=Section.TURISMO, source="derivado", decimals=1,
       formula="viajeros residentes en el extranjero / viajeros totales × 100"),
    _i("tur.mobile.domestic", "turismo", "Turistas nacionales (año, teléfonos móviles)",
       Unit.PERSONAS, section=Section.TURISMO,
       source="INE:Medición del turismo con teléfonos móviles", decimals=0,
       description="Estadística experimental del INE. Llega a municipio (o agrupación de "
                   "municipios) y cuenta también a quien no duerme en un hotel."),
    _i("tur.mobile.international", "turismo", "Turistas internacionales (año, teléfonos "
       "móviles)", Unit.PERSONAS, section=Section.TURISMO,
       source="INE:Medición del turismo con teléfonos móviles", decimals=0),
]

_INM = [
    _i("inm.sales.dwellings", "compraventa", "Compraventas de viviendas (año)", Unit.UNIDADES,
       section=Section.INMOBILIARIO, source="INE:ETDP", decimals=0,
       description="Estadística de Transmisiones de Derechos de la Propiedad. El INE la "
                   "publica por provincia: no hay dato municipal."),
    _i("inm.sales.per_1000hab", "compraventa", "Compraventas de viviendas por 1.000 habitantes",
       Unit.POR_MIL, section=Section.INMOBILIARIO, source="INE:ETDP", decimals=1,
       formula="compraventas de viviendas / población × 1.000",
       description="Por provincia. Los municipios llevan el dato de su provincia."),
    _i("inm.dwellings.main_pct", "viviendas", "% viviendas principales", Unit.PORCENTAJE,
       section=Section.INMOBILIARIO, source="INE:Censo 2021", min_level=SEC, decimals=1),
    _i("inm.dwellings.empty_pct", "viviendas", "% viviendas vacías", Unit.PORCENTAJE,
       section=Section.INMOBILIARIO, source="INE:Censo 2021", min_level=SEC, decimals=1,
       description="Categoría «vacía» del Censo 2021. No incluye las de uso esporádico, "
                   "que no equivalen a segunda residencia."),
    _i("inm.price.m2", "precio", "Valor tasado medio de la vivienda libre (€/m²)", Unit.EUROS,
       section=Section.INMOBILIARIO, source="MIVAU:Valor tasado", decimals=0,
       description="Valor de tasación, no precio de una operación concreta ni de anuncios. "
                   "Por provincia; los municipios llevan el dato de su provincia."),
    _i("inm.price.yoy_change", "precio", "Variación interanual del valor tasado", Unit.PORCENTAJE,
       section=Section.INMOBILIARIO, source="MIVAU:Valor tasado", decimals=1),
    _i("inm.rent.m2", "alquiler", "Alquiler de vivienda de referencia (€/m² al mes)", Unit.EUROS,
       section=Section.INMOBILIARIO, source="MIVAU:SERPAVI", decimals=2,
       description="Índice de referencia del alquiler (SERPAVI): una aproximación, no la "
                   "renta de un contrato concreto."),
    # Todo lo inmobiliario que ofrece el formulario (decisión de Aldo, 20/10/2026).
    _i("inm.ipv.index", "precio", "Índice de Precios de Vivienda (INE, base 2015)", Unit.INDICE,
       section=Section.INMOBILIARIO, source="INE:IPV", decimals=1,
       description="Precio de compraventa de vivienda libre. El INE lo publica por comunidad "
                   "autónoma: provincias y municipios llevan el de su comunidad."),
    _i("inm.ipv.yoy", "precio", "Variación anual del precio de la vivienda (INE IPV)",
       Unit.PORCENTAJE, section=Section.INMOBILIARIO, source="INE:IPV",
       decimals=1),
    _i("inm.affordability.years", "precio", "Años de renta para comprar 90 m²", Unit.RATIO,
       section=Section.INMOBILIARIO, source="derivado", decimals=1,
       formula="valor tasado (€/m²) × 90 / renta bruta media por hogar",
       description="Estimación de PowerGIS: años de renta bruta íntegra de un hogar medio "
                   "para pagar una vivienda de 90 m² al valor tasado."),
    _i("inm.rent.ipva_yoy", "alquiler", "Variación anual del alquiler (INE IPVA)",
       Unit.PORCENTAJE, section=Section.INMOBILIARIO, source="INE:IPVA", decimals=1,
       description="Índice de Precios de Vivienda en Alquiler (estadística experimental, "
                   "datos de la AEAT). Llega a municipio."),
    _i("inm.rent.effort_pct", "alquiler", "Esfuerzo del alquiler (% de la renta, 80 m²)",
       Unit.PORCENTAJE, section=Section.INMOBILIARIO, source="derivado", decimals=1,
       formula="alquiler (€/m² al mes) × 80 × 12 / renta bruta media por hogar × 100",
       description="Estimación de PowerGIS: parte de la renta de un hogar medio que se iría "
                   "en alquilar 80 m² al precio de referencia."),
    _i("inm.cadastre.urban_units", "catastro", "Inmuebles urbanos (Catastro)", Unit.UNIDADES,
       section=Section.INMOBILIARIO, source="Catastro", decimals=0,
       description="Bienes inmuebles urbanos de la estadística catastral (todos los usos)."),
    _i("inm.cadastre.value_mean", "catastro", "Valor catastral medio por inmueble urbano",
       Unit.EUROS, section=Section.INMOBILIARIO, source="Catastro", decimals=0,
       description="Valor catastral (administrativo), no de mercado."),
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
    # Aforos REALES, cuando el equipo de datos los consigue (ayuntamientos,
    # DGT, mapas de tráfico autonómicos). Conviven con los índices: el índice
    # sale siempre; el aforo, sólo donde hay medición.
    _i("tra.pedestrian.aforo", "peatonal", "Aforo peatonal (personas/día)", Unit.PERSONAS,
       section=Section.TRAFICO, direction=_HB, source=EQUIPO, decimals=0,
       description="Medición de paso de peatones aportada por el equipo de datos."),
    _i("tra.vehicle.imd", "vehicular", "Intensidad media diaria (vehículos/día)",
       Unit.UNIDADES, section=Section.TRAFICO, direction=_HB, source=EQUIPO, decimals=0,
       description="IMD de las vías del ámbito, aportada por el equipo de datos."),
    _i("tra.transit.stops", "peatonal", "Paradas de transporte público", Unit.UNIDADES,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=0),
    _i("tra.road.primary_km", "vehicular", "Viario primario", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=1),
    _i("tra.parking.capacity", "vehicular", "Plazas de aparcamiento", Unit.UNIDADES,
       section=Section.TRAFICO, direction=_HB, source="OSM", decimals=0),
    _i("tra.accessibility.index", "peatonal", "Índice de accesibilidad", Unit.INDICE,
       section=Section.TRAFICO, direction=_HB, source="derivado", dimension=Dimension.AMBIENTAL),
]


CATALOG: list[Indicator] = [*_DEMO, *_ECO, *_CTX, *_INM, *_CMP, *_TUR, *_CLI, *_TRA]

BY_CODE: dict[str, Indicator] = {i.code: i for i in CATALOG}


#: Lo que no varía dentro de un municipio, o que su fuente sólo publica por
#: municipio o por encima: los distritos y secciones llevan el valor de su
#: municipio, con la etiqueta «Dato de su municipio» (`domain.estado`).
HEREDABLES_DEL_MUNICIPIO: tuple[str, ...] = (
    "cli.", "mov.", "tur.", "inm.price.", "inm.ipv.", "inm.sales.", "inm.rent.",
    "eco.consumer.online_pct", "sat.turnover", "sat.survival3y", "dem.birth.rate",
)


def heredable(ind: Indicator) -> bool:
    """¿Lo puede llevar un distrito o una sección del valor de su municipio?

    Nunca un total (personas, unidades): el del municipio no es el de la zona.
    """
    return ind.code.startswith(HEREDABLES_DEL_MUNICIPIO) and ind.unit not in {
        Unit.PERSONAS, Unit.UNIDADES}


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
        Section.CONTEXTO,
        Section.INMOBILIARIO,
        Section.COMPETENCIA,
        Section.TURISMO,
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
