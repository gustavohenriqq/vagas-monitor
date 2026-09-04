"""
searches.py — Carregamento e gravação das buscas configuradas (searches.yaml).

Uma "busca" é um perfil de filtro que o usuário edita pelo painel web ou à mão.
O arquivo é a fonte da verdade da configuração; o painel apenas o edita.

Estrutura do searches.yaml:

    inhire_companies:        # tenants (subdomínios) do inhire a varrer
      - programmers
      - appmax

    searches:
      - name: "Backend Python Remoto"
        enabled: true
        providers: [gupy, inhire]
        keywords: ["python", "backend", "django"]   # casa QUALQUER uma
        exclude_keywords: ["estágio"]               # descarta se aparecer
        seniority: [pleno, senior]                  # vazio = qualquer
        workplace_types: [remote]                   # remote|hybrid|onsite; vazio = qualquer
        locations: ["são paulo", "remoto"]          # substrings; vazio = qualquer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("gupy", "inhire", "wwr", "greenhouse")
VALID_WORKPLACE = ("remote", "hybrid", "onsite")
VALID_SENIORITY = ("estagio", "junior", "pleno", "senior", "lead", "indefinido")

DEFAULT_SEARCHES_PATH = Path("config/searches.yaml")


@dataclass
class SearchProfile:
    """Perfil de busca/filtro de vagas."""

    name: str
    enabled: bool = True
    providers: list[str] = field(default_factory=lambda: list(VALID_PROVIDERS))
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    seniority: list[str] = field(default_factory=list)
    workplace_types: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    # precise=True: usa o filtro de 3 níveis (cargo no título) em vez de só
    # palavra-chave solta. profile: rótulo do perfil (brasil | internacional).
    precise: bool = False
    profile: str = "brasil"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "profile": self.profile,
            "precise": self.precise,
            "providers": self.providers,
            "keywords": self.keywords,
            "exclude_keywords": self.exclude_keywords,
            "seniority": self.seniority,
            "workplace_types": self.workplace_types,
            "locations": self.locations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchProfile":
        def _as_list(value) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                # aceita "python, backend" além de lista YAML
                return [v.strip() for v in value.split(",") if v.strip()]
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            return []

        providers = _as_list(data.get("providers")) or list(VALID_PROVIDERS)
        providers = [p.lower() for p in providers if p.lower() in VALID_PROVIDERS]

        return cls(
            name=str(data.get("name") or "sem-nome").strip(),
            enabled=bool(data.get("enabled", True)),
            providers=providers or list(VALID_PROVIDERS),
            keywords=_as_list(data.get("keywords")),
            exclude_keywords=_as_list(data.get("exclude_keywords")),
            seniority=[s.lower() for s in _as_list(data.get("seniority")) if s.lower() in VALID_SENIORITY],
            workplace_types=[w.lower() for w in _as_list(data.get("workplace_types")) if w.lower() in VALID_WORKPLACE],
            locations=_as_list(data.get("locations")),
            precise=bool(data.get("precise", False)),
            profile=str(data.get("profile") or "brasil").strip().lower(),
        )


@dataclass
class SearchesFile:
    """Conteúdo completo do searches.yaml."""

    inhire_companies: list[str] = field(default_factory=list)
    greenhouse_companies: list[str] = field(default_factory=list)
    searches: list[SearchProfile] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "inhire_companies": self.inhire_companies,
            "greenhouse_companies": self.greenhouse_companies,
            "searches": [s.to_dict() for s in self.searches],
        }


def load_searches(path: Path = DEFAULT_SEARCHES_PATH) -> SearchesFile:
    """Carrega o searches.yaml. Retorna estrutura vazia se o arquivo não existir."""
    path = Path(path)
    if not path.exists():
        logger.warning("searches.yaml não encontrado em %s. Retornando vazio.", path)
        return SearchesFile()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.error("YAML inválido em %s: %s. Retornando vazio.", path, exc)
        return SearchesFile()

    companies_raw = raw.get("inhire_companies") or []
    companies = [str(c).strip().lower() for c in companies_raw if str(c).strip()]

    gh_raw = raw.get("greenhouse_companies") or []
    gh = [str(c).strip() for c in gh_raw if str(c).strip()]

    searches_raw = raw.get("searches") or []
    searches = [SearchProfile.from_dict(item) for item in searches_raw if isinstance(item, dict)]

    logger.info("Config carregada: %d buscas, %d empresas inhire, %d boards greenhouse.",
                len(searches), len(companies), len(gh))
    return SearchesFile(inhire_companies=companies, greenhouse_companies=gh, searches=searches)


def save_searches(data: SearchesFile, path: Path = DEFAULT_SEARCHES_PATH) -> None:
    """Grava o searches.yaml preservando ordem e legibilidade."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.to_dict()
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("Config salva em %s (%d buscas).", path, len(data.searches))
