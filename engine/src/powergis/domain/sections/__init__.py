"""Registro de secciones.

Importar este paquete registra todas las secciones vía el decorador
`@register`. El orden de import fija el orden de presentación por defecto.
"""

from __future__ import annotations

# El import tiene efecto secundario deliberado: rellena REGISTRY.
from . import (
    clima,  # noqa: F401
    competencia,  # noqa: F401
    demografia,  # noqa: F401
    socioeconomico,  # noqa: F401
    trafico,  # noqa: F401
)
from .base import (
    REGISTRY,
    SectionBuilder,
    SectionContext,
    builders_for,
    get_builder,
    register,
)

__all__ = [
    "REGISTRY",
    "SectionBuilder",
    "SectionContext",
    "builders_for",
    "get_builder",
    "register",
]
