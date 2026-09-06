"""Colectores de fuentes externas."""

from .base import BaseCollector, HttpClient, RateLimiter
from .registry import build_registry, coverage_report

__all__ = ["BaseCollector", "HttpClient", "RateLimiter", "build_registry", "coverage_report"]
