"""
workday.py — Provider Workday (API pública CXS, por empresa).

    POST https://<host>/wday/cxs/<tenant>/<site>/jobs
    corpo: {"appliedFacets":{},"limit":20,"offset":0,"searchText":"<termo>"}

É o mesmo endpoint que a página de carreiras pública deles consome — sem
login e sem burlar proteção.

Quatro diferenças em relação aos outros providers, todas impostas pela API:

1. Exige POST com corpo JSON (daí o post_json no base.py).
2. O `limit` trava em 20 — pedir 50 devolve zero. Varrer um tenant inteiro
   custaria dezenas de requisições, então buscamos por TERMO em vez de
   paginar tudo: poucas chamadas e alta precisão.
3. A listagem devolve "6 Locations" no lugar do local quando a vaga tem
   vários, e a data só em texto relativo ("Posted 3 Days Ago"). O endpoint de
   detalhe traz local completo, país e `startDate` de verdade — por isso as
   vagas que passam no filtro de título são enriquecidas com uma chamada
   extra. Só as que passam, senão seriam centenas de requisições.
4. O modelo de trabalho NÃO existe em lugar nenhum: nem na listagem, nem no
   detalhe, nem no texto da descrição (verificado). Toda vaga sai como
   `unknown`, e por isso ela só casa com busca sem filtro de modelo.

Formato de cada entrada em `workday_companies`:

    host|tenant|site|Nome de exibição      (o nome é opcional)
    hp.wd5.myworkdayjobs.com|hp|ExternalCareerSite|HP
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Optional

from ..models import REMOTE, WORKPLACE_UNKNOWN, JobPosting, normalize
from .base import JobProvider, fetch_json, post_json

logger = logging.getLogger(__name__)

WORKDAY_BASE = "https://{host}/wday/cxs/{tenant}/{site}"

# Teto da API: pedir mais devolve lista vazia.
PAGE_LIMIT = 20
# Páginas por termo. Com 20 por página, cobre 100 vagas do termo mais fértil.
MAX_PAGES = 5
# Teto de chamadas de detalhe por empresa, para o custo não explodir.
MAX_DETALHES = 60

# Termos de busca. O searchText do Workday casa também com o LOCAL, e é por
# isso que buscamos pelo país e não por cargo: buscar "engineer" devolve o
# mundo inteiro e as vagas brasileiras ficam além do teto de páginas —
# testado, dava 282 vagas e zero no Brasil. Buscando "Brazil" vem o recorte
# certo, e o filtro de 3 níveis decide o resto localmente.
TERMOS_PADRAO = ("Brazil", "Brasil")

# "6 Locations" no lugar do local: a vaga tem vários e a listagem não diz quais.
_VARIOS_LOCAIS = re.compile(r"^\d+\s+locations?$", re.I)
# "Posted 3 Days Ago", "Posted Today", "Posted 30+ Days Ago"
_DIAS = re.compile(r"(\d+)\s*\+?\s*days?", re.I)


def _local(texto: str) -> str:
    """Devolve o local, ou vazio quando a API só diz quantos locais existem."""
    t = (texto or "").strip()
    return "" if not t or _VARIOS_LOCAIS.match(t) else t


def _publicado_em(texto: str) -> str:
    """Converte 'Posted 3 Days Ago' em data ISO.

    É aproximação: a listagem não devolve a data real, só há quantos dias. O
    detalhe traz `startDate` exato e sobrescreve isto quando disponível.
    """
    t = (texto or "").strip()
    if not t:
        return ""
    baixo = t.lower()
    if "today" in baixo or "hoje" in baixo:
        return date.today().isoformat()
    m = _DIAS.search(t)
    if m:
        return (date.today() - timedelta(days=int(m.group(1)))).isoformat()
    return ""


def _modelo(local: str) -> str:
    """O Workday não expõe modelo de trabalho; só dá para ler do local."""
    n = normalize(local)
    return REMOTE if ("remote" in n or "remoto" in n) else WORKPLACE_UNKNOWN


def parse_jobs(payload, host: str, site: str, empresa: str) -> list[JobPosting]:
    if not isinstance(payload, dict):
        return []
    itens = payload.get("jobPostings")
    if not isinstance(itens, list):
        return []

    jobs: list[JobPosting] = []
    for it in itens:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        caminho = str(it.get("externalPath") or "").strip()
        if not title or not caminho:
            continue

        # bulletFields costuma trazer o código da vaga (JR123456), que é o id
        # mais estável; o caminho serve de reserva.
        bullets = it.get("bulletFields")
        externo = ""
        if isinstance(bullets, list) and bullets:
            externo = str(bullets[0] or "").strip()
        if not externo:
            externo = caminho.rsplit("/", 1)[-1]

        local = _local(str(it.get("locationsText") or ""))
        job = JobPosting(
            provider="workday",
            external_id=f"{empresa}:{externo}",
            title=title,
            company=empresa,
            url=f"https://{host}/{site}{caminho}",
            description="",
            city=local,
            workplace_type=_modelo(local),
            published_date=_publicado_em(str(it.get("postedOn") or "")),
        )
        # Guardado para a etapa de detalhe; não faz parte do JobPosting.
        job._caminho = caminho          # type: ignore[attr-defined]
        jobs.append(job)
    return jobs


def aplica_detalhe(job: JobPosting, info: dict) -> JobPosting:
    """Sobrescreve local, país e data com os valores exatos do detalhe."""
    if not isinstance(info, dict):
        return job
    local = str(info.get("location") or "").strip()
    if local:
        job.city = local
        job.workplace_type = _modelo(local)
    pais = info.get("country")
    if isinstance(pais, dict) and pais.get("descriptor"):
        job.country = str(pais["descriptor"]).strip()
    inicio = str(info.get("startDate") or "").strip()
    if inicio:
        job.published_date = inicio
    return job


def _partes(entrada: str) -> Optional[tuple[str, str, str, str]]:
    """Quebra 'host|tenant|site|Nome' e valida. Devolve None se malformado."""
    campos = [p.strip() for p in str(entrada).split("|")]
    if len(campos) < 3 or not all(campos[:3]):
        logger.warning("Workday: entrada malformada (esperado host|tenant|site): %r", entrada)
        return None
    host, tenant, site = campos[:3]
    nome = campos[3] if len(campos) > 3 and campos[3] else tenant
    return host, tenant, site, nome


class WorkdayProvider(JobProvider):
    name = "workday"

    def __init__(self, companies: Optional[list[str]] = None, session=None, delay: float = 1.0):
        super().__init__(session=session, delay=delay)
        self.companies = [c.strip() for c in (companies or []) if c.strip()]

    def _busca_termo(self, base: str, host: str, site: str, nome: str,
                     termo: str, max_jobs: int) -> list[JobPosting]:
        """Pagina um termo até esgotar o total ou bater o teto."""
        achadas: list[JobPosting] = []
        offset = 0
        for _ in range(MAX_PAGES):
            payload = post_json(self._session, base + "/jobs", {
                "appliedFacets": {}, "limit": PAGE_LIMIT, "offset": offset, "searchText": termo,
            }, delay=self.delay)
            if not payload:
                break
            achadas.extend(parse_jobs(payload, host, site, nome))

            crus = payload.get("jobPostings")
            tamanho = len(crus) if isinstance(crus, list) else 0
            total = payload.get("total")
            offset += PAGE_LIMIT
            if tamanho < PAGE_LIMIT or len(achadas) >= max_jobs:
                break
            if isinstance(total, int) and offset >= total:
                break
            time.sleep(self.delay)
        return achadas

    def _enriquece(self, base: str, jobs: list[JobPosting]) -> None:
        """Busca o detalhe só das vagas que já passaram no filtro de título.

        Import tardio de relevance para não criar ciclo, mesmo padrão do
        matcher. Sem esse recorte seriam centenas de chamadas por empresa.
        """
        from ..relevance import classify_title

        gastos = 0
        for job in jobs:
            if gastos >= MAX_DETALHES:
                logger.info("Workday[%s]: teto de %d detalhes atingido.", job.company, MAX_DETALHES)
                break
            if not classify_title(job.title).passes:
                continue
            caminho = getattr(job, "_caminho", "")
            if not caminho:
                continue
            detalhe = fetch_json(self._session, base + caminho, delay=self.delay)
            gastos += 1
            if detalhe:
                aplica_detalhe(job, detalhe.get("jobPostingInfo") or {})
            time.sleep(self.delay)

    def search(self, keywords: list[str], *, max_jobs: int = 200,
               termos: Optional[tuple] = None, **kwargs) -> list[JobPosting]:
        if not self.companies:
            logger.info("Workday: nenhuma empresa configurada. Pulando.")
            return []

        alvos = termos or TERMOS_PADRAO
        seen: set[str] = set()
        result: list[JobPosting] = []

        for entrada in self.companies:
            partes = _partes(entrada)
            if not partes:
                continue
            host, tenant, site, nome = partes
            base = WORKDAY_BASE.format(host=host, tenant=tenant, site=site)

            da_empresa: list[JobPosting] = []
            for termo in alvos:
                for job in self._busca_termo(base, host, site, nome, termo, max_jobs):
                    if job.stable_id not in seen:
                        seen.add(job.stable_id)
                        da_empresa.append(job)
                if len(da_empresa) >= max_jobs:
                    break
                time.sleep(self.delay)

            self._enriquece(base, da_empresa)
            result.extend(da_empresa[:max_jobs])
            logger.info("Workday[%s]: %d vagas.", nome, len(da_empresa))

        logger.info("Workday: %d vagas em %d empresas.", len(result), len(self.companies))
        return result
