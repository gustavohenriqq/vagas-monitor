"""
inhire.py — Provider do inhire (por empresa / tenant).

O inhire NÃO tem busca global pública. Cada empresa expõe sua página de carreira:
    GET https://api.inhire.app/job-posts/public/pages
    Header obrigatório:  X-Tenant: <tenant>       (o subdomínio: tenant.inhire.app)

Este provider recebe a lista de tenants (empresas) e consulta cada um, devolvendo
todas as vagas publicadas normalizadas. O filtro por palavra-chave/senioridade/
local é aplicado depois, pelo matcher.

Como o schema exato de resposta pode variar, o parser é defensivo: procura a
lista de vagas em várias chaves possíveis e extrai cada campo por nomes
alternativos, com valores padrão seguros.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from ..models import (
    HYBRID,
    ONSITE,
    REMOTE,
    SENIORITY_ESTAGIO,
    SENIORITY_JUNIOR,
    SENIORITY_LEAD,
    SENIORITY_PLENO,
    SENIORITY_SENIOR,
    SENIORITY_UNKNOWN,
    WORKPLACE_UNKNOWN,
    JobPosting,
    strip_accents,
)
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

INHIRE_PAGES_URL = "https://api.inhire.app/job-posts/public/pages"

# Chaves onde a lista de vagas pode aparecer no payload. `jobsPage` é a real
# (observada na API pública); as demais ficam como fallback defensivo.
_JOB_LIST_KEYS = ("jobsPage", "jobPosts", "jobPostings", "jobs", "vacancies", "vagas", "data", "items", "results")

# Status considerados "vaga aberta" (o restante — draft, closed — é ignorado).
_OPEN_STATUS = ("published", "publicada", "aberta", "open", "active", "")

# Códigos de país -> nome amigável para exibição.
_COUNTRY_NAMES = {"BR": "Brasil", "PT": "Portugal", "US": "EUA", "SG": "Singapura"}


def _parse_location(loc) -> tuple[str, str, str]:
    """Interpreta o campo location. Aceita string ('Rio de Janeiro, RJ, BR',
    'BR') ou dict ({city, state}). Retorna (city, state, country)."""
    if isinstance(loc, dict):
        return (
            str(loc.get("city") or "").strip(),
            str(loc.get("state") or loc.get("uf") or "").strip(),
            str(loc.get("country") or "").strip(),
        )
    parts = [p.strip() for p in str(loc or "").split(",") if p.strip()]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        # Um único token curto (ex.: 'BR') é país; caso contrário, cidade.
        only = parts[0]
        return ("", "", only) if len(only) <= 3 else (only, "", "")
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], parts[1], parts[-1]


def _country_name(code: str) -> str:
    code = str(code or "").strip()
    return _COUNTRY_NAMES.get(code.upper(), code)


def _first(item: dict, *keys, default=""):
    """Retorna o primeiro valor não vazio entre as chaves informadas."""
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return default


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _map_workplace(value) -> str:
    raw = strip_accents(str(value or "")).lower().replace("-", "").replace("_", "").replace(" ", "")
    if raw in ("remote", "remoto", "homeoffice", "anywhere"):
        return REMOTE
    if raw in ("hybrid", "hibrido"):
        return HYBRID
    if raw in ("onsite", "presencial", "office", "local"):
        return ONSITE
    return WORKPLACE_UNKNOWN


def _map_seniority(value) -> str:
    raw = strip_accents(str(value or "")).lower()
    if not raw:
        return SENIORITY_UNKNOWN
    if "estag" in raw or "intern" in raw or "trainee" in raw:
        return SENIORITY_ESTAGIO
    if "junior" in raw or raw == "jr":
        return SENIORITY_JUNIOR
    if "pleno" in raw or raw == "pl" or "mid" in raw:
        return SENIORITY_PLENO
    if "senior" in raw or raw == "sr":
        return SENIORITY_SENIOR
    if any(w in raw for w in ("lead", "principal", "staff", "especialista", "coordenad", "gerent", "head")):
        return SENIORITY_LEAD
    return SENIORITY_UNKNOWN


def _find_job_list(payload) -> list:
    """Localiza a lista de vagas no payload, testando chaves conhecidas e recursão."""
    if isinstance(payload, list):
        # lista de vagas direta ou lista de páginas
        if payload and isinstance(payload[0], dict) and any(
            k in payload[0] for k in ("title", "name", "jobName", "displayName")
        ):
            return payload
        for page in payload:
            found = _find_job_list(page)
            if found:
                return found
        return []

    if isinstance(payload, dict):
        for key in _JOB_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list) and value:
                # confirma que parece uma lista de vagas
                if isinstance(value[0], dict) and any(
                    k in value[0] for k in ("title", "name", "jobName", "displayName", "jobId", "id", "slug")
                ):
                    return value
        # procura recursivamente em subdicionários (ex.: page -> jobPosts)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                found = _find_job_list(value)
                if found:
                    return found
    return []


def _job_url(tenant: str, item: dict) -> str:
    """Monta a URL pública da vaga a partir do tenant + id/slug."""
    direct = _first(item, "url", "jobUrl", "link", default="")
    if direct and str(direct).startswith("http"):
        return str(direct)
    job_id = _first(item, "id", "jobId", "uuid", "jobPostId", default="")
    slug = _first(item, "slug", "friendlyUrl", "permalink", default="")
    base = f"https://{tenant}.inhire.app/vagas"
    if job_id and slug:
        return f"{base}/{job_id}/{slug}"
    if job_id:
        return f"{base}/{job_id}"
    return base


def parse_jobs(payload, tenant: str, company_name: str = "") -> list[JobPosting]:
    """Converte a resposta pública do inhire em JobPosting para um tenant.

    Formato real (endpoint /job-posts/public/pages):
        {"tenantName": "Radix", "jobsPage": [
            {"jobId", "displayName", "status", "workplaceType", "location"}, ...]}
    """
    company = company_name
    items = None
    if isinstance(payload, dict):
        company = company or str(payload.get("tenantName") or "").strip()
        items = payload.get("jobsPage")
    if not isinstance(items, list):
        items = _find_job_list(payload)  # fallback para outros formatos
    company = company or tenant

    jobs: list[JobPosting] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        status = str(item.get("status") or "").strip().lower()
        if status and status not in _OPEN_STATUS:
            continue  # ignora rascunho/encerrada

        title = str(_first(item, "displayName", "title", "name", "jobName", "role", default="")).strip()
        if not title:
            continue

        job_id = str(_first(item, "jobId", "id", "uuid", "jobPostId", "slug", default="")).strip()
        city, state, country = _parse_location(_first(item, "location", "city", "address", default=""))
        if not state:
            state = str(_first(item, "state", "uf", default="")).strip()

        workplace = _map_workplace(
            _first(item, "workplaceType", "workModel", "modality", "workType", "remote", default="")
        )
        if workplace == WORKPLACE_UNKNOWN and item.get("isRemote") is True:
            workplace = REMOTE

        jobs.append(
            JobPosting(
                provider="inhire",
                external_id=f"{tenant}:{job_id}" if job_id else f"{tenant}:{title[:40]}",
                title=title,
                company=company,
                url=_job_url(tenant, item),
                description=_clean_html(_first(item, "description", "descriptionText", "about", default=""))[:5000],
                city=city,
                state=state,
                country=_country_name(country) or "Brasil",
                workplace_type=workplace,
                seniority=_map_seniority(_first(item, "seniority", "seniorityLevel", "level", default="")),
                published_date=str(_first(item, "publishedAt", "publishedDate", "createdAt", default="")).strip(),
                deadline=str(_first(item, "deadline", "applicationDeadline", "expiresAt", default="")).strip(),
            )
        )
    return jobs


class InhireProvider(JobProvider):
    name = "inhire"

    def __init__(self, tenants: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.tenants = [t.strip().lower() for t in (tenants or []) if t.strip()]

    def _fetch_tenant(self, tenant: str, max_jobs: int) -> list[JobPosting]:
        payload = fetch_json(
            self._session,
            INHIRE_PAGES_URL,
            headers={"X-Tenant": tenant},
            delay=self.delay,
        )
        if not payload:
            logger.warning("inhire: sem dados para o tenant '%s'.", tenant)
            return []
        jobs = parse_jobs(payload, tenant)
        logger.info("inhire[%s]: %d vagas publicadas.", tenant, len(jobs))
        return jobs[:max_jobs]

    def search(self, keywords: list[str], *, max_jobs: int = 200, tenants: Optional[list[str]] = None, **kwargs) -> list[JobPosting]:
        """
        Coleta as vagas publicadas de cada empresa (tenant) configurada.

        As `keywords` NÃO são enviadas ao inhire (não há busca no servidor); a
        filtragem por termo é feita depois pelo matcher. Aqui apenas trazemos o
        universo de vagas publicadas de cada empresa.
        """
        active_tenants = [t.strip().lower() for t in (tenants or self.tenants) if t.strip()]
        if not active_tenants:
            logger.info("inhire: nenhuma empresa (tenant) configurada. Pulando.")
            return []

        seen: set[str] = set()
        result: list[JobPosting] = []
        for tenant in active_tenants:
            for job in self._fetch_tenant(tenant, max_jobs):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)

        logger.info("inhire: %d vagas únicas em %d empresas.", len(result), len(active_tenants))
        return result
