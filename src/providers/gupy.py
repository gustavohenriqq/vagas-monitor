"""
gupy.py — Provider do Gupy (busca pública global por palavra-chave).

Endpoint público (sem login):
    GET https://employability-portal.gupy.io/api/v1/jobs
    ?jobName=<termo>&limit=<n>&offset=<n>

Resposta (resumo):
    {
      "data": [
        {"id", "name", "description", "careerPageName", "careerPageUrl",
         "jobUrl", "publishedDate", "applicationDeadline", "isRemoteWork",
         "city", "state", "country", "workplaceType"}
      ],
      "pagination": {"total", "limit", "offset"}
    }

O Gupy tem busca global de verdade: `jobName` filtra por nome da vaga no
catálogo inteiro, de todas as empresas.
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
    WORKPLACE_UNKNOWN,
    JobPosting,
)
from .base import JobProvider, fetch_json

logger = logging.getLogger(__name__)

GUPY_JOBS_URL = "https://employability-portal.gupy.io/api/v1/jobs"
PAGE_SIZE = 100


def _map_workplace(item: dict) -> str:
    """Converte workplaceType/isRemoteWork do Gupy para as constantes internas."""
    raw = str(item.get("workplaceType") or "").strip().lower().replace("-", "").replace("_", "")
    if raw in ("remote", "remoto"):
        return REMOTE
    if raw in ("hybrid", "hibrido"):
        return HYBRID
    if raw in ("onsite", "presencial"):
        return ONSITE
    if item.get("isRemoteWork") is True:
        return REMOTE
    return WORKPLACE_UNKNOWN


def _clean_html(text: str) -> str:
    """Remove tags HTML e normaliza espaços da descrição."""
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_jobs(payload: dict) -> list[JobPosting]:
    """Converte o JSON do Gupy em JobPosting. Defensivo a campos ausentes."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []

    jobs: list[JobPosting] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        url = str(item.get("jobUrl") or item.get("careerPageUrl") or "").strip()
        if not name or not url:
            continue

        jobs.append(
            JobPosting(
                provider="gupy",
                external_id=job_id,
                title=name,
                company=str(item.get("careerPageName") or "").strip(),
                url=url,
                description=_clean_html(item.get("description", ""))[:5000],
                city=str(item.get("city") or "").strip(),
                state=str(item.get("state") or "").strip(),
                country=str(item.get("country") or "").strip(),
                workplace_type=_map_workplace(item),
                published_date=str(item.get("publishedDate") or "").strip(),
                deadline=str(item.get("applicationDeadline") or "").strip(),
            )
        )
    return jobs


class GupyProvider(JobProvider):
    name = "gupy"

    def _search_term(self, term: str, max_jobs: int) -> list[JobPosting]:
        """Busca paginada por um único termo."""
        collected: list[JobPosting] = []
        offset = 0
        while len(collected) < max_jobs:
            payload = fetch_json(
                self._session,
                GUPY_JOBS_URL,
                params={"jobName": term, "limit": PAGE_SIZE, "offset": offset},
                delay=self.delay,
            )
            if not payload:
                break
            batch = parse_jobs(payload)
            if not batch:
                break
            collected.extend(batch)

            pagination = payload.get("pagination") or {}
            total = int(pagination.get("total") or 0)
            offset += PAGE_SIZE
            if offset >= total or len(batch) < PAGE_SIZE:
                break
            time.sleep(self.delay)
        return collected

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        """
        Busca no Gupy por cada palavra-chave e devolve a união deduplicada.

        Sem palavra-chave, uma busca vazia devolve o catálogo geral (limitado
        por max_jobs), útil para varredura ampla.
        """
        terms = [k for k in (keywords or []) if k.strip()] or [""]
        seen: set[str] = set()
        result: list[JobPosting] = []

        per_term = max(max_jobs // len(terms), PAGE_SIZE)
        for term in terms:
            logger.info("Gupy: buscando '%s'...", term or "(catálogo geral)")
            for job in self._search_term(term, per_term):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            if len(result) >= max_jobs:
                break

        logger.info("Gupy: %d vagas únicas coletadas.", len(result))
        return result[:max_jobs]
