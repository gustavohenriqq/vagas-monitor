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

VALID_PROVIDERS = (
    "gupy", "inhire", "wwr", "greenhouse", "recrutei",
    "remotive", "remoteok", "lever", "ashby", "recruitee", "smartrecruiters",
)
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
    # Barra a vaga pelo LOCAL. `exclude_keywords` não serve para isso: ela é
    # comparada com o search_blob (título + empresa + descrição), que não
    # carrega cidade nem país.
    exclude_locations: list[str] = field(default_factory=list)
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
            "exclude_locations": self.exclude_locations,
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
            exclude_locations=_as_list(data.get("exclude_locations")),
            precise=bool(data.get("precise", False)),
            profile=str(data.get("profile") or "brasil").strip().lower(),
        )


# Providers baseados em empresa e a chave da lista no YAML.
COMPANY_LIST_KEYS = {
    "inhire": "inhire_companies",
    "greenhouse": "greenhouse_companies",
    "lever": "lever_companies",
    "ashby": "ashby_companies",
    "recruitee": "recruitee_companies",
    "smartrecruiters": "smartrecruiters_companies",
}


@dataclass
class SearchesFile:
    """Conteúdo completo do searches.yaml."""

    # Listas de empresas por provider (chave = nome do provider).
    company_lists: dict = field(default_factory=dict)
    searches: list[SearchProfile] = field(default_factory=list)

    def companies(self, provider: str) -> list[str]:
        return self.company_lists.get(provider, [])

    # Acessos usados pelo código legado / painel.
    @property
    def inhire_companies(self) -> list[str]:
        return self.companies("inhire")

    @property
    def greenhouse_companies(self) -> list[str]:
        return self.companies("greenhouse")

    def to_dict(self) -> dict:
        out: dict = {}
        for prov, key in COMPANY_LIST_KEYS.items():
            out[key] = self.company_lists.get(prov, [])
        out["searches"] = [s.to_dict() for s in self.searches]
        return out


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

    company_lists: dict = {}
    for prov, key in COMPANY_LIST_KEYS.items():
        raw_list = raw.get(key) or []
        vals = [str(c).strip() for c in raw_list if str(c).strip()]
        if prov == "inhire":
            vals = [v.lower() for v in vals]  # tenants do inhire são minúsculos
        company_lists[prov] = vals

    searches_raw = raw.get("searches") or []
    searches = [SearchProfile.from_dict(item) for item in searches_raw if isinstance(item, dict)]

    resumo = " ".join(f"{p}:{len(v)}" for p, v in company_lists.items() if v)
    logger.info("Config carregada: %d buscas | %s", len(searches), resumo or "sem listas de empresa")
    return SearchesFile(company_lists=company_lists, searches=searches)


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
