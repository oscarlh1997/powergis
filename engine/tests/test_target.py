"""Perfil de cliente objetivo y Match% del PlaceRank.

Los nombres y valores de los campos son los del formulario real de
powergis.es (`/crear-proyecto-geolocalizado/`, JetFormBuilder 3118).
"""

from __future__ import annotations

import pytest

from powergis.domain import placerank
from powergis.domain.enums import Dimension, Tier
from powergis.domain.target import TargetProfile, explain_match, match_scores


@pytest.fixture
def target() -> TargetProfile:
    return TargetProfile.from_mapping({
        "age_range": ["25-34", "35-44"],
        "gender": "Indiferente",
        "family_status": "Nido lleno",
        "education_level": "Universitario",
        "nse": ["A/B", "C+"],
        "annual_income": "45-75k",
        "climate": ["Templado"],
        "pedestrian_traffic": "Alto",
        "vehicular_traffic": "Indiferente",
        "direct_competition": False,
    })


class TestTraduccionDelFormulario:
    def test_los_campos_del_formulario_se_leen_tal_cual(self, target):
        assert target.education_level == "Universitario"
        assert target.nse == ("A/B", "C+")
        assert target.age_range == ("25-34", "35-44")

    def test_indiferente_no_genera_criterio(self, target):
        codigos = [c.indicator for c in target.criteria()]
        assert "tra.vehicle.index" not in codigos, "«Indiferente» no debe puntuar"
        assert "tra.pedestrian.index" in codigos, "«Alto» sí"

    def test_universitario_apunta_al_indicador_correcto(self, target):
        codigos = [c.indicator for c in target.criteria()]
        assert "dem.edu.university_pct" in codigos

    def test_el_tramo_de_renta_se_convierte_en_intervalo(self, target):
        renta = next(c for c in target.criteria() if c.indicator == "eco.income.household.mean")
        assert (renta.minimum, renta.maximum) == (45_000, 75_000)
        assert renta.kind == "range"

    def test_no_querer_competencia_se_traduce_a_menos_es_mejor(self, target):
        competencia = next(c for c in target.criteria() if c.indicator == "cmp.density_km2")
        assert competencia.kind == "lower"

    def test_el_publico_objetivo_siempre_pesa(self):
        vacio = TargetProfile()
        codigos = [c.indicator for c in vacio.criteria()]
        assert codigos == ["dem.pop.segment"]

    def test_un_perfil_sin_nada_util_no_esta_vacio_del_todo(self):
        # Siempre queda el público objetivo, que es el criterio irreducible.
        assert not TargetProfile().is_empty()


class TestMatchScore:
    def test_puntua_todas_las_zonas(self, context, target):
        scores = match_scores(context, target)
        assert set(scores) == {g.geo_id for g in context.children}

    def test_los_scores_estan_en_rango(self, context, target):
        for value in match_scores(context, target).values():
            assert value is None or 0.0 <= value <= 100.0

    def test_hay_dispersion_entre_zonas(self, context, target):
        valores = [v for v in match_scores(context, target).values() if v is not None]
        assert max(valores) - min(valores) > 5, "sin dispersión el match no informa"

    def test_un_perfil_distinto_da_un_orden_distinto(self, context):
        joven = TargetProfile.from_mapping({"education_level": "Universitario"})
        mayor = TargetProfile.from_mapping({"family_status": "Nido vacío"})
        a = match_scores(context, joven)
        b = match_scores(context, mayor)
        assert a != b, "el perfil declarado tiene que cambiar el resultado"

    def test_sin_datos_devuelve_none_no_cincuenta(self, context):
        context.facts = {}
        scores = match_scores(context, TargetProfile.from_mapping({"education_level": "Postgrado"}))
        assert all(v is None for v in scores.values())

    def test_explain_desglosa_el_match(self, context, target):
        geo = context.children[0]
        desglose = explain_match(context, target, geo.geo_id)
        assert desglose
        assert all({"criterio", "indicador", "cumplimiento", "peso"} <= set(d) for d in desglose)


