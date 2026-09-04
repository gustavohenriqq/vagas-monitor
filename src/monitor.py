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
from .providers import GupyProvider, InhireProvider, WwrProvider, GreenhouseProvider, build_session
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


def collect_for_search(
    profile: SearchProfile,
    *,
    gupy: GupyProvider,
    inhire: InhireProvider,
    wwr: WwrProvider,
    greenhouse: GreenhouseProvider,
    max_jobs: int,
    inhire_companies: list[str],
    greenhouse_companies: list[str] | None = None,
) -> list[JobPosting]:
    """Consulta os providers do perfil e devolve as vagas que casam com o filtro."""
    raw: list[JobPosting] = []
    if "gupy" in profile.providers:
        try:
            raw.extend(gupy.search(profile.keywords, max_jobs=max_jobs))
        except Exception as exc:
            logger.warning("Falha no provider Gupy para '%s': %s", profile.name, exc)
    if "inhire" in profile.providers:
        try:
            raw.extend(inhire.search(profile.keywords, max_jobs=max_jobs, tenants=inhire_companies))
        except Exception as exc:
            logger.warning("Falha no provider inhire para '%s': %s", profile.name, exc)
    if "wwr" in profile.providers:
        try:
            raw.extend(wwr.search(profile.keywords, max_jobs=max_jobs))
        except Exception as exc:
            logger.warning("Falha no provider WWR para '%s': %s", profile.name, exc)
    if "greenhouse" in profile.providers:
        try:
            raw.extend(greenhouse.search(profile.keywords, max_jobs=max_jobs,
                                         tokens=greenhouse_companies))
        except Exception as exc:
            logger.warning("Falha no provider Greenhouse para '%s': %s", profile.name, exc)

    matched = [job for job in raw if matches(job, profile).matched]
    logger.info("Busca '%s': %d coletadas, %d após filtro.", profile.name, len(raw), len(matched))
    return matched


def run(config: Optional[Config] = None, searches: Optional[SearchesFile] = None) -> dict:
    """Executa o ciclo completo do monitor. Retorna um dicionário-resumo."""
    config = config or load_config()
    searches = searches or load_searches(Path(config.searches_path))

    storage_path = Path(config.storage_path)
    history = load_history(storage_path)
    is_first_run = len(history) == 0
    logger.info("=== Vagas Monitor iniciando (primeira execução: %s) ===", is_first_run)

    session = build_session()
    gupy = GupyProvider(session=session, delay=config.request_delay_seconds)
    inhire = InhireProvider(tenants=searches.inhire_companies, session=session,
                            delay=config.request_delay_seconds)
    wwr = WwrProvider(session=session, delay=config.request_delay_seconds)
    greenhouse = GreenhouseProvider(tokens=searches.greenhouse_companies, session=session,
                                    delay=config.request_delay_seconds)
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
            jobs = collect_for_search(
                profile, gupy=gupy, inhire=inhire, wwr=wwr, greenhouse=greenhouse,
                max_jobs=config.max_jobs_per_search,
                inhire_companies=searches.inhire_companies,
                greenhouse_companies=searches.greenhouse_companies,
            )
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

                    should_notify = (not is_first_run) or config.initial_notify
                    if not should_notify:
                        record.notification_status = "skipped"
                    elif rel.score >= config.high_score_threshold:
                        notifier.notify_job(job, profile.name, rel.score, rel.reasons)
                        mark_sent(history, sid)
                        immediate_count += 1
                    else:
                        record.notification_status = "digest"   # acumula pro digest
                        digest_added += 1
                else:
                    existing.last_seen_at = now
                    if profile.name not in existing.matched_searches:
                        existing.matched_searches.append(profile.name)

        # Digest ranqueado: junta o que ficou pendente (deste run e dos anteriores)
        if config.send_digest:
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
        gupy.close()
        inhire.close()
        wwr.close()
        greenhouse.close()
        notifier.close()
