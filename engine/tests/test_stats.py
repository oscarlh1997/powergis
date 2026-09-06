"""Estadística del dominio. Solo stdlib, así que corre en milisegundos."""

from __future__ import annotations

import math

import pytest

from powergis.domain import stats
from powergis.domain.enums import BreakMethod, Direction


class TestNulosNoSonCeros:
    """El error que convierte un informe en una mentira."""

    def test_clean_descarta_nulos_y_nan(self):
        assert stats.clean([1, None, 2, float("nan"), 3, float("inf")]) == [1.0, 2.0, 3.0]

    def test_media_ignora_nulos_no_los_cuenta_como_cero(self):
        assert stats.mean([10, None, 20]) == 15.0  # no 10.0

    def test_total_de_todo_nulo_es_none_no_cero(self):
        assert stats.total([None, None]) is None

    def test_safe_div_con_denominador_cero(self):
        assert stats.safe_div(10, 0) is None

    def test_relative_share_propaga_el_hueco(self):
        assert stats.relative_share(None, 100) is None
        assert stats.relative_share(25, None) is None


class TestPercentiles:
    def test_quantile_interpola(self):
        assert stats.quantile([1, 2, 3, 4], 0.5) == 2.5

    def test_percentile_of_extremos(self):
        pop = [1, 2, 3, 4, 5]
        assert stats.percentile_of(1, pop) == pytest.approx(10.0)
        assert stats.percentile_of(5, pop) == pytest.approx(90.0)

    def test_winsorize_recorta_el_outlier(self):
        values = [1, 2, 3, 4, 1000]
        out = stats.winsorize(values, 0.05, 0.95)
        assert max(v for v in out if v is not None) < 1000

    def test_winsorize_conserva_los_huecos(self):
        assert stats.winsorize([1, None, 3])[1] is None


class TestNormalizacion:
    def test_percentil_reparte_todo_el_rango(self):
        out = stats.normalize_percentile([10, 20, 30, 40])
        assert min(v for v in out if v is not None) < 20
        assert max(v for v in out if v is not None) > 80

    def test_direccion_invertida_para_lower_is_better(self):
        values = [10, 20, 30]
        alto = stats.normalize_percentile(values, Direction.HIGHER_IS_BETTER)
        bajo = stats.normalize_percentile(values, Direction.LOWER_IS_BETTER)
        assert alto[0] < alto[2]
        assert bajo[0] > bajo[2]

    def test_minmax_resiste_outliers_con_vallas_de_tukey(self):
        # Madrid aplastaría un min-max puro. Con percentiles 5-95 tampoco basta:
        # con 5 zonas el percentil 95 cae dentro del propio outlier.
        con_outlier = stats.normalize_minmax([10, 20, 30, 40, 100_000])
        sin_outlier = stats.normalize_minmax([10, 20, 30, 40])
        puro = stats.normalize_minmax([10, 20, 30, 40, 100_000], tukey_k=None)
        assert con_outlier[1] > 5, "el resto de zonas no puede quedar pegado a 0"
        assert puro[1] < 1, "el min-max puro sí colapsa: por eso no es el defecto"
        assert sin_outlier[1] == pytest.approx(33.33, abs=0.5)

    def test_vallas_de_tukey_detectan_el_outlier(self):
        _lo, hi = stats.tukey_fences([10, 20, 30, 40, 100_000])
        assert hi < 1_000
        assert stats.clip_outliers([10, 20, 30, 40, 100_000])[-1] == hi

    def test_valores_identicos_dan_50(self):
        assert stats.normalize_minmax([5, 5, 5]) == [50.0, 50.0, 50.0]

    def test_normalizacion_preserva_los_nulos(self):
        assert stats.normalize_percentile([1, None, 3])[1] is None


class TestRankings:
    def test_top_bottom_no_se_solapan_con_pocos_elementos(self):
        out = stats.top_bottom([("a", 1), ("b", 2), ("c", 3), ("d", 4)], n=3)
        assert not set(out["top"]) & set(out["bottom"])

    def test_top_bottom_respeta_la_direccion(self):
        items = [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5), ("f", 6)]
        alto = stats.top_bottom(items, 2, Direction.HIGHER_IS_BETTER)
        bajo = stats.top_bottom(items, 2, Direction.LOWER_IS_BETTER)
        assert alto["top"] == ["f", "e"]
        assert bajo["top"] == ["a", "b"]

    def test_los_nulos_no_entran_en_el_ranking(self):
        ranked = stats.rank_items([("a", 1), ("b", None), ("c", 3)])
        assert [k for k, _, _ in ranked] == ["c", "a"]


class TestIndicesCompuestos:
    def test_gini_de_reparto_perfecto_es_cero(self):
        assert stats.gini([10, 10, 10, 10]) == pytest.approx(0.0, abs=1e-9)

    def test_gini_crece_con_la_desigualdad(self):
        assert stats.gini([1, 1, 1, 100]) > stats.gini([10, 12, 11, 13])

    def test_shannon_maximo_con_reparto_uniforme(self):
        assert stats.shannon_diversity([5, 5, 5, 5]) == pytest.approx(1.0)

    def test_shannon_minimo_con_una_sola_categoria(self):
        assert stats.shannon_diversity([10]) == 0.0

    def test_herfindahl_monopolio(self):
        assert stats.herfindahl([100]) == pytest.approx(1.0)

    def test_dependency_ratio(self):
        assert stats.dependency_ratio(100, 500, 150) == pytest.approx(50.0)

    def test_dependency_ratio_sin_poblacion_activa(self):
        assert stats.dependency_ratio(100, 0, 150) is None


class TestCortesDeMapa:
    def test_quantiles_devuelve_classes_mas_uno(self):
        breaks = stats.compute_breaks(list(range(100)), classes=5)
        assert len(breaks) == 6
        assert breaks == sorted(breaks)

    def test_equal_interval_reparte_uniformemente(self):
        breaks = stats.compute_breaks([0, 100], classes=4, method=BreakMethod.EQUAL_INTERVAL)
        assert breaks == [0.0, 25.0, 50.0, 75.0, 100.0]

    def test_valores_identicos_no_revientan(self):
        assert stats.compute_breaks([7, 7, 7]) == [7.0, 7.0]

    def test_sin_datos_devuelve_lista_vacia(self):
        assert stats.compute_breaks([None, None]) == []

    def test_stddev_centrado_en_la_media(self):
        breaks = stats.compute_breaks([1, 2, 3, 4, 5], classes=4, method=BreakMethod.STDDEV)
        assert len(breaks) == 5
        assert math.isclose(breaks[2], 3.0, abs_tol=0.01)
