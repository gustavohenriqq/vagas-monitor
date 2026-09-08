"""
monitor.py — Orquestrador: busca, filtra, persiste e notifica.

Fluxo:
1. Carrega config (.env) e buscas (searches.yaml)
2. Para cada busca habilitada: consulta os providers, normaliza e filtra (matcher)
3. Deduplica contra o histórico (data/jobs.json)
4. Notifica vagas novas via Telegram (respeitando INITIAL_NOTIFY na 1ª execução)
5. Salva o histórico e envia resumo (opcional)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Config, load_config
from .matcher import matches
from .models import JobPosting
from .providers import (
    GupyProvider, InhireProvider, WwrProvider, GreenhouseProvider, RecruteiProvider,
    RemotiveProvider, RemoteOkProvider, LeverProvider, AshbyProvider,
    RecruteeProvider, SmartRecruitersProvider, WorkdayProvider, build_session,
)
from .relevance import evaluate
from .searches import SearchProfile, SearchesFile, load_searches
from .storage import JobRecord, load_history, mark_sent, save_history
from .telegram_notifier import Summary, build_notifier

TZ = ZoneInfo("America/Sao_Paulo")
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=TZ).isoformat()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def build_provider_map(searches: SearchesFile, session, delay: float) -> dict:
    """Instancia todos os providers, cada um já com sua lista de empresas (quando aplicável)."""
    def c(name):
        return searches.companies(name)
    return {
        "gupy": GupyProvider(session=session, delay=delay),
        "inhire": InhireProvider(tenants=c("inhire"), session=session, delay=delay),
        "greenhouse": GreenhouseProvider(tokens=c("greenhouse"), session=session, delay=delay),
        "recrutei": RecruteiProvider(session=session, delay=delay),
        "wwr": WwrProvider(session=session, delay=delay),
        "remotive": RemotiveProvider(session=session, delay=delay),
        "remoteok": RemoteOkProvider(session=session, delay=delay),
        "lever": LeverProvider(companies=c("lever"), session=session, delay=delay),
        "ashby": AshbyProvider(companies=c("ashby"), session=session, delay=delay),
        "recruitee": RecruteeProvider(companies=c("recruitee"), session=session, delay=delay),
        "smartrecruiters": SmartRecruitersProvider(companies=c("smartrecruiters"), session=session, delay=delay),
        "workday": WorkdayProvider(companies=c("workday"), session=session, delay=delay),
    }


def collect_for_search(profile: SearchProfile, provider_map: dict, max_jobs: int) -> list[JobPosting]:
    """Consulta os providers do perfil e devolve as vagas que casam com o filtro."""
    raw: list[JobPosting] = []
    for name in profile.providers:
        prov = provider_map.get(name)
        if not prov:
            continue
        try:
            raw.extend(prov.search(profile.keywords, max_jobs=max_jobs))
        except Exception as exc:
            logger.warning("Falha no provider %s para '%s': %s", name, profile.name, exc)

    matched = [job for job in raw if matches(job, profile).matched]
    logger.info("Busca '%s': %d coletadas, %d após filtro.", profile.name, len(raw), len(matched))
    return matched


def decide_destino(*, is_first_run: bool, config: Config, score: int) -> str:
    """Decide o que fazer com uma vaga NOVA: notificar, guardar pro digest ou calar.

    Separado do run() para poder ser testado sem rede nem Telegram.

    - "silencioso": execução com SILENT_RUN, que grava no histórico sem avisar
      ninguém. Serve para absorver uma fonte nova sem despejar centenas de
      mensagens de uma vez.
    - "skipped" também na primeira execução, quando o histórico está vazio e
      INITIAL_NOTIFY não foi pedido.
    """
    if config.silent_run:
        return "skipped"
    if is_first_run and not config.initial_notify:
        return "skipped"
    return "sent" if score >= config.high_score_threshold else "digest"


def run(config: Optional[Config] = None, searches: Optional[SearchesFile] = None) -> dict:
    """Executa o ciclo completo do monitor. Retorna um dicionário-resumo."""
    config = config or load_config()
    searches = searches or load_searches(Path(config.searches_path))

    storage_path = Path(config.storage_path)
    history = load_history(storage_path)
    is_first_run = len(history) == 0
    logger.info("=== Vagas Monitor iniciando (primeira execução: %s) ===", is_first_run)
    if config.silent_run:
        logger.info("Modo silencioso: coleta e grava o histórico, sem enviar nada ao Telegram.")

    session = build_session()
    provider_map = build_provider_map(searches, session, config.request_delay_seconds)
    notifier = build_notifier(config.telegram_bot_token, config.telegram_chat_id)

    new_count = 0
    immediate_count = 0
    digest_added = 0
    per_search: dict[str, int] = {}
    per_provider: dict[str, int] = {}

    try:
        enabled = [s for s in searches.searches if s.enabled]
        logger.info("%d busca(s) habilitada(s).", len(enabled))

        for profile in enabled:
            jobs = collect_for_search(profile, provider_map, config.max_jobs_per_search)
            for job in jobs:
                sid = job.stable_id
                existing = history.get(sid)
                now = _now_iso()

                if existing is None:
                    rel = evaluate(job)
                    record = JobRecord(
                        stable_id=sid, job=job, first_seen_at=now, last_seen_at=now,
                        notification_status="pending", matched_searches=[profile.name],
                        score=rel.score, confidence=rel.level, profile=profile.profile,
                    )
                    history[sid] = record
                    new_count += 1
                    per_search[profile.name] = per_search.get(profile.name, 0) + 1
                    per_provider[job.provider] = per_provider.get(job.provider, 0) + 1

                    destino = decide_destino(is_first_run=is_first_run, config=config,
                                             score=rel.score)
                    if destino == "sent":
                        notifier.notify_job(job, profile.name, rel.score, rel.reasons)
                        mark_sent(history, sid)
                        immediate_count += 1
                    elif destino == "digest":
                        record.notification_status = "digest"   # acumula pro digest
                        digest_added += 1
                    else:
                        record.notification_status = "skipped"
                else:
                    existing.last_seen_at = now
                    if profile.name not in existing.matched_searches:
                        existing.matched_searches.append(profile.name)

        # Digest ranqueado: junta o que ficou pendente (deste run e dos anteriores).
        # Em execução silenciosa ele também não sai — senão o "sem notificar"
        # viraria uma mensagem gigante no fim.
        if config.send_digest and not config.silent_run:
            pending = [r for r in history.values() if r.notification_status == "digest"]
            pending.sort(key=lambda r: (r.score, r.first_seen_at), reverse=True)
            items = [{
                "score": r.score, "title": r.job.title, "company": r.job.company,
                "location": r.job.location_label, "provider": r.job.provider, "url": r.job.url,
            } for r in pending]
            if items or config.send_empty_summary:
                notifier.send_digest(items)
            for r in pending:
                r.notification_status = "sent"
            logger.info("Digest enviado: %d vagas.", len(items))

        save_history(history, storage_path)

        summary = Summary(new_count=new_count, per_search=per_search, per_provider=per_provider)
        if config.send_summary:
            notifier.send_summary(summary, send_empty=config.send_empty_summary)
        logger.info("Imediatas: %d | Adicionadas ao digest: %d", immediate_count, digest_added)

        logger.info("=== Encerrado. Novas: %d | Total no histórico: %d ===", new_count, len(history))
        return {"new": new_count, "immediate": immediate_count, "digest_added": digest_added,
                "total": len(history), "per_search": per_search, "per_provider": per_provider}
    except Exception as exc:
        logger.critical("Erro crítico no monitor: %s", exc, exc_info=True)
        try:
            save_history(history, storage_path)
        except Exception:
            pass
        raise
    finally:
        for prov in provider_map.values():
            try:
                prov.close()
            except Exception:
                pass
        notifier.close()
