"""
recruitee.py — Provider Recruitee (API pública de offers, por empresa).

    GET https://<company>.recruitee.com/api/offers/

Resposta: {"offers": [{"id","title","company_name","careers_url"/"careers_apply_url",
    "location","city","country_code","remote"(bool),"department"}]}
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..models import ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

RECRUITEE_URL = "https://{company}.recruitee.com/api/offers/"


def parse_jobs(payload, company: str) -> list[JobPosting]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("offers")
    if not isinstance(items, list):
        return []
    jobs: list[JobPosting] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("careers_url") or it.get("careers_apply_url") or "").strip()
        if not title or not url:
            continue
        is_remote = bool(it.get("remote"))
        city = str(it.get("city") or "").strip()
        jobs.append(JobPosting(
            provider="recruitee",
            external_id=f"{company}:{it.get('id')}",
            title=title,
            company=str(it.get("company_name") or company).strip(),
            url=url,
            description=str(it.get("department") or "").strip(),
            city=city,
            country=str(it.get("country_code") or "").strip(),
            workplace_type=REMOTE if is_remote else (ONSITE if city else WORKPLACE_UNKNOWN),
            published_date=str(it.get("published_at") or "").strip(),
        ))
    return jobs


class RecruteeProvider(JobProvider):
    name = "recruitee"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        seen: set[str] = set()
        result: list[JobPosting] = []
        for company in self.companies:
            payload = fetch_json(self._session, RECRUITEE_URL.format(company=company), delay=self.delay)
            if not payload:
                logger.warning("Recruitee: sem dados para '%s'.", company)
                continue
            for job in parse_jobs(payload, company):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
        logger.info("Recruitee: %d vagas em %d empresas.", len(result), len(self.companies))
        return result[:max_jobs]
