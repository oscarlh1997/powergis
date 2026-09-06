"""Secciones del informe. Todo en memoria, sin base de datos."""

from __future__ import annotations

import pytest

from powergis.domain.enums import Section, Tier
from powergis.domain.sections import REGISTRY


class TestRegistro:
    def test_las_cinco_secciones_estan_registradas(self):
        assert set(REGISTRY) == {
            Section.DEMOGRAFIA, Section.SOCIOECONOMICO,
            Section.COMPETENCIA, Section.CLIMA, Section.TRAFICO,
        }

    def test_solo_demografia_es_basica(self):
        basicas = [s for s, b in REGISTRY.items() if b.tier is Tier.BASICO]
        assert basicas == [Section.DEMOGRAFIA]


class TestDemografia:
    @pytest.fixture
    def result(self, context):
        return REGISTRY[Section.DEMOGRAFIA].build(context)

    def test_se_construye_con_subsecciones(self, result):
        assert result.available
        ids = [s.id for s in result.subsections]
        assert "demografia.edad" in ids
        assert "demografia.genero" in ids

    def test_la_tabla_avanzada_tiene_una_fila_por_provincia(self, result, context):
        tabla = result.subsections[0].tables[0]
        assert len(tabla.rows) == len(context.children) == 4
        assert {r["zona"] for r in tabla.rows} == {"Madrid", "Toledo", "Guadalajara", "Ávila"}

    def test_la_tabla_marca_las_mejores_y_peores_zonas(self, result):
        tabla = result.subsections[0].tables[0]
        assert tabla.highlights["top"], "sin top no hay conclusiones que sacar"
        assert not set(tabla.highlights["top"]) & set(tabla.highlights["bottom"])
        assert tabla.highlights["top"][0] == "28"  # Madrid, mayor público objetivo

    def test_el_kpi_del_ambito_agrega_las_provincias(self, result, context):
        kpi = next(k for k in result.subsections[0].kpis if k.code == "dem.pop.total")
        assert kpi.value == pytest.approx(sum(
            context.value(g.geo_id, "dem.pop.total") for g in context.children
        ))

    def test_la_cobertura_se_calcula(self, result):
        assert 0.0 < result.coverage <= 1.0

    def test_el_cruce_edad_genero_usa_los_segmentos_pedidos(self, result):
        genero = next(s for s in result.subsections if s.id == "demografia.genero")
        cruce = [c for c in genero.charts if c.id == "dem.cruce_edad_genero"]
        assert cruce, "el cruce edad × género es parte del producto"
        assert cruce[0].x == ["18-35"]


class TestSeccionBloqueada:
    def test_una_seccion_avanzada_no_se_construye_en_tier_basico(self, context):
        context.tier = Tier.BASICO
        result = REGISTRY[Section.COMPETENCIA].build(context)
        assert result.available is False
        assert result.locked_reason == "tier"

    def test_una_seccion_bloqueada_no_lleva_datos_dentro(self, context):
        """Regla del producto: no se envía contenido de pago para ocultarlo con CSS."""
        context.tier = Tier.BASICO
        payload = REGISTRY[Section.SOCIOECONOMICO].build(context).as_dict()
        assert set(payload) == {"id", "title", "available", "locked_reason", "preview"}
        assert payload["id"] == "socioeconomico"
        assert payload["available"] is False
        assert payload["locked_reason"] == "tier"
        assert "subsections" not in payload
        assert "coverage" not in payload

    def test_el_indice_de_una_seccion_bloqueada_no_contiene_ni_una_cifra(self, context):
        """`preview` vende lo que hay dentro; no puede filtrar lo que vale.

        Es la única puerta por la que una sección de pago envía algo al
        navegador de quien no ha pagado, así que se comprueba que por ahí no
        cabe un número: sólo etiquetas del catálogo.
        """
        context.tier = Tier.BASICO
        payload = REGISTRY[Section.SOCIOECONOMICO].build(context).as_dict()
        preview = payload["preview"]

        assert isinstance(preview, list)
        assert all(isinstance(item, str) for item in preview), "sólo etiquetas"

        # Ningún valor calculado de la sección aparece en el índice.
        seccion = REGISTRY[Section.SOCIOECONOMICO]
        context.tier = Tier.AVANZADO
        real = seccion.build(context)
        valores = {
            str(kpi.value)
            for sub in real.subsections
            for kpi in sub.kpis
            if kpi.value is not None
        }
        texto = " ".join(preview)
        for valor in valores:
            assert valor not in texto, f"el índice filtró el valor {valor}"


class TestSecretoEstadistico:
    def test_una_zona_sin_renta_llega_como_none_no_como_cero(self, context):
        """Ávila no tiene renta publicada. Cero sería una mentira."""
        avila = next(g for g in context.children if g.name == "Ávila")
        assert context.value(avila.geo_id, "eco.income.household.mean") is None

    def test_la_tabla_conserva_el_hueco(self, context):
        result = REGISTRY[Section.SOCIOECONOMICO].build(context)
        tabla = next(
            t for s in result.subsections for t in s.tables if t.id == "eco.tabla_renta"
        )
        fila = next(r for r in tabla.rows if r["zona"] == "Ávila")
        assert fila["eco.income.household.mean"] is None

    def test_el_kpi_agregado_ignora_la_zona_sin_dato(self, context):
        result = REGISTRY[Section.SOCIOECONOMICO].build(context)
        kpi = next(
            k for s in result.subsections for k in s.kpis
            if k.code == "eco.income.household.mean"
        )
        assert kpi.value is not None  # se calcula con las 3 que sí tienen dato


class TestSeccionesSinDatos:
    def test_trafico_sin_osm_avisa_y_no_inventa(self, context):
        result = REGISTRY[Section.TRAFICO].build(context)
        assert result.subsections == []
        assert any("peatonal" in w.lower() or "osm" in w.lower() for w in context.warnings)

    def test_clima_con_datos_se_construye(self, context):
        result = REGISTRY[Section.CLIMA].build(context)
        assert result.available
        assert result.subsections
        tabla = result.subsections[0].tables[0]
        assert "AEMET" in (tabla.footnote or "")


class TestAvisosLegales:
    def test_competencia_atribuye_openstreetmap(self, context):
        from powergis.domain.sections.competencia import ATTRIBUTION

        assert "OpenStreetMap" in ATTRIBUTION

    def test_trafico_declara_que_no_es_un_aforo(self):
        from powergis.domain.sections.trafico import DISCLAIMER

        assert "NO es un aforo" in DISCLAIMER
