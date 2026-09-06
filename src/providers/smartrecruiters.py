"""
smartrecruiters.py — Provider SmartRecruiters (API pública de postings, por empresa).

    GET https://api.smartrecruiters.com/v1/companies/<company>/postings?limit=100

Resposta: {"content": [{"id","name"(título),"ref",
    "location":{"city","region","country","remote"},"customField",...}]}

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

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        seen: set[str] = set()
        result: list[JobPosting] = []
        for company in self.companies:
            payload = fetch_json(self._session, SMARTR_URL.format(company=company),
                                 params={"limit": 100}, delay=self.delay)
            if not payload:
                logger.warning("SmartRecruiters: sem dados para '%s'.", company)
                continue
            for job in parse_jobs(payload, company):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
        logger.info("SmartRecruiters: %d vagas em %d empresas.", len(result), len(self.companies))
        return result[:max_jobs]
