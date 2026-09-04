"""
recrutei.py — Provider Recrutei (páginas públicas de carreira).

O Recrutei expõe as vagas públicas de cada empresa em jobs.recrutei.com.br/<slug>,
alimentadas por um endpoint público (não o da API documentada, que é autenticada).

Estrutura da resposta (observada):
    {"message": "...", "data": {
        "total": 207, "departments": 4,
        "vacancies": [
            {"department": "Governo", "total": 126, "items": [
                {"id", "title", "regime", "department", "company_name",
                 "salary", "location": ["Cidade","UF","País"] | "Não informado",
                 "public_link", "slug"} , ...]},
            ...]}}

As vagas vêm AGRUPADAS por departamento; este parser achata tudo.

O endpoint público é montado a partir de RECRUTEI_URL_TEMPLATE + o slug da empresa.
Ajuste o template quando confirmar a URL exata (via DevTools → Request URL).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..models import ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting
from .base import JobProvider

logger = logging.getLogger(__name__)

# Endpoint público confirmado (via DevTools): POST com corpo {} e Content-Type
# application/json. "{slug}" é o identificador da empresa (ex.: "digisystem").
RECRUTEI_URL_TEMPLATE = "https://api.recrutei.com.br/api/v2/vacancies/per-departments/{slug}"
REQUEST_TIMEOUT = 20
_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": "https://jobs.recrutei.com.br",
    "Referer": "https://jobs.recrutei.com.br/",
    # UA de navegador real: com o UA "robô" a API responde 202 sem corpo.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}


def _parse_location(loc) -> tuple[str, str, str]:
    """location vem como ['Cidade','UF','País'], ['País'] ou 'Não informado'."""
    if isinstance(loc, list):
        parts = [str(p).strip() for p in loc if str(p).strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], "", parts[1]
        if len(parts) == 1:
            return "", "", parts[0]       # só país (ex.: "Brasil")
    return "", "", ""


def _infer_workplace(city: str, state: str) -> str:
    """Heurística: sem cidade/UF (só 'Brasil') tende a ser remoto/nacional;
    com cidade é presencial. O Recrutei não expõe o modelo na listagem."""
    if not city and not state:
        return REMOTE
    if city or state:
        return ONSITE
    return WORKPLACE_UNKNOWN


def parse_jobs(payload, company_slug: str, company_name: str = "") -> list[JobPosting]:
    """Achata os departamentos e converte cada vaga em JobPosting."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    groups = data.get("vacancies")
    if not isinstance(groups, list):
        return []

    jobs: list[JobPosting] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for item in (group.get("items") or []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("public_link") or "").strip()
            if not title or not url:
                continue

            city, state, country = _parse_location(item.get("location"))
            company = company_name or str(item.get("company_name") or "").strip() or company_slug

            jobs.append(
                JobPosting(
                    provider="recrutei",
                    external_id=f"{company_slug}:{item.get('id')}",
                    title=title,
                    company=company,
                    url=url,
                    description=str(item.get("department") or "").strip(),
                    city=city,
                    state=state,
                    country=country or "Brasil",
                    workplace_type=_infer_workplace(city, state),
                )
            )
    return jobs


class RecruteiProvider(JobProvider):
    name = "recrutei"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0,
                 url_template: str = RECRUTEI_URL_TEMPLATE):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]
        self.url_template = url_template

    def _fetch_company(self, slug: str, max_jobs: int) -> list[JobPosting]:
        url = self.url_template.format(slug=slug)
        payload = None
        for attempt in range(1, 3):
            try:
                resp = self._session.post(url, json={}, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
                # A API pode responder 200 ou 202 com o corpo JSON.
                if resp.status_code in (200, 202):
                    try:
                        data = resp.json()
                    except ValueError:
                        data = None
                    if data and (data.get("data") if isinstance(data, dict) else None):
                        payload = data
                        break
                    # 202 sem corpo útil: costuma ser proteção/UA. Tenta de novo.
                    logger.warning("Recrutei: HTTP %d sem corpo para '%s' (tentativa %d).",
                                   resp.status_code, slug, attempt)
                else:
                    logger.warning("Recrutei: HTTP %d para '%s'.", resp.status_code, slug)
                    if resp.status_code < 500:
                        break
            except Exception as exc:
                logger.warning("Recrutei: erro em '%s' (tentativa %d): %s", slug, attempt, exc)
            time.sleep(self.delay)
        if not payload:
            logger.warning("Recrutei: sem dados para '%s'.", slug)
            return []
        jobs = parse_jobs(payload, slug)
        logger.info("Recrutei[%s]: %d vagas.", slug, len(jobs))
        return jobs[:max_jobs]

    def search(self, keywords: list[str], *, max_jobs: int = 200, companies: Optional[list[str]] = None, **kwargs) -> list[JobPosting]:
        active = [c.strip() for c in (companies or self.companies) if c.strip()]
        if not active:
            logger.info("Recrutei: nenhuma empresa configurada. Pulando.")
            return []
        seen: set[str] = set()
        result: list[JobPosting] = []
        for slug in active:
            for job in self._fetch_company(slug, max_jobs):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
        logger.info("Recrutei: %d vagas únicas em %d empresas.", len(result), len(active))
        return result
