"""
recrutei.py — Provider Recrutei em modo GLOBAL (agregador empregos.recrutei.com.br).

O agregador é renderizado no servidor (SSR): um GET simples devolve o HTML com
todas as vagas de todas as empresas. Os links seguem o padrão:
    https://empregos.recrutei.com.br/vaga/<empresa>/<id>-<titulo-slug>

Filtramos por modelo direto na URL (?model=remote), então não precisamos parsear
o modelo por vaga: tudo que vem de model=remote é remoto. A paginação é ?page=N.

Vantagem sobre o modo por-empresa: cobre TODAS as empresas do Recrutei
automaticamente, sem precisar listar slug por slug.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from ..models import HYBRID, ONSITE, REMOTE, WORKPLACE_UNKNOWN, JobPosting
from .base import JobProvider

logger = logging.getLogger(__name__)

RECRUTEI_SEARCH_URL = "https://empregos.recrutei.com.br/busca"
REQUEST_TIMEOUT = 20
MAX_PAGES = 40  # trava de segurança

# Modelos de trabalho aceitos pela URL do agregador -> constante interna.
_MODEL_MAP = {"remote": REMOTE, "hibrido": HYBRID, "presencial": ONSITE}

# Link de vaga: /vaga/<empresa>/<id>-<titulo-slug>
_JOB_LINK_RE = re.compile(r"/vaga/([a-z0-9][a-z0-9-]*)/(\d+)-([a-z0-9][a-z0-9-]*)")

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}


def _deslug(slug: str) -> str:
    """thera-consulting -> 'Thera Consulting'. Perde acento, mas fica legível
    (o filtro de relevância normaliza acentos de qualquer forma)."""
    return re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()


def parse_search_html(html: str, model: str = "remote") -> list[JobPosting]:
    """Extrai as vagas de uma página do agregador via padrão de link."""
    workplace = _MODEL_MAP.get(model, WORKPLACE_UNKNOWN)
    seen: set[tuple[str, str]] = set()
    jobs: list[JobPosting] = []
    for company, job_id, title_slug in _JOB_LINK_RE.findall(html or ""):
        key = (company, job_id)
        if key in seen:
            continue
        seen.add(key)
        title = _deslug(title_slug)
        jobs.append(
            JobPosting(
                provider="recrutei",
                external_id=f"{company}:{job_id}",
                title=title,
                company=_deslug(company),
                url=f"https://empregos.recrutei.com.br/vaga/{company}/{job_id}-{title_slug}",
                description="",
                country="Brasil",
                workplace_type=workplace,
            )
        )
    return jobs


class RecruteiProvider(JobProvider):
    name = "recrutei"

    def __init__(self, models: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        # Por padrão só remoto (o caso de maior valor; híbrido não traz cidade).
        self.models = models or ["remote"]

    def _fetch_page(self, model: str, page: int) -> Optional[str]:
        try:
            resp = self._session.get(
                RECRUTEI_SEARCH_URL,
                params={"model": model, "page": page},
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning("Recrutei: HTTP %d em %s (page %d).", resp.status_code, model, page)
        except Exception as exc:
            logger.warning("Recrutei: erro em %s page %d: %s", model, page, exc)
        return None

    def _search_model(self, model: str, max_jobs: int) -> list[JobPosting]:
        seen: set[str] = set()
        result: list[JobPosting] = []
        for page in range(1, MAX_PAGES + 1):
            html = self._fetch_page(model, page)
            if not html:
                break
            batch = parse_search_html(html, model)
            novos = [j for j in batch if j.stable_id not in seen]
            if not novos:
                break  # página sem vagas novas = fim
            for j in novos:
                seen.add(j.stable_id)
                result.append(j)
            if len(result) >= max_jobs:
                break
            time.sleep(self.delay)
        logger.info("Recrutei[%s]: %d vagas.", model, len(result))
        return result[:max_jobs]

    def search(self, keywords: list[str], *, max_jobs: int = 200, models: Optional[list[str]] = None, **kwargs) -> list[JobPosting]:
        """Varre o agregador global por modelo(s). Keywords são filtradas depois
        pelo matcher (a busca por termo no servidor é opcional e não usada aqui,
        para não multiplicar requisições)."""
        active = models or self.models
        seen: set[str] = set()
        result: list[JobPosting] = []
        for model in active:
            for job in self._search_model(model, max_jobs):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
        logger.info("Recrutei: %d vagas únicas (modelos: %s).", len(result), ", ".join(active))
        return result
