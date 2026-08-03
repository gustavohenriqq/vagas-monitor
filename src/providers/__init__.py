"""Providers de vagas. Cada um busca de uma fonte e devolve JobPosting normalizado."""

from .base import JobProvider, build_session
from .gupy import GupyProvider
from .inhire import InhireProvider

__all__ = ["JobProvider", "build_session", "GupyProvider", "InhireProvider"]
