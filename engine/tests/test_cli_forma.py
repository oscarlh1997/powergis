"""La forma de la interfaz de línea de comandos.

No se prueba aquí lo que hacen los comandos, sino **cómo se invocan**. Parece
trivial y no lo es: Typer decide si un parámetro es argumento posicional u
opción a partir de cómo está escrita la firma, y un `str` con valor por
defecto a secas se convierte en `--opcion` sin avisar.

Eso hizo fallar el despliegue con

    powergis endpoints http://localhost:8000
    Got unexpected extra argument(s) (http://localhost:8000)

pese a ser la invocación que aparece en la propia ayuda del comando y en el
Makefile. Ninguna prueba lo notó porque todas las demás llaman a los comandos
por dentro, no por la línea de órdenes.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

from powergis.cli import app

COMANDOS = typer.main.get_command(app).commands  # type: ignore[attr-defined]


def parametro(comando: str, nombre: str) -> Any:
    return next(p for p in COMANDOS[comando].params if p.name == nombre)


class TestPosicionales:
    """Lo que la documentación promete que se escribe sin `--`."""

    @pytest.mark.parametrize(
        ("comando", "nombre"),
        [("endpoints", "base_url")],
    )
    def test_es_argumento_y_no_opcion(self, comando, nombre):
        # Se mira `param_type_name` y no la clase: Typer dejó de heredar de
        # `click.Argument` en la 0.27 —ahora usa su propio `Parameter`—, así
        # que un `isinstance` contra Click pasaría a fallar por el motivo
        # equivocado. `param_type_name` es la discriminación estable.
        assert parametro(comando, nombre).param_type_name == "argument", (
            f"`{comando} <{nombre}>` está documentado como posicional; si Typer "
            f"lo convierte en --{nombre.replace('_', '-')}, esa llamada falla."
        )

    def test_el_motor_a_probar_puede_omitirse(self):
        """Sin URL tiene que seguir valiendo: es como se usa en desarrollo."""
        assert not parametro("endpoints", "base_url").required


class TestOpciones:
    def test_grupo_acepta_una_lista_separada_por_comas(self):
        """Hace falta para excluir `operacion` al probar por el dominio, donde
        `/internal` debe dar 403 por diseño."""
        assert "comas" in (parametro("endpoints", "grupo").help or "")
