"""PlaceRank: las tres reglas que separan un ranking serio de uno decorativo."""

from __future__ import annotations

import pytest

from powergis.domain import placerank
from powergis.domain.enums import Dimension, ScoreCategory, Tier


@pytest.fixture
def result(context):
    context.tier = Tier.AVANZADO
    return placerank.compute(context, placerank.get_profile("restauracion"))


class TestCalculo:
    def test_puntua_todas_las_zonas(self, result, context):
        assert len(result.rows) == len(context.children)

    def test_los_scores_estan_en_rango(self, result):
        assert all(0.0 <= r.score <= 100.0 for r in result.rows)

    def test_el_ranking_esta_ordenado(self, result):
        assert [r.rank for r in result.rows] == list(range(1, len(result.rows) + 1))
        assert result.rows == sorted(result.rows, key=lambda r: -r.score)

    def test_la_categoria_se_deriva_del_score(self, result):
        for row in result.rows:
            assert row.category is ScoreCategory.from_score(row.score)

    def test_madrid_gana_en_restauracion(self, result):
        assert result.rows[0].geo_name == "Madrid"


class TestNormalizacionDentroDelAmbito:
    """Regla 2: el 100 es la mejor zona DEL ÁMBITO, no de España."""

    def test_alguien_ocupa_la_parte_alta_del_rango(self, result):
        assert max(r.score for r in result.rows) > 55

    def test_alguien_ocupa_la_parte_baja(self, result):
        assert min(r.score for r in result.rows) < 50

    def test_el_ranking_no_sale_todo_en_gris(self, result):
        spread = max(r.score for r in result.rows) - min(r.score for r in result.rows)
        assert spread > 15, "sin dispersión el ranking no informa de nada"


class TestContribuciones:
    """Regla 3: sin contribuciones no puedes explicar el resultado."""

    def test_cada_zona_guarda_sus_contribuciones(self, result):
        assert all(row.contributions for row in result.rows)

    def test_explain_devuelve_hechos_compactos_para_la_ia(self, result, context):
        facts = placerank.explain(result.rows[0], context.catalog, top_n=5)
        assert facts["zona"] == "Madrid"
        assert facts["posicion"] == 1
        assert len(facts["factores"]) <= 5
        assert all("label" in f and "contribution" in f for f in facts["factores"])

    def test_los_hechos_para_la_ia_son_pequenos(self, result, context):
        """La IA no ve el dataset: ve esto. Si crece, alucina más y cuesta más."""
        import json

        facts = placerank.explain(result.rows[0], context.catalog)
        assert len(json.dumps(facts)) < 2000


class TestPesosSonDatos:
    """Regla 1: cambiar el modelo de un sector no debe requerir despliegue."""

    def test_cada_sector_pondera_distinto(self):
        salud = placerank.get_profile("salud").normalized_dimensions()
        retail = placerank.get_profile("retail").normalized_dimensions()
        assert salud[Dimension.DEMOGRAFICO] > retail[Dimension.DEMOGRAFICO]
        assert retail[Dimension.ECONOMICO] > salud[Dimension.ECONOMICO]

    def test_los_pesos_normalizan_a_uno(self):
        for sector in placerank.BUILTIN_PROFILES:
            total = sum(placerank.get_profile(sector).normalized_dimensions().values())
            assert total == pytest.approx(1.0)

    def test_un_sector_desconocido_cae_al_perfil_por_defecto(self):
        profile = placerank.get_profile("floristeria-submarina")
        assert profile.normalized_dimensions()[Dimension.ECONOMICO] == pytest.approx(0.35)

    def test_rebalance_recalcula_sin_tocar_la_base_de_datos(self, result):
        antes = {r.geo_code: r.score for r in result.rows}
        despues = placerank.rebalance(result, {
            Dimension.ECONOMICO: 0.0, Dimension.DEMOGRAFICO: 1.0,
            Dimension.AMBIENTAL: 0.0, Dimension.MATCH: 0.0,
        })
        assert {r.geo_code for r in despues.rows} == set(antes)
        assert any(r.score != antes[r.geo_code] for r in despues.rows)
        assert [r.rank for r in despues.rows] == list(range(1, len(despues.rows) + 1))


class TestRobustez:
    def test_sin_zonas_devuelve_ranking_vacio(self, context):
        context.children = []
        assert placerank.compute(context).rows == []

    def test_un_indicador_casi_vacio_no_entra_en_el_score(self, context):
        """Puntuar con 1 valor de 4 zonas es ruido, no señal."""
        context.tier = Tier.AVANZADO
        usable = placerank._usable_indicators(
            context, placerank.get_profile("generico"), min_coverage=0.9
        )
        assert "eco.income.household.mean" not in {i.code for i in usable}  # solo 3 de 4

    def test_podium_no_solapa_mejores_y_peores(self, result):
        top, bottom = placerank.podium(result, 3)
        assert not {r.geo_code for r in top} & {r.geo_code for r in bottom}

    def test_categorias_en_los_umbrales(self):
        assert ScoreCategory.from_score(85) is ScoreCategory.OPTIMA
        assert ScoreCategory.from_score(84.9) is ScoreCategory.EXCELENTE
        assert ScoreCategory.from_score(0) is ScoreCategory.PESIMA
