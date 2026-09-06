"""
ashby.py — Provider Ashby (API pública de job board, por empresa/org).

    GET https://api.ashbyhq.com/posting-api/job-board/<org>

Resposta: {"jobs": [{"id"/"jobId","title","location","department","team",
    "employmentType","isRemote","jobUrl","publishedDate"}]}
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..models import ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def parse_jobs(payload, org: str) -> list[JobPosting]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("jobs")
    if not isinstance(items, list):
        return []
    jobs: list[JobPosting] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("jobUrl") or it.get("applyUrl") or "").strip()
        if not title or not url:
            continue
        loc = str(it.get("location") or "").strip()
        jobs.append(JobPosting(
            provider="ashby",
            external_id=f"{org}:{it.get('id') or it.get('jobId')}",
            title=title,
            company=org,
            url=url,
            description=str(it.get("department") or it.get("team") or "").strip(),
            city=loc,
            workplace_type=REMOTE if it.get("isRemote") else (ONSITE if loc else WORKPLACE_UNKNOWN),
            published_date=str(it.get("publishedDate") or "").strip(),
        ))
    return jobs


class AshbyProvider(JobProvider):
    name = "ashby"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        seen: set[str] = set()
        result: list[JobPosting] = []
        for org in self.companies:
            payload = fetch_json(self._session, ASHBY_URL.format(org=org), delay=self.delay)
            if not payload:
                logger.warning("Ashby: sem dados para '%s'.", org)
                continue
            # `max_jobs` é teto POR org (mesma razão do Lever/Greenhouse): a org
            # com board gigante não pode zerar a cota das demais.
            jobs = parse_jobs(payload, org)[:max_jobs]
            for job in jobs:
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            logger.info("Ashby[%s]: %d vagas.", org, len(jobs))
            time.sleep(self.delay)
        logger.info("Ashby: %d vagas em %d orgs.", len(result), len(self.companies))
        return result
