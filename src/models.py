"""
models.py — Estruturas de dados normalizadas, comuns a todos os providers.

Cada provider (Gupy, inhire, ...) converte seu payload próprio em um JobPosting,
de modo que matcher, storage e notifier trabalhem com um formato único.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# Tipos de local de trabalho normalizados
REMOTE = "remote"
HYBRID = "hybrid"
ONSITE = "onsite"
WORKPLACE_UNKNOWN = "unknown"

# Níveis de senioridade normalizados
SENIORITY_ESTAGIO = "estagio"
SENIORITY_JUNIOR = "junior"
SENIORITY_PLENO = "pleno"
SENIORITY_SENIOR = "senior"
SENIORITY_LEAD = "lead"
SENIORITY_UNKNOWN = "indefinido"


def strip_accents(text: str) -> str:
    """Remove acentos, para comparação robusta (ex.: 'sênior' == 'senior')."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados."""
    text = strip_accents(str(text or "")).lower()
    return re.sub(r"\s+", " ", text).strip()


# Padrões de senioridade avaliados na ORDEM abaixo (o primeiro que casar vence).
# Fronteiras de palavra evitam falsos positivos (ex.: 'sr' dentro de outra palavra).
_SENIORITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    (SENIORITY_ESTAGIO, re.compile(r"\b(estagi|intern|trainee)\w*", re.I)),
    (SENIORITY_LEAD, re.compile(r"\b(tech lead|lead|principal|staff|especialista|coordenad|gerent|head|manager)\w*", re.I)),
    (SENIORITY_SENIOR, re.compile(r"\b(senior|sr|iii|pleno/senior|pl/sr)\b", re.I)),
    (SENIORITY_PLENO, re.compile(r"\b(pleno|mid|ii|pl)\b", re.I)),
    (SENIORITY_JUNIOR, re.compile(r"\b(junior|jr|i|entry)\b", re.I)),
]


def infer_seniority(title: str, description: str = "") -> str:
    """
    Deduz a senioridade a partir do título (e, em fallback, da descrição).

    Retorna um dos SENIORITY_* — SENIORITY_UNKNOWN quando nada é reconhecido.
    """
    haystacks = [strip_accents(title or "")]
    # A descrição costuma ser ruidosa; só é consultada para estágio/júnior/sênior
    # explícitos, evitando classificar errado por causa de texto solto.
    desc_norm = strip_accents(description or "")

    for level, pattern in _SENIORITY_PATTERNS:
        for hay in haystacks:
            if pattern.search(hay):
                return level

    # Fallback conservador só para sinais fortes na descrição
    for level in (SENIORITY_ESTAGIO, SENIORITY_SENIOR, SENIORITY_JUNIOR):
        pattern = dict(_SENIORITY_PATTERNS)[level]
        if pattern.search(desc_norm):
            return level

    return SENIORITY_UNKNOWN


@dataclass
class JobPosting:
    """Vaga normalizada, independente do provider de origem."""

    provider: str                 # "gupy" | "inhire" | ...
    external_id: str              # id da vaga no provider
    title: str
    company: str
    url: str
    description: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    workplace_type: str = WORKPLACE_UNKNOWN   # remote | hybrid | onsite | unknown
    seniority: str = SENIORITY_UNKNOWN
    published_date: str = ""
    deadline: str = ""

    def __post_init__(self):
        if self.seniority in (None, "", SENIORITY_UNKNOWN):
            self.seniority = infer_seniority(self.title, self.description)

    @property
    def stable_id(self) -> str:
        """Identificador único e determinístico (provider + id externo)."""
        base = f"{self.provider}:{self.external_id}".strip(":")
        if self.external_id:
            return base[:120]
        # Fallback: hash do título + empresa quando não há id externo
        key = f"{self.provider}|{normalize(self.title)}|{normalize(self.company)}"
        return f"{self.provider}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"

    @property
    def location_label(self) -> str:
        if self.workplace_type == REMOTE:
            base = "Remoto"
        else:
            parts = [p for p in (self.city, self.state) if p]
            base = ", ".join(parts) if parts else (self.country or "Local não informado")
        if self.workplace_type == HYBRID:
            base = f"{base} (Híbrido)" if base and base != "Remoto" else "Híbrido"
        return base

    @property
    def search_blob(self) -> str:
        """Texto normalizado usado pelo matcher (título + empresa + descrição)."""
        return normalize(f"{self.title} {self.company} {self.description}")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "external_id": self.external_id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "description": self.description,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "workplace_type": self.workplace_type,
            "seniority": self.seniority,
            "published_date": self.published_date,
            "deadline": self.deadline,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobPosting":
        return cls(
            provider=data.get("provider", ""),
            external_id=str(data.get("external_id", "")),
            title=data.get("title", ""),
            company=data.get("company", ""),
            url=data.get("url", ""),
            description=data.get("description", ""),
            city=data.get("city", ""),
            state=data.get("state", ""),
            country=data.get("country", ""),
            workplace_type=data.get("workplace_type", WORKPLACE_UNKNOWN),
            seniority=data.get("seniority", SENIORITY_UNKNOWN),
            published_date=data.get("published_date", ""),
            deadline=data.get("deadline", ""),
        )
