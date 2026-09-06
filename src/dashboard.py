"""
dashboard.py — Gera o JSON enxuto que alimenta o painel do GitHub Pages.

O histórico (`data/jobs.json`) passa de 8 MB e guarda a descrição inteira de cada
vaga; servir isso para o navegador seria desperdício. Aqui ficam só os campos que
a tela usa, com chaves curtas para o arquivo não inflar.

    python -m src.dashboard            # escreve docs/data.json
    python -m src.dashboard saida.json # escreve onde você quiser
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .storage import JobRecord, load_history

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("docs/data.json")

# status que contam como "chegou no Telegram" (o resto é histórico interno)
NOTIFICADOS = ("sent", "digest")


def _linha(rec: JobRecord) -> dict:
    """Achata um JobRecord no formato do painel (chaves curtas = arquivo menor)."""
    job = rec.job
    local = ", ".join(p for p in (job.city, job.state, job.country) if p)
    return {
        "t": job.title,
        "e": job.company,
        "u": job.url,
        "p": job.provider,
        "s": rec.score,
        "c": rec.confidence,
        "st": rec.notification_status,
        "pf": rec.profile,
        "w": job.workplace_type,
        "sn": job.seniority,
        "l": local,
        "d": rec.first_seen_at,
        "b": rec.matched_searches,
    }


def build_payload(history: dict[str, JobRecord]) -> dict:
    """Monta o payload do painel: vagas mais recentes primeiro + agregados."""
    registros = sorted(history.values(), key=lambda r: r.first_seen_at, reverse=True)
    vagas = [_linha(r) for r in registros]

    por_provider: dict[str, int] = {}
    por_status: dict[str, int] = {}
    por_score: dict[str, int] = {}
    por_perfil: dict[str, int] = {}
    for r in registros:
        por_provider[r.job.provider] = por_provider.get(r.job.provider, 0) + 1
        por_status[r.notification_status] = por_status.get(r.notification_status, 0) + 1
        por_score[str(r.score)] = por_score.get(str(r.score), 0) + 1
        por_perfil[r.profile] = por_perfil.get(r.profile, 0) + 1

    notificadas = sum(1 for r in registros if r.notification_status in NOTIFICADOS)

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(vagas),
        "notificadas": notificadas,
        "agregados": {
            "provider": por_provider,
            "status": por_status,
            "score": por_score,
            "perfil": por_perfil,
        },
        "vagas": vagas,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    destino = Path(argv[0]) if argv else DEFAULT_OUTPUT

    history = load_history()
    payload = build_payload(history)

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atômica, mesma abordagem do storage.py.
    temp = destino.with_suffix(destino.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, destino)

    kb = destino.stat().st_size / 1024
    logger.info("Painel: %d vagas (%d notificadas) em %s (%.0f KB).",
                payload["total"], payload["notificadas"], destino, kb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
