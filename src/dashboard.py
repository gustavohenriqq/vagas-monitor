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
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .models import normalize
from .storage import JobRecord, load_history

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("docs/data.json")

# status que contam como "chegou no Telegram" (o resto é histórico interno)
NOTIFICADOS = ("sent", "digest")

# Região, derivada do local. O perfil da busca NÃO serve para isso: "brasil" ali
# é o nome do perfil que casou, não o país da vaga.
REGIAO_BR = "brasil"
REGIAO_LATAM = "latam"
REGIAO_SEM_PAIS = "sem_pais"
REGIAO_OUTROS = "outros"

_MARCAS_BR = (
    "brasil", "brazil", "sao paulo", "rio de janeiro", "belo horizonte", "curitiba",
    "porto alegre", "recife", "fortaleza", "salvador", "brasilia", "campinas",
    "florianopolis", "goiania", "manaus", "belem", "vitoria", "natal", "joao pessoa",
    "maceio", "teresina", "cuiaba", "campo grande", "sao jose", "santo andre",
    "osasco", "sorocaba", "ribeirao preto", "uberlandia", "londrina", "joinville",
    "blumenau", "caxias do sul", "niteroi", "guarulhos", "barueri", "jundiai",
)
# Genéricos: a vaga não diz o país. Pode muito bem aceitar o Brasil, então fica
# num balde próprio em vez de virar "outros".
# Genéricos: a vaga não diz o país. Pode muito bem aceitar o Brasil, então fica
# num balde próprio em vez de virar "outros".
_MARCAS_GENERICAS = (
    "remote", "remoto", "anywhere", "worldwide", "global", "home office",
)
_MARCAS_LATAM = (
    "latam", "latin america", "america latina", "south america", "americas",
    "mexico", "colombia", "argentina", "chile", "peru", "uruguai", "uruguay",
    "bolivia", "paraguai", "paraguay", "equador", "ecuador", "venezuela",
    "costa rica", "panama", "guatemala", "republica dominicana", "bogota",
    "buenos aires", "santiago", "lima", "montevideo", "ciudad de mexico",
)
# Marcadores inequívocos de fora. Precisam ser checados ANTES dos genéricos:
# "Remote - USA" tem "remote", mas não é uma vaga sem país declarado.
_MARCAS_FORA = (
    "united states", "usa", "estados unidos", "san francisco", "new york",
    "california", "menlo park", "foster city", "bellevue", "seattle", "austin",
    "boston", "chicago", "canada", "toronto", "united kingdom", "london",
    "england", "ireland", "dublin", "europe", "emea", "apac", "singapore",
    "hong kong", "asia", "india", "bangalore", "taiwan", "taipei", "japan",
    "tokyo", "australia", "sydney", "melbourne", "germany", "berlin", "munich",
    "france", "paris", "poland", "warsaw", "netherlands", "amsterdam",
    "ho chi minh", "vietnam", "philippines", "israel", "tel aviv", "dubai",
    "south africa", "us timezones",
)
# "us" / "u.s." isolado precisa de fronteira de palavra: como substring casaria
# dentro de "Belarus", "business" e afins.
_RE_EUA = re.compile("(?<![a-z0-9])(?:u[.]s[.]a?[.]?|us|usa)(?![a-z0-9])")
_PAIS_BR = ("br", "bra", "brasil", "brazil")
_PAIS_LATAM = ("mx", "ar", "cl", "co", "pe", "uy", "bo", "py", "ec", "ve", "cr", "pa", "gt", "do")


def regiao(city: str, state: str, country: str) -> str:
    """Classifica a vaga em brasil | latam | sem_pais | outros pelo local.

    A ordem importa: marcador de país de fora vence o genérico, senão
    "Remote - USA" seria lido como vaga sem país declarado.
    """
    pais = normalize(country).strip()
    if pais in _PAIS_BR:
        return REGIAO_BR
    blob = normalize(f"{city} {state} {country}").strip()
    if not blob:
        return REGIAO_SEM_PAIS
    if any(m in blob for m in _MARCAS_BR):
        return REGIAO_BR
    if pais in _PAIS_LATAM or any(m in blob for m in _MARCAS_LATAM):
        return REGIAO_LATAM
    if any(m in blob for m in _MARCAS_FORA) or _RE_EUA.search(blob):
        return REGIAO_OUTROS
    if any(m in blob for m in _MARCAS_GENERICAS):
        return REGIAO_SEM_PAIS
    return REGIAO_OUTROS


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
        "r": regiao(job.city, job.state, job.country),
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
    por_regiao: dict[str, int] = {}
    for r in registros:
        por_provider[r.job.provider] = por_provider.get(r.job.provider, 0) + 1
        por_status[r.notification_status] = por_status.get(r.notification_status, 0) + 1
        por_score[str(r.score)] = por_score.get(str(r.score), 0) + 1
        por_perfil[r.profile] = por_perfil.get(r.profile, 0) + 1
        reg = regiao(r.job.city, r.job.state, r.job.country)
        por_regiao[reg] = por_regiao.get(reg, 0) + 1

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
            "regiao": por_regiao,
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
