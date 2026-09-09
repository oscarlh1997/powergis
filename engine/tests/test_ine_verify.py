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
