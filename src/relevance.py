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
    # --- cargos que o filtro deixava passar batido ---
    "analytics engineer", "engenheiro de analytics", "analista de analytics",
    "business intelligence", "bi analyst", "bi developer",
    "administrador de dados", "data steward", "engenheiro de qualidade de dados",
    "testador de software", "testador", "testadora", "qa engineer",
    "test engineer", "engenheiro de testes", "analista de qualidade de software",
    "analista de infraestrutura", "engenheiro de redes", "network engineer",
    "suporte tecnico", "analista de suporte",
    # "dev" abreviado: ".NET DEV", "Dev Back Java". A fronteira de palavra
    # impede que case dentro de "development", então "business development"
    # continua de fora.
    "dev", "devs",
    # --- espanhol: LatAm entrou no radar com dlocal, kavak, veritran, lahaus ---
    "desarrollador", "desarrolladora", "desarrollo de software",
    "ingeniero de software", "ingeniera de software",
    "ingeniero de datos", "ingeniera de datos",
    "ingeniero de sistemas", "cientifico de datos", "cientifica de datos",
    "arquitecto de software", "arquitecto de soluciones",
    "analista de datos", "analista de sistemas",
    "programador", "programadora",
    # variantes que a fronteira de palavra deixava escapar: "tech lead" não
    # casa em "tech leader", e "engenheiro de software" não casa em
    # "engenharia de software".
    "tech leader", "technical leader", "lider tecnico", "team lead",
    "engenharia de software", "engenharia de computacao", "engenharia de dados",
    "mobile engineer", "engenheiro mobile", "desenvolvedor mobile",
    "mobile developer", "android developer", "ios developer",
    "desenvolvedor android", "desenvolvedor ios",
    # formas nominais: o vocabulário só tinha a do profissional
    # ("cientista de dados"), não a da área ("ciencia de dados").
    "ciencia de dados", "data science", "data engineering",
    "engenharia de banco de dados", "database engineering",
    "desenvolvimento de software", "software development",
    "engenharia de qualidade", "quality engineering",
    "data architect", "arquiteta de software", "arquiteta de solucoes",
    "qualidade de software", "eng de software", "eng de dados",
]

# Cargos ambíguos: só contam com um qualificador de tech junto.
AMBIGUOUS_ROLES = [
    "analista", "analyst", "business analyst", "consultor", "consultora",
    "especialista", "coordenador", "coordenadora", "gerente", "assistente",
    "estagiario", "estagiaria", "estagio", "trainee", "jovem aprendiz",
    "engenheiro", "engenheira", "arquiteto", "lider", "coordenacao",
    # espanhol
    "ingeniero", "ingeniera", "arquitecto", "practicante", "pasante",
    "asistente", "coordinador", "coordinadora", "gerente de",
    # inglês genérico que aparece muito em board internacional
    "associate", "specialist", "intern", "engineer", "leader",
    "gestor", "gestora", "manager", "administrador", "administradora",
    "cientista", "arquiteta", "scientist", "architect",
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
    # espanhol
    "datos", "seguridad", "nube", "informatica", "programacion",
    "aprendizaje automatico", "desarrollo", "tecnologia de la informacion",
    # plataformas: salvam cargo ambíguo ("Arquiteto ... Mobile", "Mobile Engineer")
    "mobile", "android", "ios", "web", "api", "microservicos", "microservicios",
]

# Ferramentas/stacks concretas: só contam com uma palavra de cargo junto.
TOOLS = [
    "power bi", "powerbi", "sql", "python", "java", "javascript", "typescript",
    "react", "angular", "vue", "node", "nodejs", ".net", "c#", "php", "ruby", "go",
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
    "spark", "databricks", "hadoop", "airflow", "kafka", "snowflake",
    "tableau", "looker", "qlik", "excel avancado", "pandas", "scala",
    "dbt", "bigquery", "redshift", "postgres", "postgresql", "mysql",
    "mongodb", "elasticsearch", "kotlin", "swift", "rust", "flutter",
    "laravel", "django", "spring boot", "quarkus", "camel",
]

# (ROLE_WORDS foi absorvida por ROLE_NOUNS, mais abaixo: mesma ideia, com
# curinga de gênero/plural e os termos em espanhol.)


# Conectivos: só ligam palavras, não mudam o cargo. Removê-los faz
# "engenheiro de banco de dados" e "engenheiro banco dados" virarem o mesmo
# texto, em vez de exigir uma entrada de vocabulário para cada grafia.
_CONECTIVOS = frozenset((
    "de", "da", "do", "das", "dos", "del", "la", "el", "los", "las",
    "of", "the", "in", "on", "for", "em", "no", "na", "nos", "nas",
    "e", "y", "and", "com", "with", "para", "a", "o", "um", "uma",
))
_SEPARADOR = re.compile(r"[^0-9a-z#.+]+")


@lru_cache(maxsize=8192)
def canon(texto: str) -> str:
    """Normaliza e joga fora conectivos, deixando só as palavras que carregam sentido."""
    palavras = [p for p in _SEPARADOR.split(normalize(texto)) if p and p not in _CONECTIVOS]
    return " ".join(palavras)


@lru_cache(maxsize=8192)
def _term_re(term_canon: str) -> "re.Pattern":
    """Compila o termo. Sufixo '*' aceita continuação da palavra.

    É assim que "tech lead*" cobre lead, leader e leads de uma vez, em vez de
    uma entrada por variação — a fronteira de palavra sozinha tratava
    "tech leader" como termo diferente de "tech lead".
    """
    if term_canon.endswith("*"):
        corpo = re.escape(term_canon[:-1]) + "[a-z]*"
    else:
        corpo = re.escape(term_canon)
    return re.compile("(?<![0-9a-z])" + corpo + "(?![0-9a-z])")


