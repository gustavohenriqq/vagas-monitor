"""
base.py — Interface comum dos providers e utilitários HTTP compartilhados.

Um provider recebe uma lista de palavras-chave e devolve JobPosting normalizados.
O provider NÃO aplica os filtros finos (senioridade, local, exclusões) — isso é
responsabilidade do matcher. Ele só busca o máximo de candidatos relevantes.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from ..models import JobPosting

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
BACKOFF_BASE = 2

USER_AGENT = (
    "Mozilla/5.0 (compatible; VagasMonitor/1.0; +https://github.com/seu-usuario/vagas-monitor)"
)


def build_session() -> requests.Session:
    """Cria uma Session HTTP reutilizável com headers padrão."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return session


def fetch_json(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    delay: float = 1.0,
) -> Optional[dict]:
    """
    GET com retry/backoff que devolve JSON decodificado ou None.

    Trata 403/404/429/5xx e erros de conexão sem propagar exceção.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    logger.warning("Resposta 200 sem JSON válido em %s.", url)
                    return None

            if resp.status_code in (401, 403):
                logger.warning("Acesso negado (%d) em %s. Não repetiremos.", resp.status_code, url)
                return None
            if resp.status_code == 404:
                logger.warning("Não encontrado (404): %s", url)
                return None
            if resp.status_code == 429:
                wait = delay * (BACKOFF_BASE ** attempt)
                logger.warning("Rate limit (429) em %s. Aguardando %.1fs.", url, wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = delay * (BACKOFF_BASE ** attempt)
                logger.warning("Erro do servidor (%d) em %s. Tentativa %d/%d.", resp.status_code, url, attempt, MAX_RETRIES)
                time.sleep(wait)
                continue

            logger.warning("Status inesperado %d em %s.", resp.status_code, url)
            return None

        except requests.exceptions.Timeout:
            wait = delay * (BACKOFF_BASE ** attempt)
            logger.warning("Timeout em %s (tentativa %d/%d). Aguardando %.1fs.", url, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
        except requests.exceptions.ConnectionError as exc:
            wait = delay * (BACKOFF_BASE ** attempt)
            logger.warning("Erro de conexão em %s: %s. Aguardando %.1fs.", url, exc, wait)
            time.sleep(wait)
        except requests.exceptions.RequestException as exc:
            logger.error("Erro irrecuperável em %s: %s", url, exc)
            return None

    logger.error("Todas as tentativas falharam para %s.", url)
    return None


class JobProvider:
    """Interface base. Subclasses implementam search()."""

    name: str = "base"

    def __init__(self, session: Optional[requests.Session] = None, delay: float = 1.0):
        self._session = session or build_session()
        self.delay = delay

    def search(self, keywords: list[str], *, max_jobs: int = 200, **kwargs) -> list[JobPosting]:
        """Busca vagas relacionadas às palavras-chave. Deve ser sobrescrito."""
        raise NotImplementedError

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
