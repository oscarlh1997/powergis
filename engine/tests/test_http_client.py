"""El cliente HTTP compartido por los colectores.

Aquí se comprueba una sola cosa, pero es la que costó una tarde: **un cuerpo
que no es JSON tiene que decir por qué**.

El INE, cuando una consulta le viene grande, no devuelve un error: devuelve
200 con el cuerpo vacío. `httpx` lo traduce a un `JSONDecodeError` que dice
«Expecting value: line 1 column 1 (char 0)» y nada más — ni la URL, ni el
código, ni cuántos bytes llegaron. Con esa traza no se puede saber si la
fuente se cayó, si cambió de formato, si nos está limitando o si el cuerpo
venía vacío, que es justo lo que pasaba.
"""

from __future__ import annotations

import httpx
import pytest

from powergis.adapters.collectors.base import HttpClient
from powergis.domain.errors import CollectorError


def cliente(respuesta: httpx.Response) -> HttpClient:
    c = HttpClient("https://ejemplo.test")
    c._client = httpx.Client(
        transport=httpx.MockTransport(lambda _req: respuesta),
    )
    return c


class TestCuerpoQueNoEsJson:
    def test_un_cuerpo_vacio_explica_que_estaba_vacio(self):
        with pytest.raises(CollectorError) as exc:
            cliente(httpx.Response(200, text="")).get_json("VALORES_VARIABLE/19")

        mensaje = str(exc.value)
        assert "cuerpo vacío" in mensaje
        assert "VALORES_VARIABLE/19" in mensaje, "hay que saber qué se pidió"
        assert "0 bytes" in mensaje

    def test_una_pagina_de_error_html_se_ve_en_el_mensaje(self):
        html = "<html><body>Servicio temporalmente no disponible</body></html>"
        with pytest.raises(CollectorError) as exc:
            cliente(
                httpx.Response(200, text=html, headers={"content-type": "text/html"})
            ).get_json("VARIABLES")

        mensaje = str(exc.value)
        assert "text/html" in mensaje
        assert "Servicio temporalmente" in mensaje

    def test_el_ine_diciendo_que_la_operacion_no_existe(self):
        """El caso que de verdad pasó.

        La ruta llevaba `VALORES_VARIABLES` (plural) y esa operación no existe.
        El INE no contesta 404: contesta 200 con esta frase en texto plano. Sin
        este diagnóstico, lo único que se veía era «Expecting value: line 1
        column 1 (char 0)» — que apunta a un cuerpo vacío, no a una ruta mal
        escrita, y manda a buscar el fallo justo donde no está.
        """
        with pytest.raises(CollectorError) as exc:
            cliente(
                httpx.Response(200, text="La operación indicada no existe (VALORES_VARIABLES)")
            ).get_json("VALORES_VARIABLES/19")

        assert "La operación indicada no existe" in str(exc.value)

    def test_el_contexto_queda_disponible_para_el_log(self):
        """El mensaje es para el humano; el contexto, para el log estructurado."""
        with pytest.raises(CollectorError) as exc:
            cliente(httpx.Response(200, text="no soy json")).get_json("VARIABLES")

        ctx = exc.value.context
        assert ctx["status"] == 200
        assert ctx["length"] == len("no soy json")
        assert "no soy json" in ctx["body"]

    def test_un_json_valido_sigue_pasando_tal_cual(self):
        datos = cliente(httpx.Response(200, json=[{"Id": 19}])).get_json("VARIABLES")

        assert datos == [{"Id": 19}]
