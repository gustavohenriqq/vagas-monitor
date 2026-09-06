"""
smartrecruiters.py — Provider SmartRecruiters (API pública de postings, por empresa).

    GET https://api.smartrecruiters.com/v1/companies/<company>/postings
        ?limit=100&offset=<n>

Resposta: {"offset","limit","totalFound","content": [{"id","name"(título),"ref",
    "location":{"city","region","country","remote"},"customField",...}]}

A API devolve no máximo 100 vagas por página; boards grandes (o da Bosch tem
~4.800 vagas) precisam ser paginados via `offset`, senão só a primeira página é
vista. `max_jobs` é o teto POR empresa, como no provider do Greenhouse.

URL pública da vaga: https://jobs.smartrecruiters.com/<company>/<id>
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..models import ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

SMARTR_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
SMARTR_PAGE_LIMIT = 100   # máximo aceito pela API por página
SMARTR_MAX_PAGES = 20     # trava de segurança: até 2.000 vagas por empresa


def parse_jobs(payload, company: str) -> list[JobPosting]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("content")
    if not isinstance(items, list):
        return []
    jobs: list[JobPosting] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("name") or "").strip()
        job_id = str(it.get("id") or "").strip()
        if not title or not job_id:
            continue
        loc = it.get("location") or {}
        city = str(loc.get("city") or "").strip() if isinstance(loc, dict) else ""
        region = str(loc.get("region") or "").strip() if isinstance(loc, dict) else ""
        is_remote = bool(loc.get("remote")) if isinstance(loc, dict) else False
        jobs.append(JobPosting(
            provider="smartrecruiters",
            external_id=f"{company}:{job_id}",
            title=title,
            company=company,
            url=f"https://jobs.smartrecruiters.com/{company}/{job_id}",
            description="",
            city=city,
            state=region,
            country=str(loc.get("country") or "").strip() if isinstance(loc, dict) else "",
            workplace_type=REMOTE if is_remote else (ONSITE if city else WORKPLACE_UNKNOWN),
            published_date=str(it.get("releasedDate") or "").strip(),
        ))
    return jobs


class SmartRecruitersProvider(JobProvider):
    name = "smartrecruiters"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]

    def _fetch_company(self, company: str, max_jobs: int) -> list[JobPosting]:
        """Percorre as páginas da empresa via offset/limit até esgotar `totalFound`."""
        jobs: list[JobPosting] = []
        offset = 0
        truncated = True
        for page in range(SMARTR_MAX_PAGES):
            payload = fetch_json(
                self._session,
                SMARTR_URL.format(company=company),
                params={"limit": SMARTR_PAGE_LIMIT, "offset": offset},
                delay=self.delay,
            )
            if not payload:
                if page == 0:
                    logger.warning("SmartRecruiters: sem dados para '%s'.", company)
                truncated = False
                break

            jobs.extend(parse_jobs(payload, company))

            # `content` é a página crua: se veio incompleta, era a última.
            content = payload.get("content")
            page_size = len(content) if isinstance(content, list) else 0
            total = payload.get("totalFound")
            offset += SMARTR_PAGE_LIMIT

            if page_size < SMARTR_PAGE_LIMIT or len(jobs) >= max_jobs:
                truncated = False
                break
            if isinstance(total, int) and offset >= total:
                truncated = False
                break
            time.sleep(self.delay)

        if truncated:
            logger.warning("SmartRecruiters[%s]: parei em %d páginas; o board pode ter mais vagas.",
                           company, SMARTR_MAX_PAGES)
        logger.info("SmartRecruiters[%s]: %d vagas.", company, len(jobs))
        return jobs[:max_jobs]

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        seen: set[str] = set()
        result: list[JobPosting] = []
        for company in self.companies:
            for job in self._fetch_company(company, max_jobs):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
        logger.info("SmartRecruiters: %d vagas em %d empresas.", len(result), len(self.companies))
        return result
