"""
matcher.py — Decide se uma vaga casa com um perfil de busca.

Regras (todas precisam passar):
  1. keywords: se houver, ao menos UMA precisa aparecer no título/empresa/descrição.
  2. exclude_keywords: se QUALQUER uma aparecer, a vaga é descartada.
  3. seniority: se houver lista, a senioridade da vaga precisa estar nela.
  4. workplace_types: se houver lista, o tipo de local precisa estar nela.
  5. exclude_locations: se algum termo casar o local, a vaga é descartada.
  6. locations: se houver lista, ao menos um termo precisa casar cidade/estado/rótulo.

Comparações são feitas sem acento e em minúsculas (via models.normalize).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .models import JobPosting, normalize
from .searches import SearchProfile


@lru_cache(maxsize=1024)
def _compile_term(term_norm: str) -> "re.Pattern":
    """Compila o termo com fronteira de 'palavra' (alfanumérico) nas bordas.

    Assim 'ti' casa 'analista de ti' mas não 'logística'; 'python' casa
    'desenvolvedor python' mas não 'pythonista'. Termos com espaço/pontuação
    (ex.: 'engenheiro de dados', '.net') também funcionam.
    """
    return re.compile(r"(?<![0-9a-z])" + re.escape(term_norm) + r"(?![0-9a-z])")


@dataclass
class MatchResult:
    matched: bool
    reason: str = ""              # motivo da rejeição (para debug/log)
    matched_keywords: list[str] = None

    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = []


def _any_in(terms: list[str], blob: str) -> list[str]:
    """Retorna os termos presentes no blob, casando por fronteira de palavra."""
    hits = []
    for term in terms:
        norm = normalize(term)
        if norm and _compile_term(norm).search(blob):
            hits.append(term)
    return hits


def matches(job: JobPosting, profile: SearchProfile) -> MatchResult:
    """Avalia a vaga contra o perfil de busca."""
    blob = job.search_blob

    # 2. Exclusões primeiro (curto-circuito)
    if profile.exclude_keywords:
        excluded = _any_in(profile.exclude_keywords, blob)
        if excluded:
            return MatchResult(False, f"excluída por: {', '.join(excluded)}")

    # 1. Relevância — modo preciso (filtro de 3 níveis) OU palavra-chave solta.
    matched_kw: list[str] = []
    if profile.precise:
        # Import tardio para evitar ciclo (relevance -> models apenas).
        from .relevance import classify_title
        conf = classify_title(job.title)
        if not conf.passes:
            return MatchResult(False, f"filtro 3 níveis: {conf.reason}")
        # Se também houver keywords, elas restringem ainda mais (opcional).
        if profile.keywords and not _any_in(profile.keywords, blob):
            return MatchResult(False, "nenhuma palavra-chave encontrada")
    elif profile.keywords:
        matched_kw = _any_in(profile.keywords, blob)
        if not matched_kw:
            return MatchResult(False, "nenhuma palavra-chave encontrada")

    # 3. Senioridade
    if profile.seniority and job.seniority not in profile.seniority:
        return MatchResult(False, f"senioridade '{job.seniority}' fora do filtro")

    # 4. Tipo de local
    if profile.workplace_types and job.workplace_type not in profile.workplace_types:
        return MatchResult(False, f"local '{job.workplace_type}' fora do filtro")

    # 5. Localização textual
    if profile.exclude_locations or profile.locations:
        location_blob = normalize(f"{job.city} {job.state} {job.country} {job.location_label}")

        # Exclusão primeiro: barra local claramente fora do alcance do perfil.
        # Local vazio ou genérico ("Remote") passa de propósito — a vaga pode
        # muito bem aceitar o Brasil, e descartá-la perderia vaga boa.
        fora = _any_in(profile.exclude_locations, location_blob) if profile.exclude_locations else []
        if fora:
            return MatchResult(False, f"local excluído por: {', '.join(fora)}")

        if profile.locations and not _any_in(profile.locations, location_blob):
            return MatchResult(False, "localização fora do filtro")

    return MatchResult(True, "ok", matched_kw)


def filter_jobs(jobs: list[JobPosting], profile: SearchProfile) -> list[JobPosting]:
    """Retorna apenas as vagas que casam com o perfil."""
    return [job for job in jobs if matches(job, profile).matched]
