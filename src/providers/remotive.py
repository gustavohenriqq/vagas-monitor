"""
remotive.py — Provider Remotive (API pública de vagas remotas).

    GET https://remotive.com/api/remote-jobs?limit=<n>[&search=<termo>]

Resposta: {"jobs": [{"id","url","title","company_name",
    "candidate_required_location","publication_date","job_type","category"}]}

Todas as vagas são remotas. Cobre o mundo todo (bom pro perfil internacional/PT-ES;
muitas aceitam LatAm/worldwide).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import REMOTE, JobPosting
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def parse_jobs(payload) -> list[JobPosting]:
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
        url = str(it.get("url") or "").strip()
        if not title or not url:
            continue
        jobs.append(JobPosting(
            provider="remotive",
            external_id=str(it.get("id") or url),
            title=title,
            company=str(it.get("company_name") or "").strip(),
            url=url,
            description=_clean_html(it.get("description", ""))[:2000],
            country=str(it.get("candidate_required_location") or "").strip(),
            workplace_type=REMOTE,
            published_date=str(it.get("publication_date") or "").strip(),
        ))
    return jobs


class RemotiveProvider(JobProvider):
    name = "remotive"

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        payload = fetch_json(self._session, REMOTIVE_URL, params={"limit": max_jobs}, delay=self.delay)
        jobs = parse_jobs(payload) if payload else []
        logger.info("Remotive: %d vagas remotas.", len(jobs))
        return jobs[:max_jobs]
