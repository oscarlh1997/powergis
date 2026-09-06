"""El verificador del INE.

Estas pruebas no tocan la red. Lo que se comprueba aquí es que el verificador
DETECTA los cuatro modos en que el mapeo del INE se rompe en silencio:

  1. el INE renumera la tabla al republicar   → UNREACHABLE
  2. la tabla existe pero se vació            → EMPTY
  3. el nombre de las series cambia           → NO_MATCH
  4. la tabla pasa a ser provincial           → LEVEL_MISMATCH

Ninguno de los cuatro lanza una excepción en producción: los cuatro devuelven
cero hechos y el informe sale con huecos que parecen secreto estadístico. Por
eso el verificador tiene que ser el ruidoso.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from powergis.adapters.collectors.ine import IneCollector, TableSpec
from powergis.domain.errors import CollectorError


class FakeClient:
    """Devuelve lo que se le diga por ID de tabla. Cuenta las llamadas."""

    def __init__(self, tables: dict[str, object]) -> None:
        self.tables = tables
        self.calls: list[str] = []

    def get_json(self, path: str, params: dict | None = None) -> object:
        table_id = path.rsplit("/", 1)[-1]
        self.calls.append(table_id)
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


class TestDeteccionDeNivel:
    def test_ignora_el_total_nacional_de_la_primera_fila(self):
        """Las tablas del INE suelen abrir con el total nacional; si se mirara
        sólo la primera serie, el nivel saldría mal siempre."""
        names = ["Total Nacional. Personas."] + [s["Nombre"] for s in MUNICIPALES]

        assert IneCollector._detect_level(names) == "municipio"

    def test_sin_codigos_no_inventa_un_nivel(self):
        assert IneCollector._detect_level(["Total Nacional.", "Ambos sexos."]) is None
