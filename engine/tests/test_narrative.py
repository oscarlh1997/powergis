"""Verificación de cifras en los textos de IA.

El peor fallo posible en un informe de pago es una cifra inventada. Esta
comprobación es barata y lo hace imposible de publicar.
"""

from __future__ import annotations

from powergis.adapters.llm.narrative import (
    NarrativeService,
    _template_summary,
    _template_zone,
    allowed_numbers,
    extract_numbers,
    facts_hash,
    verify_numbers,
)

FACTS = {
    "zona": "Madrid",
    "posicion": 1,
    "score": 83.2,
    "categoria": "Excelente",
    "dimensiones": {"economico": 88.0, "demografico": 79.5},
    "factores": [
        {"code": "dem.pop.segment", "label": "Público objetivo",
         "contribution": 0.31, "direction": 1},
        {"code": "cmp.density_km2", "label": "Densidad competitiva",
         "contribution": -0.12, "direction": -1},
    ],
}


class TestExtraccionDeCifras:
    def test_detecta_decimales_espanoles(self):
        assert 83.2 in extract_numbers("La puntuación es 83,2 sobre 100")

    def test_detecta_miles_con_punto(self):
        assert 1_234_567 in extract_numbers("Hay 1.234.567 habitantes")

    def test_texto_sin_cifras(self):
        assert extract_numbers("Zona con buen potencial comercial") == []


class TestVerificacion:
    def test_texto_fiel_pasa(self):
        texto = "Madrid obtiene 83,2 puntos y ocupa la posición 1."
        assert verify_numbers(texto, FACTS) == []

    def test_cifra_inventada_se_detecta(self):
        texto = "Madrid crecerá un 47,3% el próximo año."
        assert 47.3 in verify_numbers(texto, FACTS)

    def test_dimension_valida_pasa(self):
        assert verify_numbers("Dimensión económica: 88", FACTS) == []

    def test_redondeo_razonable_se_acepta(self):
        assert verify_numbers("Puntuación de 83 puntos", FACTS) == []

    def test_los_numeros_de_uso_comun_no_se_castigan(self):
        assert verify_numbers("Las 3 mejores zonas de las 5 analizadas", FACTS) == []

    def test_allowed_numbers_recorre_estructuras_anidadas(self):
        allowed = allowed_numbers(FACTS)
        assert 0.31 in allowed
        assert 88.0 in allowed


class TestServicioConLlmSimulado:
    class _Cliente:
        enabled = True

        def __init__(self, payload):
            self.payload = payload
            self.llamadas = 0

        def complete_json(self, *args, **kwargs):
            self.llamadas += 1
            return self.payload

    def test_texto_valido_se_devuelve(self):
        cliente = self._Cliente({
            "resumen": "Madrid obtiene 83,2 puntos.",
            "fortalezas": ["Público objetivo amplio"],
            "riesgos": [],
        })
        service = NarrativeService(client=cliente)
        assert "83,2" in service.zone_narrative(FACTS)
        assert cliente.llamadas == 1

    def test_texto_con_cifra_inventada_se_rechaza_y_cae_a_plantilla(self):
        cliente = self._Cliente({
            "resumen": "Madrid crecerá un 47,3% y triplicará ventas en 2031.",
            "fortalezas": [],
            "riesgos": [],
        })
        service = NarrativeService(client=cliente)
        result = service.zone_full(FACTS)
        assert result["generated_by"] == "plantilla"
        assert cliente.llamadas == 2, "se reintenta una vez antes de rendirse"
        assert "47,3" not in result["resumen"]

    def test_salida_que_no_valida_cae_a_plantilla(self):
        cliente = self._Cliente({"campo_inventado": True})
        result = NarrativeService(client=cliente).zone_full(FACTS)
        assert result["generated_by"] == "plantilla"

    def test_sin_api_key_no_se_rompe_el_informe(self):
        service = NarrativeService()  # NullLlmClient
        result = service.zone_full(FACTS)
        assert result["resumen"]
        assert result["generated_by"] == "plantilla"


class TestPlantillasDeterministas:
    def test_la_plantilla_de_zona_solo_usa_cifras_reales(self):
        result = _template_zone(FACTS)
        assert verify_numbers(result["resumen"], FACTS) == []

    def test_la_plantilla_de_resumen_solo_usa_cifras_reales(self):
        facts = {"ambito": "Comunidad de Madrid", "zonas_comparadas": 4,
                 "mejores_zonas": [{"zona": "Madrid"}], "peores_zonas": [{"zona": "Ávila"}]}
        result = _template_summary(facts)
        assert verify_numbers(result["resumen"], facts) == []
        assert "Madrid" in result["resumen"]


class TestCache:
    def test_el_hash_es_de_los_hechos_no_del_proyecto(self):
        """Dos usuarios con los mismos hechos comparten texto. Ahí está el ahorro."""
        a = facts_hash(FACTS, "zone", "modelo-x")
        b = facts_hash(dict(reversed(list(FACTS.items()))), "zone", "modelo-x")
        assert a == b

    def test_hechos_distintos_dan_hash_distinto(self):
        otros = {**FACTS, "score": 40.0}
        assert facts_hash(FACTS, "zone", "m") != facts_hash(otros, "zone", "m")

    def test_el_modelo_forma_parte_de_la_clave(self):
        assert facts_hash(FACTS, "zone", "rapido") != facts_hash(FACTS, "zone", "grande")

    def test_se_sirve_desde_cache_sin_llamar_al_llm(self):
        class Cache:
            def __init__(self):
                self.store = {}

            def get(self, key):
                return self.store.get(key)

            def set(self, key, value, ttl=None):
                self.store[key] = value

        cliente = TestServicioConLlmSimulado._Cliente({
            "resumen": "Madrid obtiene 83,2 puntos.", "fortalezas": [], "riesgos": [],
        })
        cache = Cache()
        service = NarrativeService(client=cliente, cache=cache)
        service.zone_full(FACTS)
        service.zone_full(FACTS)
        assert cliente.llamadas == 1
