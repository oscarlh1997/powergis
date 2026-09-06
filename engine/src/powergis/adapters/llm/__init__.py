"""Adaptador de LLM con verificación de cifras."""

from .client import LlmClient, NullLlmClient, build_client
from .narrative import NarrativeService, verify_numbers

__all__ = ["LlmClient", "NarrativeService", "NullLlmClient", "build_client", "verify_numbers"]
