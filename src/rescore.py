"""
rescore.py — Repontua os registros anteriores ao filtro de relevância.

O `relevance.py` entrou em 18/08/2026. As vagas coletadas antes disso ficaram
gravadas com os padrões da dataclass (`score=0`, `confidence=""`), o que não
quer dizer "vaga irrelevante" e sim "vaga nunca pontuada" — elas poluem o
gráfico de distribuição e somem de qualquer filtro por score mínimo.

Este script roda o `evaluate()` atual sobre esses registros e grava score e
confiança. O `notification_status` NUNCA é tocado: essas vagas já foram
enviadas ou puladas, e mexer nisso reabriria notificação de coisa antiga.

    python -m src.rescore --dry-run   # só mostra o que mudaria
    python -m src.rescore             # repontua só os legados
    python -m src.rescore --todos     # reavalia o histórico inteiro

Use --todos depois de mexer no vocabulário do relevance.py: registros já
pontuados foram avaliados com o vocabulário antigo e podem ter ficado abaixo
do que valem.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import load_config
from .relevance import evaluate
from .storage import JobRecord, load_history, save_history

logger = logging.getLogger(__name__)

# Registro legado: confiança em branco. Depois do filtro de 3 níveis todo
# registro sai com "alta", "media", "baixa" ou "nenhum" — nunca vazio.
def _legado(rec: JobRecord) -> bool:
    return not rec.confidence


def rescore(history: dict[str, JobRecord], *, aplicar: bool = True,
            todos: bool = False) -> dict:
    """Repontua os registros. Devolve um resumo do que mudou.

    Por padrão só toca nos legados (sem confiança). Com `todos=True` reavalia
    o histórico inteiro, para refletir mudança de vocabulário.
    """
    alvos = list(history.values()) if todos else [r for r in history.values() if _legado(r)]
    por_nivel: dict[str, int] = {}
    virou_alto = 0
    mudaram = 0

    for rec in alvos:
        rel = evaluate(rec.job)
        por_nivel[rel.level] = por_nivel.get(rel.level, 0) + 1
        if rel.score >= 7:
            virou_alto += 1
        if rel.score != rec.score or rel.level != rec.confidence:
            mudaram += 1
        if aplicar:
            rec.score = rel.score
            rec.confidence = rel.level
            # notification_status fica como está, de propósito.

    return {
        "legados": len(alvos),
        "por_nivel": por_nivel,
        "score_alto": virou_alto,
        "mudaram": mudaram,
        "intactos": len(history) - len(alvos),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    simular = "--dry-run" in argv
    todos = "--todos" in argv

    config = load_config()
    caminho = Path(config.storage_path)
    history = load_history(caminho)

    resumo = rescore(history, aplicar=not simular, todos=todos)
    logger.info("Registros avaliados: %d", resumo["legados"])
    logger.info("Registros que mudaram de score ou nível: %d", resumo["mudaram"])
    logger.info("Registros já pontuados, intactos: %d", resumo["intactos"])
    logger.info("Distribuição por nível: %s", resumo["por_nivel"])
    logger.info("Passariam a ter score >= 7: %d", resumo["score_alto"])

    if simular:
        logger.info("--dry-run: nada foi gravado.")
        return 0

    save_history(history, caminho)
    logger.info("Histórico regravado em %s.", caminho)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
