"""Providers de vagas. Cada um busca de uma fonte e devolve JobPosting normalizado."""

from .base import JobProvider, build_session
from .gupy import GupyProvider
from .inhire import InhireProvider
from .wwr import WwrProvider
from .greenhouse import GreenhouseProvider

__all__ = [
    "JobProvider", "build_session", "GupyProvider", "InhireProvider",
    "WwrProvider", "GreenhouseProvider",
]