def _present(terms, blob: str) -> bool:
    """`blob` já deve vir de canon()."""
    return any(_term_re(canon(t) if not t.endswith("*") else canon(t[:-1]) + "*").search(blob)
               for t in terms)


# ---------------------------------------------------------------------------
# Filtro em 3 níveis
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regra combinatória: núcleo de cargo + domínio de tech
#
# "Engenheiro de banco de dados", "administrador banco dados" e "arquiteto de
# dados" são a mesma função escrita de três jeitos. Em vez de uma entrada de
# vocabulário por grafia, o par (quem faz) × (sobre o quê) resolve todas.
# O sufixo '*' cobre gênero e plural: desenvolvedor/a/es numa entrada só.
# ---------------------------------------------------------------------------

# Quem faz. São núcleos de cargo, não cargos completos.
ROLE_NOUNS = [
    "desenvolvedor*", "desenvolvimento", "developer*", "programador*",
    "engenheiro*", "engenheira*", "engenharia", "engineer*",
    "arquiteto*", "arquiteta*", "architect*", "arquitectura",
    "analista*", "analyst*", "cientista*", "scientist*",
    "administrador*", "administradora*", "especialista*", "specialist*",
    "consultor*", "tecnico*", "technician", "coordenador*", "gestor*",
    "gerente*", "manager*", "lider*", "lead*", "leader*", "head",
    "estagiario*", "estagio", "trainee", "intern", "aprendiz",
    # espanhol
    "ingeniero*", "ingeniera*", "ingenieria", "desarrollador*", "desarrollo",
    "cientifico*", "arquitecto*", "practicante*", "pasante*",
]

# Sobre o quê. Só entra domínio que, sozinho, já é inequivocamente de tech —
# por isso "desenvolvimento" e "produto" ficam de fora: existem em vendas,
# mercado e RH ("desenvolvimento de mercado", "desenvolvimento humano").
TECH_DOMAINS = [
    "software", "sistemas", "systems", "dados", "data", "datos",
    "banco de dados", "base de datos", "database", "bi",
    "business intelligence", "analytics", "machine learning", "ml",
    "inteligencia artificial", "artificial intelligence", "ia", "ai",
    "cloud", "nuvem", "nube", "devops", "sre", "infraestrutura",
    "infraestructura", "infrastructure", "redes", "networks", "seguranca",
    "seguridad", "security", "qa", "testes", "testing", "qualidade de software",
    "backend", "back-end", "frontend", "front-end", "fullstack", "full stack",
    "mobile", "android", "ios", "web", "api", "microservicos", "microservicios",
    "computacao", "informatica", "tecnologia da informacao", "ti", "it",
    "plataforma", "platform", "dbre", "etl", "big data",
]

# Trava de segurança: mesmo com cargo + domínio, estes contextos derrubam a
# vaga. "Consultor de vendas de software" é vaga de vendas, não de tech.
DENY_CONTEXT = [
    "vendas", "venda", "comercial", "sales", "sdr", "pre-vendas", "pos-vendas",
    "account executive", "customer success", "atendimento", "call center",
    "recursos humanos", "recrutamento", "recruiter",
    "contabil", "fiscal", "juridico", "advogado",
    "midia", "publicidade", "trafego pago",
    # "marketing", "growth", "people" e "financeiro" ficaram DE FORA de
    # propósito: "Marketing Analytics", "People Analytics" e "Analista de
    # Dados | Financeiro" são vagas de dados de verdade. Sem cargo nem
    # domínio de tech, esses títulos já são reprovados pelas regras normais.
    "enfermeiro*", "enfermagem", "medico*", "medica*", "psicologo*",
    "professor*", "docente", "instrutor*", "monitoria",
    "limpeza", "motorista", "entregador*", "seguranca patrimonial",
    "mercado", "negocios", "business development",
]


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
    blob = canon(title)

    # Cargo inequívoco vence o contexto: "Dev Backend — Segmento Financeiro" e
    # "Data Analyst - Marketing" são vagas de tech dentro de outra área do
    # negócio, não vagas daquela área.
    if _present(STRONG_ROLES, blob):
        return Confidence(True, CONF_ALTA, "cargo de tech inequívoco no título")

    # Daqui para baixo o sinal é fraco, então contexto de outra área veta:
    # "Consultor de vendas de software" casaria cargo + domínio sem ser tech.
    de_outra_area = _present(DENY_CONTEXT, blob)

    # Núcleo de cargo + domínio de tech, em qualquer ordem e sem depender de
    # conectivo: cobre "engenheiro de banco de dados" e "administrador banco
    # dados" com a mesma regra, no mesmo nível.
    if not de_outra_area and _present(ROLE_NOUNS, blob) and _present(TECH_DOMAINS, blob):
        return Confidence(True, CONF_ALTA, "cargo + domínio de tech no título")

    if not de_outra_area and _present(AMBIGUOUS_ROLES, blob) and _present(QUALIFIERS, blob):
        return Confidence(True, CONF_MEDIA, "cargo ambíguo + qualificador de tech")

    # ROLE_NOUNS no lugar de ROLE_WORDS: mesma ideia de "palavra de cargo", mas
    # com curinga de gênero/plural e os termos em espanhol.
    if not de_outra_area and _present(TOOLS, blob) and _present(ROLE_NOUNS, blob):
        return Confidence(True, CONF_BAIXA, "ferramenta + palavra de cargo")

    if de_outra_area:
        return Confidence(False, CONF_NENHUM, "título é de outra área")
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
