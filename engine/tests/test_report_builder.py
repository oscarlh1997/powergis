"""Composición del informe y contrato del payload que consume el front."""

from __future__ import annotations

import json

import pytest

from powergis.domain.enums import Section, Tier
from powergis.domain.report import ReportBuilder

ENGINE = "1.0.0-test"


@pytest.fixture
def builder():
    return ReportBuilder(ENGINE)


@pytest.fixture
def basic(builder, project, context):
    context.tier = Tier.BASICO
    return builder.build(project, context, version=1, tier=Tier.BASICO)


@pytest.fixture
def advanced(builder, advanced_project, context):
    return builder.build(advanced_project, context, version=2, tier=Tier.AVANZADO)


class TestInformeBasico:
    def test_solo_demografia_esta_disponible(self, basic):
        disponibles = [s.id for s in basic.sections if s.available]
        assert disponibles == [Section.DEMOGRAFIA]

    def test_las_demas_secciones_viajan_bloqueadas(self, basic):
        bloqueadas = [s for s in basic.sections if not s.available]
        assert len(bloqueadas) == 4
        assert all(s.locked_reason == "tier" for s in bloqueadas)

    def test_el_basico_no_lleva_placerank(self, basic):
        assert basic.placerank is None

    def test_el_payload_serializa_a_json(self, basic):
        blob = json.dumps(basic.as_dict(), ensure_ascii=False)
        assert '"available": false' in blob.replace('"available":false', '"available": false')

    def test_ninguna_seccion_bloqueada_filtra_datos(self, basic):
        """Lo importante del modelo básico→avanzado: no se envía y se oculta."""
        blob = json.dumps(basic.as_dict())
        for section in basic.sections:
            if section.available:
                continue
            raw = section.as_dict()
            assert set(raw) == {"id", "title", "available", "locked_reason", "preview"}
            # `preview` es el índice de venta: etiquetas, nunca datos.
            assert all(isinstance(item, str) for item in raw["preview"])
        assert "eco.income.household.mean" not in blob
        assert "cmp.count" not in blob


class TestInformeAvanzado:
    def test_todas_las_secciones_con_datos_estan_disponibles(self, advanced):
        disponibles = {s.id for s in advanced.sections if s.available}
        assert Section.DEMOGRAFIA in disponibles
        assert Section.SOCIOECONOMICO in disponibles
        assert Section.CLIMA in disponibles

    def test_incluye_placerank(self, advanced):
        assert advanced.placerank is not None
        assert advanced.placerank["rows"]

    def test_incluye_capas_de_geolens(self, advanced):
        assert advanced.geolens["layers"]
        capa = advanced.geolens["layers"][0]
        assert set(capa) >= {"id", "indicator", "breaks", "values", "palette"}

    def test_geolens_lleva_valores_y_no_geometrias(self, advanced):
        """Las geometrías van en las teselas PMTiles; los valores, aquí."""
        capa = advanced.geolens["layers"][0]
        assert all(isinstance(k, str) for k in capa["values"])
        assert "geom" not in json.dumps(advanced.geolens)
        assert advanced.geolens["tiles"]["promote_id"] == "geo_code"

    def test_resumen_ejecutivo_con_mejores_y_peores_zonas(self, advanced):
        summary = advanced.executive_summary
        assert summary["mejores_zonas"]
        assert summary["peores_zonas"]
        assert summary["narrative"] is None  # lo rellena la cola de IA


class TestUpgradeIncremental:
    """Un solo job, dos perfiles, acumulativo. Ni ocultar ni duplicar."""

    def test_el_avanzado_reutiliza_la_demografia_del_basico(self, builder, advanced_project, context, basic):
        previo = basic.as_dict()
        # Marcador imposible de reproducir: si aparece, viene del snapshot v1.
        previo["sections"][0]["subsections"][0]["title"] = "REUTILIZADO-DEL-V1"

        v2 = builder.build(
            advanced_project, context, version=2, tier=Tier.AVANZADO, previous=previo
        )
        demografia = next(s for s in v2.sections if s.id is Section.DEMOGRAFIA)
        assert demografia.subsections[0].title == "REUTILIZADO-DEL-V1"

    def test_el_upgrade_anade_las_secciones_que_faltaban(self, builder, advanced_project, context, basic):
        v2 = builder.build(
            advanced_project, context, version=2, tier=Tier.AVANZADO,
            previous=basic.as_dict(),
        )
        antes = {s.id for s in basic.sections if s.available}
        despues = {s.id for s in v2.sections if s.available}
        assert antes < despues

    def test_no_se_reutiliza_una_seccion_bloqueada(self, builder, advanced_project, context, basic):
        v2 = builder.build(
            advanced_project, context, version=2, tier=Tier.AVANZADO,
            previous=basic.as_dict(),
        )
        socio = next(s for s in v2.sections if s.id is Section.SOCIOECONOMICO)
        assert socio.available and socio.subsections

    def test_la_version_sube(self, basic, advanced):
        assert advanced.version > basic.version


class TestMetadatosDelInforme:
    def test_ambito_resuelto(self, advanced, context):
        assert advanced.scope["name"] == "Comunidad de Madrid"
        assert advanced.scope["children_level"] == "provincia"
        assert advanced.scope["children_count"] == len(context.children)

    def test_se_citan_las_fuentes(self, advanced):
        nombres = {s["name"] for s in advanced.sources}
        assert any("INE" in n for n in nombres)
        assert all(s["attribution"] is not None for s in advanced.sources)

    def test_hay_glosario(self, advanced):
        assert advanced.glossary
        assert all({"term", "code", "definition"} <= set(g) for g in advanced.glossary)

    def test_los_avisos_llegan_al_informe(self, advanced):
        assert isinstance(advanced.warnings, list)

    def test_version_de_motor_en_el_payload(self, advanced):
        assert advanced.as_dict()["engine_version"] == ENGINE


class TestContratoDelPayload:
    """Si esto cambia, hay que cambiar el bundle JS del front a la vez."""

    def test_claves_de_primer_nivel(self, advanced):
        assert set(advanced.as_dict()) == {
            "project_uuid", "tier", "version", "engine_version", "generated_at",
            "scope", "segments", "business", "sections", "geolens", "placerank",
            "executive_summary", "glossary", "sources", "warnings",
        }

    def test_forma_uniforme_de_las_secciones(self, advanced):
        for section in advanced.as_dict()["sections"]:
            if not section["available"]:
                continue
            for sub in section["subsections"]:
                assert set(sub) == {"id", "title", "kpis", "charts", "tables", "narrative"}

    def test_las_tablas_llevan_columnas_tipadas(self, advanced):
        tabla = advanced.as_dict()["sections"][0]["subsections"][0]["tables"][0]
        for column in tabla["columns"]:
            assert column["type"] in {"text", "int", "float", "pct", "eur", "index"}

    def test_los_kpis_marcan_el_hueco_explicitamente(self, advanced):
        kpis = [
            k for s in advanced.as_dict()["sections"] if s["available"]
            for sub in s["subsections"] for k in sub["kpis"]
        ]
        assert all("missing" in k for k in kpis)
