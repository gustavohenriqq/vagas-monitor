"""
lever.py — Provider Lever (API pública de postings, por empresa).

    GET https://api.lever.co/v0/postings/<company>?mode=json

Resposta: array de postings: [{"id","text"(título),"hostedUrl",
    "categories":{"location","team","commitment"},"workplaceType"}]
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import HYBRID, ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting, normalize
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

LEVER_URL = "https://api.lever.co/v0/postings/{company}"


def _workplace(value: str, location: str) -> str:
    v = normalize(value)
    if "remote" in v:
        return REMOTE
    if "hybrid" in v:
        return HYBRID
    if "onsite" in v or "on-site" in v:
        return ONSITE
    return REMOTE if "remote" in normalize(location) else (ONSITE if location else WORKPLACE_UNKNOWN)


def parse_jobs(payload, company: str) -> list[JobPosting]:
    if not isinstance(payload, list):
        return []
    jobs: list[JobPosting] = []
    for it in payload:
        if not isinstance(it, dict):
            continue
        title = str(it.get("text") or "").strip()
        url = str(it.get("hostedUrl") or it.get("applyUrl") or "").strip()
        if not title or not url:
            continue
        cats = it.get("categories") or {}
        location = str(cats.get("location") or "").strip() if isinstance(cats, dict) else ""
        jobs.append(JobPosting(
            provider="lever",
            external_id=f"{company}:{it.get('id')}",
            title=title,
            company=company,
            url=url,
            description=str((cats or {}).get("team") or "").strip(),
            city=location,
            country=str(it.get("country") or "").strip(),
            workplace_type=_workplace(str(it.get("workplaceType") or ""), location),
            published_date=str(it.get("createdAt") or "").strip(),
        ))
    return jobs


class LeverProvider(JobProvider):
    name = "lever"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        import time
        seen: set[str] = set()
        result: list[JobPosting] = []
        for company in self.companies:
            payload = fetch_json(self._session, LEVER_URL.format(company=company),
                                 params={"mode": "json"}, delay=self.delay)
            if not payload:
                logger.warning("Lever: sem dados para '%s'.", company)
                continue
            # `max_jobs` é teto POR empresa: cortar só no fim faria um board grande
            # consumir a cota inteira e as empresas seguintes nunca apareceriam.
            jobs = parse_jobs(payload, company)[:max_jobs]
            for job in jobs:
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            logger.info("Lever[%s]: %d vagas.", company, len(jobs))
            time.sleep(self.delay)
        logger.info("Lever: %d vagas em %d empresas.", len(result), len(self.companies))
        return result
