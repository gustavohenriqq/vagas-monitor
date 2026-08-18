"""
relevance.py — Filtro em 3 níveis de confiança + score de relevância (sem ML).

Inspirado na arquitetura do JobRadar, reimplementado para "todo tech" (não só
dados). A ideia central: NÃO aprovar por palavra-chave solta.

Três níveis de confiança:
  ALTA  — cargo inequívoco no título (ex.: "Desenvolvedor", "Engenheiro de Dados")
          passa sozinho.
  MEDIA — cargo ambíguo (ex.: "Analista", "Consultor") só conta se houver um
          qualificador de tech junto no título (ex.: "de dados", "de sistemas").
  BAIXA — ferramenta (ex.: "Power BI", "SQL", "React") só conta se houver uma
          palavra de cargo junto (ex.: "Analista de Power BI").

O score (0–10) soma sinais conhecidos: nível de confiança, senioridade, presença
de ferramenta concreta, modelo de trabalho e mercado/idioma. Serve para decidir
o que notificar na hora vs. o que agrupar no digest, e para ranquear o digest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .models import (
    HYBRID,
    REMOTE,
    SENIORITY_UNKNOWN,
    JobPosting,
    normalize,
)

CONF_ALTA = "alta"
CONF_MEDIA = "media"
CONF_BAIXA = "baixa"
CONF_NENHUM = "nenhum"


# ---------------------------------------------------------------------------
# Vocabulário (tudo em minúsculas e sem acento — comparado via normalize())
# ---------------------------------------------------------------------------

# Cargos inequívocos de tech: aprovam sozinhos.
STRONG_ROLES = [
    "desenvolvedor", "desenvolvedora", "developer", "programador", "programadora",
    "engenheiro de software", "engenheira de software", "software engineer",
    "engenheiro de dados", "engenharia de dados", "data engineer",
    "cientista de dados", "data scientist",
    "engenheiro de machine learning", "ml engineer", "mlops",
    "analista de dados", "data analyst",
    "analista de sistemas", "analista de ti",
    "analista de bi", "engenheiro de bi",
    "devops", "sre", "site reliability",
    "qa", "sdet", "analista de testes", "analista de qa", "tester", "quality assurance",
    "dba", "administrador de banco de dados", "database administrator",
    "arquiteto de software", "arquiteto de solucoes", "arquiteto de dados",
    "solutions architect", "software architect",
    "product manager", "product owner", "gerente de produto",
    "scrum master", "agilista",
    "fullstack", "full stack", "full-stack",
    "front-end", "frontend", "front end",
    "back-end", "backend", "back end",
    "tech lead", "engenheiro de plataforma", "platform engineer",
    "engenheiro de seguranca", "security engineer", "analista de seguranca da informacao",
    "engenheiro de dados", "engenheiro de machine learning",
]

# Cargos ambíguos: só contam com um qualificador de tech junto.
AMBIGUOUS_ROLES = [
    "analista", "analyst", "business analyst", "consultor", "consultora",
    "especialista", "coordenador", "coordenadora", "gerente", "assistente",
    "estagiario", "estagiaria", "estagio", "trainee", "jovem aprendiz",
    "engenheiro", "engenheira", "arquiteto", "lider", "coordenacao",
]

# Qualificadores que "salvam" um cargo ambíguo (contexto tech/dados).
QUALIFIERS = [
    "dados", "data", "bi", "business intelligence", "analytics",
    "software", "sistemas", "ti", "tecnologia", "desenvolvimento",
    "backend", "back-end", "frontend", "front-end", "fullstack", "full stack",
    "cloud", "devops", "seguranca da informacao", "machine learning", "ml",
    "inteligencia artificial", "ia", "infraestrutura", "banco de dados",
    "python", "java", "javascript", "typescript", ".net", "node",
    "qa", "teste", "automacao",
]

# Ferramentas/stacks concretas: só contam com uma palavra de cargo junto.
TOOLS = [
    "power bi", "powerbi", "sql", "python", "java", "javascript", "typescript",
    "react", "angular", "vue", "node", "nodejs", ".net", "c#", "php", "ruby", "go",
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
    "spark", "databricks", "hadoop", "airflow", "kafka", "snowflake",
    "tableau", "looker", "qlik", "excel avancado", "pandas", "scala",
]

# Palavras genéricas de cargo, usadas para validar uma ferramenta.
ROLE_WORDS = [
    "desenvolvedor", "desenvolvedora", "developer", "programador", "engenheiro",
    "engenheira", "analista", "cientista", "arquiteto", "especialista",
    "consultor", "consultora", "estagiario", "estagio", "trainee", "engineer",
    "analyst", "developer", "administrador", "lider", "coordenador", "tech lead",
]


@lru_cache(maxsize=4096)
def _term_re(term_norm: str) -> "re.Pattern":
    return re.compile(r"(?<![0-9a-z])" + re.escape(term_norm) + r"(?![0-9a-z])")


def _present(terms: list[str], blob: str) -> bool:
    return any(_term_re(normalize(t)).search(blob) for t in terms)


# ---------------------------------------------------------------------------
# Filtro em 3 níveis
# ---------------------------------------------------------------------------

@dataclass
class Confidence:
    passes: bool
    level: str          # alta | media | baixa | nenhum
    reason: str


def classify_title(title: str) -> Confidence:
    """
    Classifica o TÍTULO da vaga em um nível de confiança de que é uma vaga tech.

    Avalia só o título (não a descrição), como o JobRadar: o título carrega o
    cargo e evita falsos positivos de menções soltas no corpo do anúncio.
    """
    blob = normalize(title)

    if _present(STRONG_ROLES, blob):
        return Confidence(True, CONF_ALTA, "cargo de tech inequívoco no título")

    if _present(AMBIGUOUS_ROLES, blob) and _present(QUALIFIERS, blob):
        return Confidence(True, CONF_MEDIA, "cargo ambíguo + qualificador de tech")

    if _present(TOOLS, blob) and _present(ROLE_WORDS, blob):
        return Confidence(True, CONF_BAIXA, "ferramenta + palavra de cargo")

    return Confidence(False, CONF_NENHUM, "sem cargo de tech claro no título")


# ---------------------------------------------------------------------------
# Score de relevância (0–10)
# ---------------------------------------------------------------------------

_LEVEL_BASE = {CONF_ALTA: 6, CONF_MEDIA: 4, CONF_BAIXA: 2, CONF_NENHUM: 0}


def score_job(job: JobPosting, conf: Confidence | None = None) -> tuple[int, list[str]]:
    """
    Pontua a vaga de 0 a 10 somando sinais explícitos. Retorna (score, motivos).
    """
    conf = conf or classify_title(job.title)
    if not conf.passes:
        return 0, ["não passou no filtro de cargo"]

    score = _LEVEL_BASE.get(conf.level, 0)
    reasons = [conf.reason]

    title_blob = normalize(job.title)
    full_blob = job.search_blob

    if job.workplace_type == REMOTE:
        score += 2
        reasons.append("remoto")
    elif job.workplace_type == HYBRID:
        score += 1
        reasons.append("híbrido")

    if _present(TOOLS, title_blob) or _present(TOOLS, full_blob):
        score += 1
        reasons.append("stack/ferramenta concreta")

    if job.seniority != SENIORITY_UNKNOWN:
        score += 1
        reasons.append(f"senioridade: {job.seniority}")

    return min(score, 10), reasons


@dataclass
class Relevance:
    passes: bool
    level: str
    score: int
    reasons: list[str]


def evaluate(job: JobPosting) -> Relevance:
    """Combina filtro + score num único resultado."""
    conf = classify_title(job.title)
    if not conf.passes:
        return Relevance(False, conf.level, 0, [conf.reason])
    score, reasons = score_job(job, conf)
    return Relevance(True, conf.level, score, reasons)
