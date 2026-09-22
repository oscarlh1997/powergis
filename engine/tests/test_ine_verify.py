"""El verificador del INE.

Estas pruebas no tocan la red. Lo que se comprueba aquí es que el verificador
DETECTA los cinco modos en que el mapeo del INE se rompe en silencio:

  1. el INE renumera la tabla al republicar   → UNREACHABLE
  2. la tabla existe pero se vació            → EMPTY
  3. el nombre de las series cambia           → NO_MATCH
  4. la tabla pasa a ser provincial           → LEVEL_MISMATCH
  5. la tabla sigue viva pero es la edición vieja → STALE

Ninguno de los cinco lanza una excepción en producción. Los cuatro primeros
devuelven cero hechos y el informe sale con huecos que parecen secreto
estadístico. El quinto es peor: el informe sale COMPLETO, con datos de hace
años y sin un solo hueco que invite a sospechar.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pytest

from powergis.adapters.collectors.ine import IneCollector, TableSpec
from powergis.domain.errors import CollectorError


class FakeClient:
    """Devuelve lo que se le diga por ID de tabla. Cuenta las llamadas."""

    def __init__(self, tables: dict[str, object]) -> None:
        self.tables = tables
        self.calls: list[str] = []
        #: La ruta COMPLETA, no sólo el ID. El nombre de la operación es parte
        #: del contrato con el INE y se equivocó una vez.
        self.rutas: list[str] = []

    def get_json(self, path: str, params: dict | None = None) -> object:
        table_id = path.rsplit("/", 1)[-1]
        self.calls.append(table_id)
        self.rutas.append(path)
        payload = self.tables.get(table_id)
        if payload is None:
            raise CollectorError("tabla inexistente", table=table_id)
        return payload


def serie(name: str) -> dict:
    return {"Nombre": name, "Data": [{"Valor": 1.0, "Anyo": 2024}]}


MUNICIPALES = [
    serie("28079 Madrid. Total. Personas."),
    serie("28079 Madrid. Hombres. Personas."),
    serie("28079 Madrid. Mujeres. Personas."),
    serie("08019 Barcelona. Total. Personas."),
]

PROVINCIALES = [
    serie("28 Madrid. Tasa de natalidad."),
    serie("08 Barcelona. Tasa de natalidad."),
]


@pytest.fixture
def collector():
    def _make(tables: dict[str, object]) -> tuple[IneCollector, FakeClient]:
        client = FakeClient(tables)
        return IneCollector(client=client), client

    return _make


class TestVerificador:
    def test_una_tabla_correcta_pasa(self, collector):
        ine, _ = collector({"2879": MUNICIPALES})
        spec = TableSpec("2879", "dem.pop.total", "municipio")

        report = ine.verify([spec])

        assert report["broken"] == 0
        assert report["results"][0]["status"] == "OK"
        assert report["results"][0]["detected_level"] == "municipio"

    def test_una_tabla_renumerada_se_detecta(self, collector):
        """El caso real: el INE republica la operación y cambia el ID."""
        ine, _ = collector({"99999": MUNICIPALES})
        spec = TableSpec("2879", "dem.pop.total", "municipio")

        report = ine.verify([spec])

        assert report["broken"] == 1
        assert report["results"][0]["status"] == "UNREACHABLE"

    def test_una_tabla_vacia_no_pasa_por_buena(self, collector):
        ine, _ = collector({"2879": []})
        spec = TableSpec("2879", "dem.pop.total", "municipio")

        assert ine.verify([spec])["results"][0]["status"] == "EMPTY"

    def test_un_filtro_que_ya_no_acierta_se_detecta(self, collector):
        """`match` son subcadenas: si el INE renombra la serie, deja de acertar
        sin dar ningún error."""
        ine, _ = collector({"2879": MUNICIPALES})
        spec = TableSpec("2879", "dem.sex.men", "municipio", match=("varones",))

        row = ine.verify([spec])["results"][0]

        assert row["status"] == "NO_MATCH"
        assert row["matched"] == 0
        # Y enseña qué HAY, que es lo que permite arreglarlo.
        assert any("Hombres" in s for s in row["sample"])

    def test_un_filtro_que_acierta_cuenta_las_series(self, collector):
        ine, _ = collector({"2879": MUNICIPALES})
        spec = TableSpec("2879", "dem.sex.men", "municipio", match=("hombres",))

        row = ine.verify([spec])["results"][0]

        assert row["status"] == "OK"
        assert row["matched"] == 1

    def test_una_tabla_con_el_nivel_equivocado_se_detecta(self, collector):
        """Pedir municipios y recibir provincias arruina el informe entero:
        el ámbito consultado no encuentra a sus hijos."""
        ine, _ = collector({"1470": PROVINCIALES})
        spec = TableSpec("1470", "dem.birth.rate", "municipio", match=("natalidad",))

        row = ine.verify([spec])["results"][0]

        assert row["status"] == "LEVEL_MISMATCH"
        assert row["detected_level"] == "provincia"

    def test_el_nivel_provincial_declarado_es_correcto(self, collector):
        ine, _ = collector({"1470": PROVINCIALES})
        spec = TableSpec("1470", "dem.birth.rate", "provincia", match=("natalidad",))

        assert ine.verify([spec])["results"][0]["status"] == "OK"

    def test_cada_tabla_se_descarga_una_sola_vez(self, collector):
        """16 specs son 6 tablas. Descargar una tabla municipal del INE por
        cada indicador sería absurdo."""
        ine, client = collector({"2879": MUNICIPALES})
        specs = [
            TableSpec("2879", "dem.pop.total", "municipio"),
            TableSpec("2879", "dem.sex.men", "municipio", match=("hombres",)),
            TableSpec("2879", "dem.sex.women", "municipio", match=("mujeres",)),
        ]

        ine.verify(specs)

        assert client.calls == ["2879"]

    def test_el_verificador_no_se_cae_nunca(self, collector):
        """Si el verificador explota, no verifica nada. Cualquier excepción
        del transporte tiene que convertirse en un veredicto."""

        class Explosive(FakeClient):
            def get_json(self, path, params=None):
                raise RuntimeError("el socket se fue")

        ine = IneCollector(client=Explosive({}))
        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["results"][0]["status"] == "UNREACHABLE"


class TestPadronDeMunicipios:
    """La semilla del repositorio llega a provincia. Los ~8.100 municipios se
    cargan desde el INE, y esa carga es el cimiento del almacén municipal: si
    entra mal, la ingestión del Padrón descarta cada fila en silencio."""

    VARIABLES: ClassVar[list[dict]] = [
        {"Id": 70, "Nombre": "Provincias"},
        {"Id": 19, "Nombre": "Municipios"},
        {"Id": 349, "Nombre": "Municipios de residencia"},
        {"Id": 3, "Nombre": "Sexo"},
    ]

    VALORES: ClassVar[list[dict]] = [
        {"Codigo": "28079", "Nombre": "Madrid"},
        {"Codigo": "08019", "Nombre": "Barcelona"},
        {"Codigo": "46250", "Nombre": "València"},
        {"Codigo": "28079", "Nombre": "Madrid"},          # duplicado
        {"Codigo": "28", "Nombre": "Madrid (provincia)"},  # no es municipio
        {"Codigo": "ES", "Nombre": "Total Nacional"},      # tampoco
    ]

    def test_encuentra_la_variable_por_nombre_no_por_id(self, collector):
        """Los IDs de variable del INE no son estables; el nombre sí."""
        ine, _ = collector({"VARIABLES": self.VARIABLES})

        assert ine.municipality_variable_id() == 19

    def test_prefiere_la_variable_generica_a_una_variante(self, collector):
        """'Municipios' es la lista; 'Municipios de residencia' es otra cosa."""
        ine, _ = collector({"VARIABLES": list(reversed(self.VARIABLES))})

        assert ine.municipality_variable_id() == 19

    def test_si_el_ine_no_expone_municipios_falla_en_alto(self, collector):
        ine, _ = collector({"VARIABLES": [{"Id": 3, "Nombre": "Sexo"}]})

        with pytest.raises(CollectorError):
            ine.municipality_variable_id()

    def test_solo_acepta_codigos_de_cinco_digitos(self, collector):
        ine, _ = collector({"VARIABLES": self.VARIABLES, "19": self.VALORES})

        municipios = ine.municipalities(19)

        assert [m["ine_code"] for m in municipios] == ["28079", "08019", "46250"]

    def test_la_provincia_se_deriva_del_codigo_no_se_pregunta(self, collector):
        """Los dos primeros dígitos SON la provincia por definición del INE.
        Derivarla evita depender de un campo que puede venir vacío."""
        ine, _ = collector({"VARIABLES": self.VARIABLES, "19": self.VALORES})

        municipios = {m["ine_code"]: m["province_code"] for m in ine.municipalities(19)}

        assert municipios["28079"] == "28"   # Madrid
        assert municipios["08019"] == "08"   # Barcelona
        assert municipios["46250"] == "46"   # Valencia

    def test_una_variable_equivocada_no_pasa_por_carga_buena(self, collector):
        ine, _ = collector({"VARIABLES": self.VARIABLES, "3": [{"Codigo": "1", "Nombre": "Hombres"}]})

        with pytest.raises(CollectorError):
            ine.municipalities(3)

    def test_la_operacion_del_ine_es_en_singular(self):
        """Un error de una sola letra que no daba error.

        `VALORES_VARIABLES` no existe, pero el INE no contesta 404: contesta
        **200** con el texto «La operación indicada no existe (…)». Para el
        cliente HTTP eso es una respuesta buena, así que el fallo sólo salía al
        leerla como JSON, sin decir qué se había pedido. Coste real: el almacén
        se quedó sin nivel municipal.
        """
        assert IneCollector.OP_VALORES == "VALORES_VARIABLE"

    def test_pide_exactamente_la_ruta_que_el_ine_publica(self, collector):
        ine, cliente = collector({"VARIABLES": self.VARIABLES, "19": self.VALORES})

        ine.municipalities(19)

        assert cliente.rutas[-1] == "VALORES_VARIABLE/19"


class TestListaQueNoCabe:
    """Los ~8.100 municipios son la lista más larga que publica el INE, y es
    justo la que a veces no le cabe: contesta 200 con el cuerpo vacío. El
    colector reintenta paginado antes de rendirse.

    Sin esto la carga muere con un `JSONDecodeError` pelado y el almacén se
    queda sin nivel municipal, que es la avería que deja los informes vacíos
    sin dar un solo error.
    """

    @staticmethod
    def municipio(n: int) -> dict:
        return {"Codigo": f"{28000 + n:05d}", "Nombre": f"Pueblo {n}"}

    def cliente_paginado(self, total: int, *, entero: object):
        """Falla o se vacía de una vez; responde bien con `?page=`."""
        todos = [self.municipio(n) for n in range(total)]

        class Paginado:
            calls: ClassVar[list] = []

            def get_json(self, path, params=None):
                Paginado.calls.append((path, params))
                if not params or "page" not in params:
                    if isinstance(entero, Exception):
                        raise entero
                    return entero
                inicio = (params["page"] - 1) * IneCollector.PAGE_SIZE
                return todos[inicio : inicio + IneCollector.PAGE_SIZE]

        return IneCollector(client=Paginado())

    def test_un_cuerpo_vacio_no_hunde_la_carga(self):
        """El modo de fallo real observado en producción."""
        ine = self.cliente_paginado(
            1200, entero=CollectorError("el cuerpo no es JSON", status=200)
        )

        assert len(ine.municipalities(19)) == 1200

    def test_una_lista_vacia_tambien_dispara_el_paginado(self):
        """200 con `[]` es el mismo problema con otra cara."""
        ine = self.cliente_paginado(600, entero=[])

        assert len(ine.municipalities(19)) == 600

    def test_no_pagina_si_no_hace_falta(self):
        """El camino barato sigue siendo el camino por defecto."""
        ine = self.cliente_paginado(3, entero=[self.municipio(n) for n in range(3)])

        ine.municipalities(19)

        assert all(p is None or "page" not in p for _, p in type(ine._client).calls)

    def test_si_el_ine_ignora_page_no_se_queda_en_bucle(self):
        """Devolver siempre la misma página es indistinguible de paginar bien
        salvo por esto: la segunda no aporta nada nuevo."""
        pagina = [self.municipio(n) for n in range(IneCollector.PAGE_SIZE)]

        class Terco:
            paginas = 0

            def get_json(self, path, params=None):
                if not params or "page" not in params:
                    return []
                Terco.paginas += 1
                return pagina

        ine = IneCollector(client=Terco())
        municipios = ine.municipalities(19)

        assert len(municipios) == IneCollector.PAGE_SIZE
        assert Terco.paginas == 2, "debe parar en cuanto una página no aporta nada"

    def test_si_fallan_los_dos_caminos_el_error_dice_los_dos(self):
        class Muerto:
            def get_json(self, path, params=None):
                raise CollectorError("el cuerpo no es JSON")

        with pytest.raises(CollectorError) as exc:
            IneCollector(client=Muerto()).municipalities(19)

        mensaje = str(exc.value)
        assert "Entero:" in mensaje and "Paginado:" in mensaje
        assert "curl" in mensaje, "el error debe traer cómo reproducirlo a mano"


class TestAntiguedad:
    """El quinto modo de fallo, y el que se coló hasta producción.

    Una tabla puede responder, traer series de sobra, encajar con los filtros y
    tener el nivel correcto — y ser la edición de hace seis años. Pasa las
    cuatro comprobaciones anteriores, el informe sale entero, y los números son
    de otra década. Nada lo delataba: el verificador nunca miraba el año.
    """

    @staticmethod
    def serie_de(ano: int) -> dict:
        return {
            "Nombre": "28079 Madrid. Total. Personas.",
            "Data": [{"Valor": 1.0, "Anyo": ano}],
        }

    def test_una_tabla_reciente_pasa(self, collector):
        actual = date.today().year - 1
        ine, _ = collector({"2879": [self.serie_de(actual)]})

        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["results"][0]["status"] == "OK"
        assert report["results"][0]["year"] == actual

    def test_el_retraso_normal_del_ine_no_es_un_fallo(self, collector):
        """El Padrón de un año se publica al siguiente; dos años de diferencia
        son lo habitual y no significan nada."""
        ine, _ = collector({"2879": [self.serie_de(date.today().year - 2)]})

        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["results"][0]["status"] == "OK"
        assert report["stale"] == 0

    def test_una_edicion_vieja_se_marca(self, collector):
        ine, _ = collector({"2879": [self.serie_de(date.today().year - 7)]})

        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["results"][0]["status"] == "STALE"
        assert report["stale"] == 1
        assert str(date.today().year - 7) in report["results"][0]["detail"]

    def test_vieja_no_es_rota(self, collector):
        """`STALE` se cuenta aparte: la tabla responde y da datos, así que
        seguir con esa edición o buscar la nueva es una decisión de una
        persona. Si contara como rota, el verificador fallaría por algo que a
        veces es correcto — y un verificador que falla cuando no debe se acaba
        ignorando entero."""
        ine, _ = collector({"2879": [self.serie_de(date.today().year - 7)]})

        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["broken"] == 0

    def test_el_detalle_dice_cómo_arreglarlo(self, collector):
        ine, _ = collector({"2879": [self.serie_de(2015)]})

        detalle = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])["results"][0]["detail"]

        assert "ine-discover" in detalle
        assert "INE_TABLE_DEM_POP_TOTAL" in detalle

    def test_una_tabla_sin_fechas_no_se_marca_por_las_dudas(self, collector):
        """Sin año no se puede afirmar que esté vieja. Se informa con '?' y se
        deja pasar: inventar una antigüedad sería peor que no darla."""
        ine, _ = collector({"2879": [{"Nombre": "28079 Madrid. Total.", "Data": []}]})

        report = ine.verify([TableSpec("2879", "dem.pop.total", "municipio")])

        assert report["results"][0]["year"] is None
        assert report["results"][0]["status"] == "OK"

    def test_se_queda_con_el_año_mas_reciente_de_la_tabla(self):
        filas = [
            {"Data": [{"Anyo": 2019}, {"Anyo": 2024}]},
            {"Data": [{"Anyo": 2021}]},
        ]
        assert IneCollector._ultimo_ano(filas) == 2024

    def test_lee_el_año_aunque_venga_dentro_de_un_texto(self):
        assert IneCollector._ultimo_ano([{"Data": [{"Fecha": "1 de enero de 2023"}]}]) == 2023


class TestDeteccionDeNivel:
    def test_ignora_el_total_nacional_de_la_primera_fila(self):
        """Las tablas del INE suelen abrir con el total nacional; si se mirara
        sólo la primera serie, el nivel saldría mal siempre."""
        names = ["Total Nacional. Personas."] + [s["Nombre"] for s in MUNICIPALES]

        assert IneCollector._detect_level(names) == "municipio"

    def test_sin_codigos_no_inventa_un_nivel(self):
        assert IneCollector._detect_level(["Total Nacional.", "Ambos sexos."]) is None


class TestResolucionDeTabla:
    """Elegir la edición vigente en vez de arrastrar la que se escribió.

    El ID de tabla es lo que el INE renumera al republicar; el de la operación
    es estable. Declarando la operación, el motor pregunta cuál es la tabla
    vigente y deja de envejecer solo.

    Las formas de aquí son las REALES, sacadas de `TABLAS_OPERACION`: las
    operaciones de población (22, 450) traen `Anyo_Periodo_fin`, y las
    demográficas y de renta (33, 353, 10) traen `FechaRef_fin`. Un resolutor
    que sólo mirase uno de los dos funcionaría en la mitad del catálogo.
    """

    @staticmethod
    def tabla(id_, nombre, *, fin=None, ini=None, ref=None, mod=0):
        """Un registro con la forma EXACTA de TABLAS_OPERACION.

        Los años vienen como texto —`"2021"`, no 2021— y `FechaRef_fin` suele
        ser la cadena `"null"`, no un nulo. Las dos cosas parecen detalles y
        las dos rompieron el resolutor.
        """
        t = {"Id": id_, "Nombre": nombre, "Ultima_Modificacion": mod}
        if fin is not None:
            t["Anyo_Periodo_fin"] = str(fin)
        if ini is not None:
            t["Anyo_Periodo_ini"] = str(ini)
        if ref is not None:
            t["FechaRef_fin"] = ref
        return t

    def resolver(self, spec, tablas):
        class Cliente:
            def get_json(self, path, params=None):
                assert path.startswith("TABLAS_OPERACION/")
                return tablas
        return IneCollector(client=Cliente()).resolver_tabla(spec)

    def test_elige_la_de_datos_mas_recientes(self):
        spec = TableSpec("2879", "dem.pop.total", "municipio",
                         operacion=22, table_match=("poblacion por municipios",))
        tablas = [
            self.tabla(2855, "Albacete: Población por municipios y sexo.", fin=2019),
            self.tabla(2870, "Madrid: Población por municipios y sexo.", fin=2025),
            self.tabla(2860, "Cuenca: Población por municipios y sexo.", fin=2022),
        ]
        elegida, motivo = self.resolver(spec, tablas)
        assert elegida == "2870"
        assert "2025" in motivo

    def test_lee_tambien_las_operaciones_con_fecharef(self):
        spec = TableSpec("1470", "dem.birth.rate", "provincia",
                         operacion=33, table_match=("natalidad",))
        tablas = [
            self.tabla(1381, "Tasa Bruta de Natalidad.", ref="2018-12-31"),
            self.tabla(1382, "Tasa Bruta de Natalidad.", ref="2024-12-31"),
        ]
        assert self.resolver(spec, tablas)[0] == "1382"

    def test_los_anos_llegan_como_texto(self):
        """`"Anyo_Periodo_fin": "2021"`. Filtrarlos por tipo entero los
        descartaba todos, y entonces no quedaba ninguna fecha con la que
        ordenar: las listas salían en el orden en que venían."""
        assert IneCollector._recencia({"Anyo_Periodo_fin": "2021"})[0] == 2021

    def test_fecharef_suele_ser_la_cadena_null(self):
        """No `None`: el texto literal. Está así en las operaciones 33 y 353."""
        assert IneCollector._recencia({"FechaRef_fin": "null"})[0] == 0

    def test_el_ano_de_inicio_no_cuenta_como_frescura(self):
        """`Anyo_Periodo_ini` es cuándo EMPIEZA la serie. Usarlo pondría
        arriba la tabla que arranca más tarde, que no dice nada sobre cuál
        trae el dato más nuevo."""
        vieja_larga = {"Anyo_Periodo_ini": "1975", "Anyo_Periodo_fin": "2025"}
        nueva_corta = {"Anyo_Periodo_ini": "2015", "Anyo_Periodo_fin": "2019"}
        assert IneCollector._recencia(vieja_larga) > IneCollector._recencia(nueva_corta)

    def test_sin_ano_manda_la_ultima_modificacion(self):
        """Es lo único que queda en las operaciones 33 y 353."""
        antigua = {"FechaRef_fin": "null", "Ultima_Modificacion": 1_600_000_000_000}
        reciente = {"FechaRef_fin": "null", "Ultima_Modificacion": 1_763_546_400_000}
        assert IneCollector._recencia(reciente) > IneCollector._recencia(antigua)

    def test_a_igualdad_de_todo_gana_el_id_mayor(self):
        """Heurística de último recurso, no un dato: el INE asigna los
        identificadores crecientes, así que entre dos tablas idénticas en
        nombre y fecha la de número mayor suele ser la republicada. Sin esto
        el desempate sería el orden de llegada, que no significa nada.

        Es el caso real de `1470` frente a `67223`, las dos «Tasa Bruta de
        Natalidad por provincia».
        """
        spec = TableSpec("1470", "dem.birth.rate", "provincia",
                         operacion=33, table_match=("natalidad por provincia",))
        mod = 1_763_546_400_000
        tablas = [
            self.tabla(1470, "Tasa Bruta de Natalidad por provincia", ref="null", mod=mod),
            self.tabla(67223, "Tasa Bruta de Natalidad por provincia", ref="null", mod=mod),
        ]
        assert self.resolver(spec, tablas)[0] == "67223"

    def test_la_etiqueta_distingue_el_dato_de_la_modificacion(self):
        """«2021» es el año del dato; «mod. 2025» es cuándo se tocó la tabla.
        Enseñarlos igual invitaría a leer una fecha de retoque como si fuera
        la frescura del dato."""
        assert IneCollector.etiqueta_fecha({"Anyo_Periodo_fin": "2021"}) == "2021"
        assert IneCollector.etiqueta_fecha(
            {"FechaRef_fin": "null", "Ultima_Modificacion": 1_763_546_400_000}
        ).startswith("mod. 202")
        assert IneCollector.etiqueta_fecha({}) == "?"

    def test_el_nombre_filtra_antes_que_la_fecha(self):
        """Lo que hace peligroso este resolutor: la 22 tiene una tabla POR
        PROVINCIA. Sin filtrar por nombre elegiría la más reciente de
        cualquiera, y el informe saldría con datos de otra provincia sin dar
        un solo error."""
        spec = TableSpec("2879", "dem.pop.total", "municipio",
                         operacion=22, table_match=("madrid",))
        tablas = [
            self.tabla(2855, "Albacete: Población por municipios y sexo.", fin=2025),
            self.tabla(2870, "Madrid: Población por municipios y sexo.", fin=2024),
        ]
        assert self.resolver(spec, tablas)[0] == "2870"

    def test_la_ultima_modificacion_solo_desempata(self):
        """Una tabla vieja retocada ayer no es reciente."""
        spec = TableSpec("x", "dem.pop.total", "municipio", operacion=22)
        tablas = [
            self.tabla(9999, "A", fin=2019, mod=9_999_999_999_999),
            self.tabla(1, "B", fin=2025, mod=1),
        ]
        assert self.resolver(spec, tablas)[0] == "1"

    def test_sin_operacion_declarada_no_cambia_nada(self):
        """Los specs que no la declaran se comportan igual que siempre."""
        spec = TableSpec("2879", "dem.pop.total", "municipio")
        assert self.resolver(spec, [])[0] == "2879"

    def test_si_el_ine_no_responde_se_sigue_con_la_semilla(self):
        """Una carga que se niega a empezar porque el descubrimiento falló es
        peor que una carga con la tabla de ayer."""
        class Muerto:
            def get_json(self, path, params=None):
                raise CollectorError("el INE no responde")

        spec = TableSpec("2879", "dem.pop.total", "municipio", operacion=22)
        elegida, motivo = IneCollector(client=Muerto()).resolver_tabla(spec)
        assert elegida == "2879"
        assert "no responde" in motivo

    def test_si_nada_encaja_se_sigue_con_la_semilla(self):
        spec = TableSpec("2879", "dem.pop.total", "municipio",
                         operacion=22, table_match=("algo que no existe",))
        elegida, motivo = self.resolver(spec, [self.tabla(1, "Otra cosa", fin=2025)])
        assert elegida == "2879"
        assert "ninguna tabla" in motivo

    def test_la_variable_de_entorno_manda_sobre_todo(self, monkeypatch):
        """Es la vía de escape cuando la resolución se equivoca. Si el
        descubrimiento la ignorase, quien la puso se quedaría sin forma de
        corregir nada."""
        monkeypatch.setenv("INE_TABLE_DEM_POP_TOTAL", "12345")
        spec = TableSpec("2879", "dem.pop.total", "municipio",
                         operacion=22, table_match=("poblacion",))
        elegida, motivo = self.resolver(spec, [self.tabla(999, "Población", fin=2030)])
        assert elegida == "12345"
        assert "INE_TABLE_DEM_POP_TOTAL" in motivo

    def test_el_listado_se_pide_una_vez_por_operacion(self):
        llamadas = []

        class Contador:
            def get_json(self, path, params=None):
                llamadas.append(path)
                return [{"Id": 7, "Nombre": "Población por municipios", "Anyo_Periodo_fin": 2025}]

        ine = IneCollector(client=Contador())
        for _ in range(3):
            ine.resolver_tabla(
                TableSpec("2879", "dem.pop.total", "municipio",
                          operacion=22, table_match=("poblacion",))
            )
        assert llamadas == ["TABLAS_OPERACION/22"]


class TestSeriesSinCodigo:
    """Casar series con geografías cuando el INE no pone el código.

    Descubierto mirando cinco tablas reales: **no hay un formato, hay tres**, y
    los tres están en tablas que el motor usa.

        '28079 Madrid. Total. Personas.'    código delante
        'Ababuj. Total. Total habitantes.'  sólo nombre, primer campo
        'Fecundidad. Albacete.'             sólo nombre, SEGUNDO campo

    El colector miraba únicamente el primer campo y sólo entendía el código.
    Con eso, la tabla municipal nacional del padrón (24.414 series) y la de
    natalidad provincial (53) no aportaban ni un dato — sin lanzar nada, sin
    un error, sin nada que mirar.
    """

    @staticmethod
    def geo(geo_id, level, code, name):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo
        return Geo(geo_id=geo_id, level=GeoLevel(level), ine_code=code,
                   name=name, parent_id=None)

    def indice(self, *geos):
        return IneCollector._indice_por_nombre(list(geos))

    def resolver(self, serie, geos, level=None):
        por_codigo = {g.ine_code: g for g in geos}
        return IneCollector._geo_of(serie, por_codigo, self.indice(*geos), level)

    def test_el_codigo_delante_sigue_funcionando(self):
        madrid = self.geo(1, "municipio", "28079", "Madrid")
        g = self.resolver("28079 Madrid. Total. Personas.", [madrid], "municipio")
        assert g is madrid

    def test_el_nombre_solo_en_el_primer_campo(self):
        """Formato de la 29005, la tabla municipal nacional del padrón."""
        ababuj = self.geo(2, "municipio", "44001", "Ababuj")
        g = self.resolver("Ababuj. Total. Total habitantes. Personas.", [ababuj], "municipio")
        assert g is ababuj

    def test_el_nombre_en_el_segundo_campo(self):
        """Formato de la 67223, natalidad provincial. Mirando sólo el primer
        campo —'Fecundidad'— esta tabla no resolvía nada."""
        albacete = self.geo(3, "provincia", "02", "Albacete")
        g = self.resolver("Fecundidad. Albacete.", [albacete], "provincia")
        assert g is albacete

    def test_los_acentos_no_impiden_casar(self):
        """'Alcalá de Guadaíra' aparece acentuado en el INE y puede no estarlo
        igual en `dim_geo`."""
        alcala = self.geo(4, "municipio", "41004", "Alcala de Guadaira")
        g = self.resolver("Alcalá de Guadaíra. Fecundidad. Tasa.", [alcala], "municipio")
        assert g is alcala

    def test_un_nombre_repetido_no_se_asigna_a_ninguno(self):
        """La regla de honestidad. Si dos municipios se llaman igual no hay
        forma de saber cuál es, y elegir uno metería el dato de un pueblo en
        la ficha de otro sin que nada lo delatara. Un hueco se ve; un dato
        equivocado, no."""
        uno = self.geo(5, "municipio", "09001", "Villanueva")
        otro = self.geo(6, "municipio", "37001", "Villanueva")
        assert self.resolver("Villanueva. Total. Personas.", [uno, otro], "municipio") is None

    def test_el_nivel_evita_confundir_ceuta_municipio_con_ceuta_provincia(self):
        """Ceuta es municipio, provincia y comunidad a la vez."""
        muni = self.geo(7, "municipio", "51001", "Ceuta")
        prov = self.geo(8, "provincia", "51", "Ceuta")
        assert self.resolver("Ceuta. Total. Personas.", [muni, prov], "provincia") is prov
        assert self.resolver("Ceuta. Total. Personas.", [muni, prov], "municipio") is muni

    def test_una_serie_que_no_es_de_ninguna_geografia_no_inventa(self):
        """'Total Nacional' de la 56934, que resultó ser una tabla NACIONAL
        declarada como municipal en el motor."""
        madrid = self.geo(9, "municipio", "28079", "Madrid")
        serie = "Total Nacional. Todas las edades. Total. Población. Número."
        assert self.resolver(serie, [madrid], "municipio") is None

    def test_el_codigo_gana_al_nombre(self):
        """Si viene el código, es inequívoco y manda."""
        real = self.geo(10, "municipio", "28079", "Madrid")
        trampa = self.geo(11, "municipio", "99999", "Total")
        g = self.resolver("28079 Madrid. Total. Personas.", [real, trampa], "municipio")
        assert g is real


class TestPoblacionMunicipalReal:
    """El mapeo de la 29005, la única tabla municipal nacional del padrón.

    Sus series van SIN código y las tres de cada municipio contienen «Total
    habitantes»:

        Ababuj. Total. Total habitantes. Personas.
        Ababuj. Hombres. Total habitantes. Personas.
        Ababuj. Mujeres. Total habitantes. Personas.

    De ahí que `dem.pop.total` filtre por exclusión y no por coincidencia: un
    `match=("total",)` cogería las tres y escribiría tres hechos del mismo
    indicador para el mismo municipio. La población saldría al doble, y nada
    lo delataría salvo mirar el número.
    """

    FILAS: ClassVar[list[dict]] = [
        {"Nombre": "Ababuj. Total. Total habitantes. Personas.",
         "Data": [{"Valor": 100.0, "Anyo": 2025}]},
        {"Nombre": "Ababuj. Hombres. Total habitantes. Personas.",
         "Data": [{"Valor": 55.0, "Anyo": 2025}]},
        {"Nombre": "Ababuj. Mujeres. Total habitantes. Personas.",
         "Data": [{"Valor": 45.0, "Anyo": 2025}]},
    ]

    @staticmethod
    def ababuj():
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo
        return Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="44001",
                   name="Ababuj", parent_id=None)

    def hechos(self, indicador):
        from powergis.adapters.collectors.ine import TABLES
        from powergis.domain.models import Segments

        spec = next(s for s in TABLES if s.indicator == indicador)
        ine = IneCollector(client=FakeClient({"29005": self.FILAS}))
        geo = self.ababuj()
        return ine._map(
            spec, self.FILAS,
            {geo.ine_code: geo}, IneCollector._indice_por_nombre([geo]),
            Segments(), None,
        )

    def test_la_poblacion_total_es_un_solo_hecho(self):
        hechos = self.hechos("dem.pop.total")
        assert len(hechos) == 1
        assert hechos[0].value == 100.0

    def test_hombres_y_mujeres_salen_por_separado(self):
        assert [h.value for h in self.hechos("dem.sex.men")] == [55.0]
        assert [h.value for h in self.hechos("dem.sex.women")] == [45.0]

    def test_el_total_no_suma_hombres_y_mujeres(self):
        """La comprobación que delata el triple conteo: si `dem.pop.total`
        cogiera las tres series, saldría 200 en vez de 100."""
        assert sum(h.value or 0 for h in self.hechos("dem.pop.total")) == 100.0

    def test_la_serie_sin_codigo_encuentra_su_municipio(self):
        assert self.hechos("dem.pop.total")[0].geo_id == 1

    def test_la_tabla_apuntada_es_la_nacional_no_la_de_una_provincia(self):
        """`2879` era «Rioja, La: Población por municipios y sexo». Que este
        número vuelva a cambiar a una tabla provincial no daría ningún error:
        sólo faltaría el 98 % del país."""
        from powergis.adapters.collectors.ine import TABLES

        for indicador in ("dem.pop.total", "dem.sex.men", "dem.sex.women"):
            spec = next(s for s in TABLES if s.indicator == indicador)
            assert spec.table_id == "29005"
            assert spec.operacion == 22
            assert "padron por municipio" in " ".join(spec.table_match)


class TestSegmentoDeSexo:
    """`dem.sex.men` y `dem.sex.women` NO llevan segmento.

    El código del indicador ya dice el sexo. Guardarlos además con `{sex: M}`
    hacía que el cálculo de derivados —que los busca sin segmento— no los
    encontrara nunca, y el índice de feminidad y el % de mujeres no se
    calcularon ni una vez, ni con la tabla de La Rioja ni con la nacional.
    """

    FILAS: ClassVar[list[dict]] = [
        {"Nombre": "Ababuj. Hombres. Total habitantes. Personas.",
         "Data": [{"Valor": 55.0, "Anyo": 2025}]},
        {"Nombre": "Ababuj. Mujeres. Total habitantes. Personas.",
         "Data": [{"Valor": 45.0, "Anyo": 2025}]},
    ]

    def hechos(self, indicador):
        from powergis.adapters.collectors.ine import TABLES
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo, Segments

        spec = next(s for s in TABLES if s.indicator == indicador)
        g = Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="44001",
                name="Ababuj", parent_id=None)
        return IneCollector(client=FakeClient({}))._map(
            spec, self.FILAS, {g.ine_code: g},
            IneCollector._indice_por_nombre([g]), Segments(), None,
        )

    def test_hombres_sin_segmento(self):
        hechos = self.hechos("dem.sex.men")
        assert [h.value for h in hechos] == [55.0]
        assert all(not h.segment for h in hechos)

    def test_mujeres_sin_segmento(self):
        hechos = self.hechos("dem.sex.women")
        assert [h.value for h in hechos] == [45.0]
        assert all(not h.segment for h in hechos)

    def test_un_indicador_segmentado_si_lo_lleva(self):
        from dataclasses import replace

        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo, Segments

        spec = TableSpec("x", "dem.pop.segment", "municipio", segment_from="sex")
        g = Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="44001",
                name="Ababuj", parent_id=None)
        hechos = IneCollector(client=FakeClient({}))._map(
            replace(spec), self.FILAS, {g.ine_code: g},
            IneCollector._indice_por_nombre([g]), Segments(), None,
        )
        assert {h.segment["sex"] for h in hechos} == {"M", "F"}


class TestVariasTablas:
    """Un indicador alimentado por 54 tablas, una por provincia (Atlas)."""

    @staticmethod
    def catalogo(n):
        return [
            {"Id": 30000 + i, "Nombre": "Indicadores demográficos",
             "FechaRef_fin": "null", "Ultima_Modificacion": 1_700_000_000_000 + i}
            for i in range(n)
        ]

    def spec(self, **kw):
        base: dict = {"operacion": 353, "table_match": ("indicadores demograficos",),
                      "varias_tablas": True}
        base.update(kw)
        return TableSpec("30814", "dem.age.mean", "municipio", **base)

    def test_resuelve_las_cincuenta_y_cuatro(self):
        class Cliente:
            def get_json(self, path, params=None):
                return TestVariasTablas.catalogo(54)

        ids, motivo = IneCollector(client=Cliente()).resolver_tablas(self.spec())
        assert len(ids) == 54 and "54 tablas" in motivo

    def test_sin_la_marca_sigue_devolviendo_una(self):
        class Cliente:
            def get_json(self, path, params=None):
                return TestVariasTablas.catalogo(54)

        ids, _ = IneCollector(client=Cliente()).resolver_tablas(self.spec(varias_tablas=False))
        assert len(ids) == 1

    def test_una_tabla_caida_no_tumba_las_demas(self):
        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return TestVariasTablas.catalogo(3)
                if path.endswith("30001"):
                    raise CollectorError("esta no responde")
                return [{"Nombre": "Abengibre. Edad media de la población.",
                         "Data": [{"Valor": 44.0, "Anyo": 2025}]}]

        assert len(IneCollector(client=Cliente())._table(self.spec())) == 2

    def test_si_no_responde_ninguna_falla_en_alto(self):
        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return TestVariasTablas.catalogo(3)
                raise CollectorError("ninguna responde")

        with pytest.raises(CollectorError):
            IneCollector(client=Cliente())._table(self.spec())

    def test_el_verificador_dice_cuantas_tablas_no_una(self):
        """Ver «30814» cuando la carga usa 54 escondería el error de leer una
        provincia creyendo leer el país."""
        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return TestVariasTablas.catalogo(3)
                return [{"Nombre": "28079 Madrid. Edad media de la población.",
                         "Data": [{"Valor": 44.0, "Anyo": 2025}]}]

        fila = IneCollector(client=Cliente()).verify([self.spec()])["results"][0]
        assert fila["table"] == "3 tablas"


class TestUnaDescargaPorTabla:
    """Tres indicadores leen la 29005 y cinco las 54 del Atlas.

    Sin caché, cada indicador volvía a descargar su tabla: 270 peticiones
    donde bastan 54, a la tasa que tolera el INE y con cinco veces más
    papeletas para que alguna se corte a medias.
    """

    def test_la_misma_tabla_se_pide_una_vez_por_carga(self):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo, Segments

        llamadas: list[str] = []

        class Cliente:
            def get_json(self, path, params=None):
                llamadas.append(path)
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 29005, "Nombre": "Cifras oficiales del padrón por municipio",
                             "Ultima_Modificacion": 1}]
                return [
                    {"Nombre": "Ababuj. Total. Total habitantes.", "Data": [{"Valor": 100.0, "Anyo": 2025}]},
                    {"Nombre": "Ababuj. Hombres. Total habitantes.", "Data": [{"Valor": 55.0, "Anyo": 2025}]},
                    {"Nombre": "Ababuj. Mujeres. Total habitantes.", "Data": [{"Valor": 45.0, "Anyo": 2025}]},
                ]

        g = Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="44001", name="Ababuj", parent_id=None)
        hechos = IneCollector(client=Cliente()).collect(
            ["dem.pop.total", "dem.sex.men", "dem.sex.women"], [g], Segments()
        )
        assert sum(1 for p in llamadas if p.startswith("DATOS_TABLA")) == 1
        assert {h.indicator: h.value for h in hechos} == {
            "dem.pop.total": 100.0, "dem.sex.men": 55.0, "dem.sex.women": 45.0,
        }


class TestFiltrosSinAcentos:
    FILAS: ClassVar[list[dict]] = [
        {"Nombre": "Abengibre. Porcentaje de población de 65 y más años. Dato base.",
         "Data": [{"Valor": 30.0, "Anyo": 2025}]},
        {"Nombre": "Abengibre. Tamaño medio del hogar. Dato base.",
         "Data": [{"Valor": 2.3, "Anyo": 2025}]},
    ]

    def test_token_sin_acento_casa_con_serie_acentuada(self, collector):
        ine, _ = collector({"30814": self.FILAS})
        spec = TableSpec("30814", "dem.age.65p_pct", "municipio", match=("65 y mas",))
        assert ine.verify([spec])["results"][0]["matched"] == 1

    def test_y_con_la_enye(self, collector):
        ine, _ = collector({"30814": self.FILAS})
        spec = TableSpec("30814", "dem.household.size", "municipio", match=("tamano medio",))
        assert ine.verify([spec])["results"][0]["matched"] == 1

    def test_el_lector_de_edades_sigue_viendo_y_mas(self):
        """Plegar el nombre entero rompería el último tramo, «100 y más»,
        porque el lector de edades busca el texto acentuado."""
        assert IneCollector._age_of("madrid. 100 y más años. total.") is not None


class TestVerificadorConExclude:
    FILAS: ClassVar[list[dict]] = [
        {"Nombre": f"{m}. {s}. Total habitantes. Personas.", "Data": [{"Valor": 1.0, "Anyo": 2025}]}
        for m in ("Ababuj", "Abades") for s in ("Total", "Hombres", "Mujeres")
    ]

    def test_exclude_cuenta(self, collector):
        ine, _ = collector({"29005": self.FILAS})
        spec = TableSpec("29005", "dem.pop.total", "municipio", exclude=("hombres", "mujeres"))
        assert ine.verify([spec])["results"][0]["matched"] == 2

    def test_si_todo_queda_excluido_lo_dice(self, collector):
        ine, _ = collector({"29005": self.FILAS})
        spec = TableSpec("29005", "x", "municipio", exclude=("habitantes",))
        fila = ine.verify([spec])["results"][0]
        assert fila["status"] == "NO_MATCH" and "excluidas" in fila["detail"]


class TestAtlasDemografico:
    """El mapeo del Atlas, con las series tal y como las publica el INE."""

    FILAS: ClassVar[list[dict]] = [
        {"Nombre": f"Abengibre. {n}. Dato base.", "Data": [{"Valor": v, "Anyo": 2023}]}
        for n, v in (
            ("Edad media de la población", 47.1),
            ("Porcentaje de población menor de 18 años", 14.2),
            ("Porcentaje de población de 65 y más años", 29.8),
            ("Tamaño medio del hogar", 2.31),
            ("Porcentaje de hogares unipersonales", 31.5),
            ("Población", 812.0),
        )
    ] + [
        # Sección censal de la misma tabla: no debe casar con ningún municipio.
        {"Nombre": "Abengibre sección 0200101001. Edad media de la población. Dato base.",
         "Data": [{"Valor": 50.0, "Anyo": 2023}]},
    ]

    def valores(self):
        from powergis.adapters.collectors.ine import TABLES
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo, Segments

        g = Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="02001",
                name="Abengibre", parent_id=None)
        ine = IneCollector(client=FakeClient({}))
        out = {}
        for spec in TABLES:
            if spec.operacion != 353:
                continue
            for h in ine._map(spec, self.FILAS, {g.ine_code: g},
                              IneCollector._indice_por_nombre([g]), Segments(), None):
                out.setdefault(h.indicator, []).append(h.value)
        return out

    def test_cada_indicador_sale_una_vez_y_con_su_valor(self):
        assert self.valores() == {
            "dem.age.mean": [47.1],
            "dem.age.u18_pct": [14.2],
            "dem.age.65p_pct": [29.8],
            "dem.household.size": [2.31],
            "dem.household.single_pct": [31.5],
        }

    def test_la_seccion_censal_no_pisa_al_municipio(self):
        """Si la sección casara, habría dos edades medias para Abengibre y
        una de ellas sería la de un barrio."""
        assert self.valores()["dem.age.mean"] == [47.1]

    def test_todas_las_del_atlas_usan_las_54_tablas(self):
        from powergis.adapters.collectors.ine import TABLES
        atlas = [s for s in TABLES if s.operacion == 353]
        assert atlas and all(s.varias_tablas for s in atlas)


class TestCargaCompleta:
    """Cómo se comporta el colector cuando lo usa la ingesta de verdad."""

    @staticmethod
    def geo(geo_id, level, code, name):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo
        return Geo(geo_id=geo_id, level=GeoLevel(level), ine_code=code, name=name, parent_id=None)

    def test_pide_todas_las_geografias_de_una_vez(self):
        """En lotes, el detector de homónimos sólo veía el lote."""
        assert IneCollector.TODAS_LAS_GEOS is True

    def test_la_ingesta_respeta_esa_peticion(self):
        from powergis.application.ingest import IngestData

        llamadas: list[int] = []

        class Espia:
            TODAS_LAS_GEOS = True
            name = "espia"

            def provides(self):
                return ["x"]

            def collect(self, codes, geos, segments, period=None):
                llamadas.append(len(geos))
                return []

        class UoW:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ingest = IngestData(lambda: UoW(), {"espia": Espia()}, batch_size=500)
        ingest._target_geos = lambda level, parent: [self.geo(i, "municipio", f"{i:05d}", f"M{i}") for i in range(1200)]
        from powergis.domain.enums import GeoLevel
        ingest.by_collector("espia", [], GeoLevel.MUNICIPIO)
        assert llamadas == [1200], "una llamada con todas, no tres lotes de 500"

    def test_homonimos_en_distintos_lotes_se_siguen_detectando(self):
        """Con todas las geografías delante, dos «Villanueva» son ambiguos y no
        se asignan a ninguno. En lotes, cada uno se quedaba el dato del otro."""
        filas = [
            {"Nombre": "Villanueva. Total. Total habitantes.", "Data": [{"Valor": 100.0, "Anyo": 2025}]},
            {"Nombre": "Villanueva. Total. Total habitantes.", "Data": [{"Valor": 900.0, "Anyo": 2025}]},
        ]
        from powergis.domain.models import Segments

        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 29005, "Nombre": "Cifras oficiales del padrón por municipio"}]
                return filas

        geos = [self.geo(1, "municipio", "09001", "Villanueva"),
                self.geo(2, "municipio", "37001", "Villanueva")]
        hechos = IneCollector(client=Cliente()).collect(["dem.pop.total"], geos, Segments())
        assert hechos == []

    def test_cada_spec_solo_en_su_nivel(self):
        """Cargando provincias no se bajan las 54 del Atlas ni la 29005."""
        from powergis.domain.models import Segments
        pedidas: list[str] = []

        class Cliente:
            def get_json(self, path, params=None):
                pedidas.append(path)
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 67223, "Nombre": "Tasa Bruta de Natalidad por provincia",
                             "Ultima_Modificacion": 1}]
                return [{"Nombre": "Fecundidad. Albacete.", "Data": [{"Valor": 6.5, "Anyo": 2024}]}]

        prov = [self.geo(3, "provincia", "02", "Albacete")]
        todos = list(IneCollector.PROVIDES)
        hechos = IneCollector(client=Cliente()).collect(todos, prov, Segments())
        assert [h.indicator for h in hechos] == ["dem.birth.rate"]
        assert all("67223" in p or "TABLAS_OPERACION/33" in p for p in pedidas)

    def test_los_pendientes_no_se_descargan(self):
        from powergis.adapters.collectors.ine import TABLES
        from powergis.domain.models import Segments
        pedidas: list[str] = []

        class Cliente:
            def get_json(self, path, params=None):
                pedidas.append(path)
                return []

        pendientes = [s.indicator for s in TABLES if s.pendiente]
        assert pendientes, "debería haber indicadores marcados como pendientes"
        IneCollector(client=Cliente()).collect(
            pendientes, [self.geo(1, "municipio", "44001", "Ababuj")], Segments()
        )
        assert pedidas == []

    def test_un_pendiente_no_bloquea_la_verificacion(self, collector):
        ine, _ = collector({})
        spec = TableSpec("0", "x", "municipio", pendiente="sin fuente")
        informe = ine.verify([spec])
        assert informe["broken"] == 0 and informe["pending"] == 1

    def test_valores_contradictorios_se_descartan_iguales_se_funden(self):
        from datetime import date

        from powergis.domain.models import Fact
        f = lambda gid, v: Fact(geo_id=gid, indicator="x", value=v, period=date(2025, 1, 1))  # noqa: E731
        limpios = IneCollector._sin_conflictos([f(1, 10.0), f(1, 20.0), f(2, 5.0), f(2, 5.0)])
        assert [(h.geo_id, h.value) for h in limpios] == [(2, 5.0)]


class TestIneBuscarDesdeTabla:
    """Hay operaciones que no salen en OPERACIONES_DISPONIBLES —la del Padrón
    continuo por edad—, así que buscando por nombre no aparecen nunca. Desde
    una tabla conocida se llega a su operación por SERIES_TABLA."""

    def _cli(self, monkeypatch, tablas: dict[str, object]):
        from typer.testing import CliRunner

        from powergis import cli
        from powergis.adapters.collectors import ine as ine_mod

        cliente = FakeClient(tablas)
        original = ine_mod.IneCollector

        class ConCliente(original):  # type: ignore[misc, valid-type]
            def __init__(self, client=None):
                super().__init__(client=cliente)

        monkeypatch.setattr(ine_mod, "IneCollector", ConCliente)
        return CliRunner(), cli.app, cliente

    def test_de_la_tabla_a_su_operacion(self, monkeypatch):
        runner, app, cliente = self._cli(monkeypatch, {
            "33956": [{"COD": "X", "FK_Operacion": 188, "Nombre": "Albacete. Total."}],
            "188": [
                {"Id": 33956, "Nombre": "Albacete: Población por sexo, municipios y edad "
                 "(grupos quinquenales)", "Anyo_Periodo_ini": "2024"},
                {"Id": 33570, "Nombre": "Alicante: Población por sexo, municipios y edad "
                 "(grupos quinquenales)", "Anyo_Periodo_ini": "2024"},
                {"Id": 11111, "Nombre": "Otra cosa", "Anyo_Periodo_ini": "2024"},
            ],
        })
        out = runner.invoke(app, ["ine-buscar", "quinquenales", "--desde-tabla", "33956"])

        assert out.exit_code == 0, out.output
        assert "operación 188" in out.output
        assert "33570" in out.output and "33956" in out.output
        assert "11111" not in out.output, "el texto filtra las tablas"
        assert "SERIES_TABLA/33956" in cliente.rutas
        assert "TABLAS_OPERACION/188" in cliente.rutas

    def test_sin_texto_ni_tabla_no_recorre_todo_el_ine(self, monkeypatch):
        runner, app, cliente = self._cli(monkeypatch, {})
        out = runner.invoke(app, ["ine-buscar"])
        assert out.exit_code == 2
        assert cliente.rutas == []


class TestFilasRecortadasYSecreto:
    def test_la_cache_guarda_solo_nombre_y_puntos(self, collector):
        pesada = {
            "COD": "DPOP1", "Nombre": "28079 Madrid. Total. Personas.",
            "MetaData": [{"Id": 1, "Variable": {"Nombre": "Municipios"}}] * 20,
            "Unidad": {"Nombre": "Personas"},
            "Data": [{"Valor": 3.4e6, "Anyo": 2025, "FK_TipoDato": 1, "Secreto": False}],
        }
        c, _ = collector({"29005": [pesada]})
        filas = c._one_table("29005")
        assert set(filas[0]) == {"Nombre", "Municipio", "Tabla", "Data"}
        assert filas[0]["Tabla"] == "29005"
        assert filas[0]["Municipio"] is None, "la variable no trae código de municipio"
        assert filas[0]["Data"][0]["Valor"] == 3.4e6
        assert filas[0]["Data"][0]["Anyo"] == 2025

    def test_un_dato_secreto_es_hueco_nunca_cero(self, collector):
        c, _ = collector({})
        fila = {"Nombre": "x", "Data": [{"Valor": 0, "Anyo": 2023, "Secreto": True}]}
        assert c._points(fila) == [(None, date(2023, 1, 1))]


class TestHomonimosPorCodigo:
    """Dos pueblos con el mismo nombre quedaban SIN dato: la 29005 y el Atlas
    los nombran sin código ni provincia. Con `det=2` cada serie trae el valor
    de la variable «Municipios» (19) con su código, y ese sí desempata."""

    @staticmethod
    def meta(codigo: str, variable: str = "Municipios", var_id: int = 19) -> dict:
        return {"Id": 1, "Variable": {"Id": var_id, "Nombre": variable}, "Codigo": codigo}

    @staticmethod
    def geo(geo_id, ine_code, name):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo

        return Geo(geo_id, GeoLevel.MUNICIPIO, ine_code, name, None, None, None)

    def _cargar(self, filas):
        from powergis.domain.models import Segments

        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 29005, "Nombre": "Cifras oficiales del padrón por municipio"}]
                return filas

        geos = [self.geo(1, "31070", "Castejón"), self.geo(2, "16068", "Castejón"),
                self.geo(3, "02003", "Albacete")]
        hechos = IneCollector(client=Cliente()).collect(["dem.pop.total"], geos, Segments())
        return {h.geo_id: h.value for h in hechos}

    def test_cada_homonimo_con_su_dato(self):
        out = self._cargar([
            {"Nombre": "Castejón. Total. Total habitantes.", "MetaData": [self.meta("31070")],
             "Data": [{"Valor": 4_300.0, "Anyo": 2025}]},
            {"Nombre": "Castejón. Total. Total habitantes.", "MetaData": [self.meta("16068")],
             "Data": [{"Valor": 150.0, "Anyo": 2025}]},
        ])
        assert out == {1: 4_300.0, 2: 150.0}

    def test_sin_codigo_siguen_sin_resolverse(self):
        out = self._cargar([
            {"Nombre": "Castejón. Total. Total habitantes.", "Data": [{"Valor": 4_300.0, "Anyo": 2025}]},
        ])
        assert out == {}

    def test_una_seccion_no_se_guarda_como_su_municipio(self):
        out = self._cargar([
            {"Nombre": "Castejón. Total. Total habitantes.",
             "MetaData": [self.meta("31070"), self.meta("3107001001", "Secciones", 847)],
             "Data": [{"Valor": 900.0, "Anyo": 2025}]},
        ])
        assert out == {}

    def test_el_codigo_manda_y_no_se_prueba_por_nombre(self):
        """Cargando un ámbito que sólo tiene el Castejón de Navarra, la serie
        del de Cuenca NO puede caer en él por llamarse igual."""
        from powergis.domain.models import Segments

        filas = [{"Nombre": "Castejón. Total. Total habitantes.",
                  "MetaData": [self.meta("16068")],
                  "Data": [{"Valor": 150.0, "Anyo": 2025}]}]

        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 29005, "Nombre": "Cifras oficiales del padrón por municipio"}]
                return filas

        solo_navarra = [self.geo(1, "31070", "Castejón")]
        hechos = IneCollector(client=Cliente()).collect(
            ["dem.pop.total"], solo_navarra, Segments()
        )
        assert hechos == []

    def test_una_fila_provincial_no_cae_en_el_municipio(self):
        """«Albacete.» provincia y Albacete ciudad se llaman igual."""
        out = self._cargar([
            {"Nombre": "Albacete. Total. Total habitantes.",
             "MetaData": [self.meta("02", "Provincias", 115)],
             "Data": [{"Valor": 386_000.0, "Anyo": 2025}]},
            {"Nombre": "Albacete. Total. Total habitantes.",
             "MetaData": [self.meta("02003")],
             "Data": [{"Valor": 173_000.0, "Anyo": 2025}]},
        ])
        assert out == {3: 173_000.0}


class TestVariasTablasSinCaerseALaSemilla:
    """Con 54 tablas, caer a la semilla es cargar UNA provincia creyendo cargar
    el país: el fallo de La Rioja otra vez."""

    def test_si_la_operacion_no_responde_falla_en_vez_de_cargar_una(self):
        from powergis.adapters.collectors.ine import TableSpec

        class Cliente:
            def get_json(self, path, params=None):
                raise CollectorError("caído")

        spec = TableSpec("30814", "dem.age.mean", "municipio", operacion=353,
                         table_match=("indicadores demograficos",), varias_tablas=True)
        with pytest.raises(CollectorError):
            IneCollector(client=Cliente()).resolver_tablas(spec)

    def test_el_verificador_lo_marca_inalcanzable(self):
        from powergis.adapters.collectors.ine import TableSpec

        class Cliente:
            def get_json(self, path, params=None):
                return []        # la operación no tiene ninguna tabla que encaje

        spec = TableSpec("30814", "dem.age.mean", "municipio", operacion=353,
                         table_match=("indicadores demograficos",), varias_tablas=True)
        out = IneCollector(client=Cliente()).verify([spec])
        assert out["results"][0]["status"] == "UNREACHABLE"

    def test_la_variable_de_entorno_lleva_la_lista(self, monkeypatch):
        from powergis.adapters.collectors.ine import TableSpec

        spec = TableSpec("30814", "dem.age.mean", "municipio", operacion=353,
                         table_match=("x",), varias_tablas=True)
        monkeypatch.setenv(spec.env_key, "1, 2,3")
        tablas, _ = IneCollector(client=FakeClient({})).resolver_tablas(spec)
        assert tablas == ["1", "2", "3"]


class TestEdicionNuevaGana:
    def test_de_tablas_distintas_manda_la_mas_reciente(self):
        from powergis.domain.models import Fact

        def f(v, tabla):
            return Fact(geo_id=1, indicator="x", period=date(2023, 1, 1), value=v,
                        segment={}, source_ref=f"INE:{tabla}")

        assert [h.value for h in IneCollector._sin_conflictos([f(5.0, "B"), f(4.0, "A")])] == [5.0]

    def test_en_la_misma_tabla_es_contradiccion(self):
        from powergis.domain.models import Fact

        def f(v):
            return Fact(geo_id=1, indicator="x", period=date(2023, 1, 1), value=v,
                        segment={}, source_ref="INE:A")

        assert IneCollector._sin_conflictos([f(5.0), f(4.0)]) == []


class TestSeccionesYFallosVisibles:
    @staticmethod
    def meta(codigo, variable="Municipios", var_id=19):
        return {"Variable": {"Id": var_id, "Nombre": variable}, "Codigo": codigo}

    @staticmethod
    def geo(geo_id, ine_code, name):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Geo

        return Geo(geo_id, GeoLevel.MUNICIPIO, ine_code, name, None, None, None)

    def _collector(self, filas):
        class Cliente:
            def get_json(self, path, params=None):
                if path.startswith("TABLAS_OPERACION"):
                    return [{"Id": 29005, "Nombre": "Cifras oficiales del padrón por municipio"}]
                return filas

        return IneCollector(client=Cliente())

    def test_una_seccion_con_variable_rara_no_se_guarda_como_municipio(self):
        """El código solo no basta: la sección cita el de su municipio."""
        from powergis.domain.models import Segments

        filas = [
            {"Nombre": "Abengibre sección 0200101001. Total. Total habitantes.",
             "MetaData": [self.meta("02001"), self.meta("0200101001", "Unidades censales", 999)],
             "Data": [{"Valor": 39.0, "Anyo": 2025}]},
            {"Nombre": "Abengibre. Total. Total habitantes.",
             "MetaData": [self.meta("02001")],
             "Data": [{"Valor": 44.0, "Anyo": 2025}]},
        ]
        hechos = self._collector(filas).collect(
            ["dem.pop.total"], [self.geo(1, "02001", "Abengibre")], Segments()
        )
        assert [(h.geo_id, h.value) for h in hechos] == [(1, 44.0)]

    def test_nacionalidad_no_es_un_nivel_territorial(self):
        fila = {"MetaData": [self.meta("02001"),
                             self.meta("1", "Nacionalidad", 300)]}
        assert IneCollector._municipio_de_metadatos(fila) == "02001"

    def test_si_nada_resuelve_la_carga_lo_dice(self):
        from powergis.domain.models import Segments

        filas = [{"Nombre": "Pueblo Desconocido. Total. Total habitantes.",
                  "Data": [{"Valor": 1.0, "Anyo": 2025}]}]
        c = self._collector(filas)
        assert c.collect(["dem.pop.total"], [self.geo(1, "02001", "Abengibre")], Segments()) == []
        assert any("ninguna resolvió" in f for f in c.fallos)

    def test_los_fallos_llegan_al_informe_de_la_carga(self, geos):
        from conftest import FakeUnitOfWork
        from powergis.application.ingest import IngestData
        from powergis.domain.enums import GeoLevel

        class Cliente:
            def get_json(self, path, params=None):
                raise CollectorError("el INE no contesta")

        from powergis.domain.models import Geo

        madrid = Geo(50, GeoLevel.MUNICIPIO, "28079", "Madrid", 3)
        uow = FakeUnitOfWork([*geos, madrid], [])
        servicio = IngestData(lambda: uow, {"ine": IneCollector(client=Cliente())})
        informe = servicio.by_collector("ine", ["dem.pop.total"], GeoLevel.MUNICIPIO)
        assert informe.errors, "un indicador que no carga no puede acabar «bien»"