class TestIntegracionConPlaceRank:
    def test_el_match_del_perfil_sustituye_a_la_aproximacion(self, context, target):
        context.tier = Tier.AVANZADO
        sin_perfil = placerank.compute(context, placerank.get_profile("restauracion"))
        con_perfil = placerank.compute(
            context, placerank.get_profile("restauracion"), target=target
        )

        a = {r.geo_code: r.dimensions[Dimension.MATCH] for r in sin_perfil.rows}
        b = {r.geo_code: r.dimensions[Dimension.MATCH] for r in con_perfil.rows}
        assert a != b

    def test_la_contribucion_del_perfil_queda_registrada(self, context, target):
        context.tier = Tier.AVANZADO
        result = placerank.compute(context, target=target)
        assert any("perfil.match" in row.contributions for row in result.rows)

    def test_sin_perfil_el_placerank_sigue_funcionando(self, context):
        context.tier = Tier.AVANZADO
        result = placerank.compute(context, target=None)
        assert result.rows
        assert all(0 <= r.score <= 100 for r in result.rows)


class TestIdempotencia:
    def test_cambiar_el_perfil_cambia_el_hash(self, project):
        from powergis.domain.target import TargetProfile as Target

        project.target = Target.from_mapping({"education_level": "Universitario"})
        a = project.input_hash(Tier.AVANZADO)
        project.target = Target.from_mapping({"education_level": "Sin estudios"})
        assert project.input_hash(Tier.AVANZADO) != a, (
            "otro perfil = otro Match% = otro informe"
        )


class TestTramosQueSeSolapan:
    """`medio` es prefijo de `medio_alto`, y la búsqueda por prefijo hacía que
    ganara el más corto: quien marcaba «Medio-Alto (201€-1.000€)» acababa
    puntuando contra el tramo 51–200. No daba error, daba el rango de otro."""

    def test_medio_alto_no_cae_en_medio(self):
        from powergis.domain.target import TICKET_BRACKETS, _bracket

        assert _bracket("medio_alto", TICKET_BRACKETS) == (201, 1_000)
        assert _bracket("medio", TICKET_BRACKETS) == (51, 200)

    def test_el_formulario_llega_hasta_el_criterio_correcto(self):
        from powergis.domain.target import TargetProfile

        perfil = TargetProfile.from_mapping({"average_ticket": "medio_alto"})
        gasto = [c for c in perfil.criteria() if c.indicator == "eco.sector_spend"]

        assert gasto, "un ticket declarado tiene que generar criterio"
        assert (gasto[0].minimum, gasto[0].maximum) == (201, 1_000)

    def test_los_seis_tramos_del_formulario_dan_seis_rangos_distintos(self):
        from powergis.domain.target import TICKET_BRACKETS, _bracket

        claves = ["micro", "bajo", "medio", "medio_alto", "alto", "lujo"]
        rangos = [_bracket(k, TICKET_BRACKETS) for k in claves]

        assert None not in rangos
        assert len(set(rangos)) == len(claves), "dos tramos comparten rango"


class TestCriteriosQueNoSePuedenMedir:
    """Descartar un criterio en silencio convierte un hueco de datos en un
    Match% que parece simplemente bajo.

    Salió de mirar `/internal/coverage` en un motor real: 18 indicadores del
    catálogo no tienen colector, y siete de ellos son criterios del perfil
    —NSE entero, estructura familiar y postgrado—, el 29 % del peso. El
    cálculo era correcto (no inventa valores), pero nadie se enteraba.
    """

    def test_avisa_de_los_criterios_sin_datos(self, context):
        from powergis.domain.target import TargetProfile, match_scores

        context.warnings.clear()
        perfil = TargetProfile.from_mapping({
            "nse": ["a/b"],
            "family_status": "nido_lleno",
            "annual_income": "45-75k",
        })

        match_scores(context, perfil)

        avisos = [w for w in context.warnings if "no se han podido evaluar" in w.lower()]
        assert avisos, "un criterio declarado y no medido tiene que decirse"
        assert "%" in avisos[0], "el aviso dice cuánto peso se perdió"

    def test_sin_descartes_no_hay_aviso(self, context):
        """Un perfil que sólo pide lo que sí hay no debe generar ruido."""
        from powergis.domain.target import TargetProfile, match_scores

        context.warnings.clear()
        perfil = TargetProfile.from_mapping({"age_range": ["18-35"]})

        match_scores(context, perfil)

        assert not [w for w in context.warnings if "no se han podido evaluar" in w.lower()]

    def test_el_match_sigue_sin_inventar_valores(self, context):
        """El aviso se añade; la regla de no inventar no cambia."""
        from powergis.domain.target import TargetProfile, match_scores

        perfil = TargetProfile.from_mapping({"nse": ["a/b"]})
        scores = match_scores(context, perfil)

        assert all(v is None or 0 <= v <= 100 for v in scores.values())
