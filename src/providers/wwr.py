"""
wwr.py — Provider We Work Remotely (feeds RSS públicos).

WWR publica feeds RSS por categoria (feitos para consumo, sem risco de ToS):
    https://weworkremotely.com/categories/<categoria>.rss

Cada <item> traz:
    <title>Empresa: Cargo</title>
    <region>Anywhere in the World | Latin America | USA Only | ...</region>
    <category>Full-Stack Programming | ...</category>
    <link>...</link>  <description>HTML</description>  <pubDate>...</pubDate>

Todas as vagas do WWR são remotas. A `region` vira o "país"/mercado da vaga —
útil para o perfil internacional (Anywhere / Latin America aceitam Brasil).
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

from ..models import REMOTE, JobPosting
from .base import JobProvider

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

REQUEST_TIMEOUT = 20


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _slug_id(link: str) -> str:
    """Extrai um id estável do link (/remote-jobs/<slug>)."""
    slug = re.sub(r"[#?].*$", "", str(link or "")).rstrip("/").split("/")[-1]
    return slug[:100] if slug else ""


def parse_feed(xml_text: str) -> list[JobPosting]:
    """Parseia um feed RSS do WWR em JobPosting. Defensivo a itens malformados."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("WWR: RSS inválido: %s", exc)
        return []

    jobs: list[JobPosting] = []
    for item in root.iter("item"):
        def _txt(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        raw_title = _txt("title")
        link = _txt("link")
        if not raw_title or not link:
            continue

        # "Empresa: Cargo" — separa no primeiro ':'
        if ":" in raw_title:
            company, title = raw_title.split(":", 1)
            company, title = company.strip(), title.strip()
        else:
            company, title = "", raw_title.strip()

        region = _txt("region") or "Remoto"
        jobs.append(
            JobPosting(
                provider="wwr",
                external_id=_slug_id(link) or raw_title[:60],
                title=title,
                company=company,
                url=link,
                description=_clean_html(_txt("description"))[:5000],
                city="",
                state="",
                country=region,
                workplace_type=REMOTE,           # WWR é 100% remoto
                published_date=_txt("pubDate"),
            )
        )
    return jobs


class WwrProvider(JobProvider):
    name = "wwr"

    def __init__(self, feeds: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.feeds = feeds or DEFAULT_FEEDS

    def _fetch_text(self, url: str) -> Optional[str]:
        for attempt in range(1, 3):
            try:
                resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
                logger.warning("WWR: HTTP %d em %s", resp.status_code, url)
                return None
            except Exception as exc:
                logger.warning("WWR: erro em %s (tentativa %d): %s", url, attempt, exc)
                time.sleep(self.delay)
        return None

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        """Coleta os feeds configurados e devolve as vagas deduplicadas."""
        seen: set[str] = set()
        result: list[JobPosting] = []
        for feed in self.feeds:
            xml_text = self._fetch_text(feed)
            if not xml_text:
                continue
            for job in parse_feed(xml_text):
                if job.stable_id not in seen:
                    seen.add(job.stable_id)
                    result.append(job)
            time.sleep(self.delay)
            if len(result) >= max_jobs:
                break
        logger.info("WWR: %d vagas remotas coletadas de %d feeds.", len(result), len(self.feeds))
        return result[:max_jobs]
