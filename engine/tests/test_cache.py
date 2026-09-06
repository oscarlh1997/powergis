"""El respaldo sin Redis.

`NullCache` es lo que se usa cuando Redis no está disponible. No tenía
pruebas, y por eso pasó desapercibido durante meses que **le faltaba
`unlock()`** mientras `lock()` devolvía `True`.

El efecto en producción era el peor posible: la tarea de informes tomaba el
cerrojo, hacía el trabajo, y al soltarlo en su bloque `finally` lanzaba
`AttributeError`. Al estar en un `finally`, ese error SUSTITUYE al que
viniera propagándose — así que si el informe había fallado por otra cosa, el
motivo real se perdía y el worker moría diciendo algo sin relación.

La prueba que lo habría cazado es la primera de aquí: que las dos mitades del
cerrojo existan.
"""

from __future__ import annotations

import pytest

from powergis.adapters.cache import NullCache
from powergis.domain.ports import CachePort


@pytest.fixture
def cache():
    return NullCache()


class TestCerrojo:
    def test_lo_que_se_toma_se_puede_soltar(self, cache):
        """Un cerrojo que se toma y no se puede soltar no es un cerrojo."""
        assert cache.lock("informe:abc") is True
        cache.unlock("informe:abc")  # no debe lanzar

    def test_soltar_un_cerrojo_que_no_se_tomo_no_falla(self, cache):
        """Se llama desde un `finally`, así que puede ejecutarse en caminos
        donde el cerrojo nunca llegó a tomarse."""
        cache.unlock("nunca-tomado")

    def test_cumple_el_puerto(self, cache):
        """Si el puerto declara un método, la implementación lo tiene.

        `CachePort` es `runtime_checkable`, así que esto comprueba de verdad
        que no falta ninguno de los nombres del contrato.
        """
        assert isinstance(cache, CachePort)


class TestComportamientoNulo:
    def test_no_guarda_nada(self, cache):
        cache.set("k", {"v": 1})
        assert cache.get("k") is None

    def test_borrar_es_inocuo(self, cache):
        cache.delete("k")
        assert cache.delete_prefix("informe:") == 0

    def test_no_limita_el_uso(self, cache):
        """Sin Redis no hay contador, y la respuesta tiene que dejar pasar.

        Devolver un número alto aquí bloquearía a todos los clientes cada vez
        que Redis parpadea, que es peor que no limitar.
        """
        assert cache.incr_window("user:7:h", 3600) == 0

    def test_dice_que_no_esta_vivo(self, cache):
        """`ping()` en False es lo que permite a `/ready` reportar degradado
        en vez de fingir que todo va bien."""
        assert cache.ping() is False
