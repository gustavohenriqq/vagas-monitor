"""Providers de vagas. Cada um busca de uma fonte e devolve JobPosting normalizado."""

from .base import JobProvider, build_session
from .gupy import GupyProvider
from .inhire import InhireProvider
from .wwr import WwrProvider
from .greenhouse import GreenhouseProvider
from .recrutei import RecruteiProvider
from .remotive import RemotiveProvider
from .remoteok import RemoteOkProvider
from .lever import LeverProvider
from .ashby import AshbyProvider
from .recruitee import RecruteeProvider
from .smartrecruiters import SmartRecruitersProvider
from .workday import WorkdayProvider

__all__ = [
    "JobProvider", "build_session",
    "GupyProvider", "InhireProvider", "WwrProvider", "GreenhouseProvider",
    "RecruteiProvider", "RemotiveProvider", "RemoteOkProvider",
    "LeverProvider", "AshbyProvider", "RecruteeProvider", "SmartRecruitersProvider",
    "WorkdayProvider",
]
