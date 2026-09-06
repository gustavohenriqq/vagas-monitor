"""
remoteok.py — Provider RemoteOK (API pública de vagas remotas).

    GET https://remoteok.com/api   (exige User-Agent de navegador)

Resposta: array JSON. O PRIMEIRO elemento é um aviso legal ({"legal": ...});
os demais são vagas: {"id","slug","company","position","tags":[...],
"location","url","apply_url","date"}.

Todas remotas. Atribuição a RemoteOK é requerida pelos termos deles (mantemos o
link original na notificação, o que já cumpre isso).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models import REMOTE, JobPosting
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

REMOTEOK_URL = "https://remoteok.com/api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def parse_jobs(payload) -> list[JobPosting]:
    if not isinstance(payload, list):
        return []
    jobs: list[JobPosting] = []
    for it in payload:
        if not isinstance(it, dict) or "legal" in it:
            continue  # pula o aviso legal e entradas inválidas
        title = str(it.get("position") or it.get("title") or "").strip()
        url = str(it.get("url") or it.get("apply_url") or "").strip()
        if not title or not url:
            continue
        tags = it.get("tags")
        desc = ", ".join(str(t) for t in tags) if isinstance(tags, list) else ""
        jobs.append(JobPosting(
            provider="remoteok",
            external_id=str(it.get("id") or it.get("slug") or url),
            title=title,
            company=str(it.get("company") or "").strip(),
            url=url,
            description=desc[:2000],
            country=str(it.get("location") or "").strip(),
            workplace_type=REMOTE,
            published_date=str(it.get("date") or "").strip(),
        ))
    return jobs


class RemoteOkProvider(JobProvider):
    name = "remoteok"

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        payload = fetch_json(self._session, REMOTEOK_URL, headers=_HEADERS, delay=self.delay)
        jobs = parse_jobs(payload) if payload else []
        logger.info("RemoteOK: %d vagas remotas.", len(jobs))
        return jobs[:max_jobs]
