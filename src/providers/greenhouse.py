"""
greenhouse.py — Provider Greenhouse (Job Board API oficial e pública).

Endpoint oficial (sem login, documentado):
    GET https://boards-api.greenhouse.io/v1/boards/<board_token>/jobs?content=true

`board_token` é o identificador do quadro da empresa — o trecho da URL pública:
    https://job-boards.greenhouse.io/<board_token>

Como o inhire, é por empresa: você lista os tokens em greenhouse_companies e o
provider consulta cada um. Resposta:
    {"jobs": [{"id", "title", "updated_at", "absolute_url",
               "location": {"name"}, "content": "<html escapado>",
               "departments": [{"name"}], "offices": [{"name","location"}]}],
     "meta": {"total"}}
"""

from __future__ import annotations

import html as html_module
import logging
import re
import time
from typing import Optional

from ..models import ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting, normalize
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _clean_html(text: str) -> str:
    text = html_module.unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _workplace_from_location(loc_name: str) -> str:
    n = normalize(loc_name)
    if not n:
        return WORKPLACE_UNKNOWN
    if "remote" in n or "remoto" in n or "anywhere" in n:
        return REMOTE
    return ONSITE


def _parse_location(loc_name: str) -> tuple[str, str, str]:
    parts = [p.strip() for p in str(loc_name or "").split(",") if p.strip()]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], parts[1], parts[-1]


def parse_jobs(payload, token: str, company_name: str = "") -> list[JobPosting]:
    """Converte a resposta do Greenhouse em JobPosting para um board."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("jobs")
    if not isinstance(items, list):
        return []

    company = company_name or token
    jobs: list[JobPosting] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("absolute_url") or "").strip()
        if not title or not url:
            continue

        loc = item.get("location") or {}
        loc_name = str(loc.get("name") if isinstance(loc, dict) else loc or "").strip()
        city, state, country = _parse_location(loc_name)

        jobs.append(
            JobPosting(
                provider="greenhouse",
                external_id=f"{token}:{item.get('id')}",
                title=title,
                company=company,
                url=url,
                description=_clean_html(item.get("content", ""))[:5000],
                city=city,
                state=state,
                country=country or loc_name,
                workplace_type=_workplace_from_location(loc_name),
                published_date=str(item.get("updated_at") or "").strip(),
            )
        )
    return jobs


class GreenhouseProvider(JobProvider):
    name = "greenhouse"

    def __init__(self, tokens: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.tokens = [t.strip() for t in (tokens or []) if t.strip()]

    def _fetch_board(self, token: str, max_jobs: int) -> list[JobPosting]:
        payload = fetch_json(
            self._session,
            GREENHOUSE_URL.format(token=token),
            params={"content": "true"},
            delay=self.delay,
        )
        if not payload:
            logger.warning("Greenhouse: sem dados para o board '%s'.", token)
            return []
        jobs = parse_jobs(payload, token)
        logger.info("Greenhouse[%s]: %d vagas.", token, len(jobs))
        return jobs[:max_jobs]

    def search(self, keywords: list[str], *, max_jobs: int = 200, tokens: Optional[list[str]] = None, **kwargs) -> list[JobPosting]:
        """Coleta as vagas dos boards (empresas) configurados. Keywords são
        filtradas depois pelo matcher (a API não busca por termo)."""
        active = [t.strip() for t in (tokens or self.tokens) if t.strip()]
        if not active:
            logger.info("Greenhouse: nenhum board configurado. Pulando.")
            return []
        seen: set[str] = set()
        result: list[JobPosting] = []
        for token in active:
            for job in self._fetch_board(token, max_jobs):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
        logger.info("Greenhouse: %d vagas únicas em %d boards.", len(result), len(active))
        return result
