"""
storage.py — Persistência atômica das vagas já vistas em JSON.

Garante:
- gravação atômica (arquivo temporário + os.replace)
- leitura segura mesmo com arquivo vazio/inexistente
- deduplicação por stable_id (provider:id)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import JobPosting

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_PATH = Path("data/jobs.json")


@dataclass
class JobRecord:
    """Vaga armazenada no histórico, com metadados de acompanhamento."""

    stable_id: str
    job: JobPosting
    first_seen_at: str
    last_seen_at: str
    notification_status: str = "pending"    # pending | sent | skipped | digest
    matched_searches: list[str] = field(default_factory=list)
    score: int = 0
    confidence: str = ""                     # alta | media | baixa
    profile: str = "brasil"

    def to_dict(self) -> dict:
        d = self.job.to_dict()
        d.update({
            "stable_id": self.stable_id,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "notification_status": self.notification_status,
            "matched_searches": self.matched_searches,
            "score": self.score,
            "confidence": self.confidence,
            "profile": self.profile,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "JobRecord":
        job = JobPosting.from_dict(data)
        return cls(
            stable_id=data.get("stable_id") or job.stable_id,
            job=job,
            first_seen_at=data.get("first_seen_at", ""),
            last_seen_at=data.get("last_seen_at", ""),
            notification_status=data.get("notification_status", "pending"),
            matched_searches=data.get("matched_searches", []),
            score=data.get("score", 0),
            confidence=data.get("confidence", ""),
            profile=data.get("profile", "brasil"),
        )


def load_history(path: Path = DEFAULT_STORAGE_PATH) -> dict[str, JobRecord]:
    """Carrega o histórico. Retorna {} se vazio/inexistente/corrompido."""
    path = Path(path)
    if not path.exists():
        logger.info("Histórico não encontrado em %s. Iniciando vazio.", path)
        return {}
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        raw = json.loads(content)
        if not isinstance(raw, list):
            logger.warning("Formato inesperado no histórico (esperava lista). Iniciando vazio.")
            return {}
        history: dict[str, JobRecord] = {}
        for item in raw:
            try:
                rec = JobRecord.from_dict(item)
                if rec.stable_id:
                    history[rec.stable_id] = rec
            except Exception as exc:
                logger.warning("Entrada inválida ignorada: %s", exc)
        logger.info("Histórico carregado: %d vagas.", len(history))
        return history
    except json.JSONDecodeError as exc:
        logger.error("JSON inválido no histórico: %s. Iniciando vazio.", exc)
        return {}
    except OSError as exc:
        logger.error("Erro ao ler histórico: %s. Iniciando vazio.", exc)
        return {}


def save_history(history: dict[str, JobRecord], path: Path = DEFAULT_STORAGE_PATH) -> None:
    """Salva o histórico atomicamente."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [rec.to_dict() for rec in history.values()]
    dir_path = str(path.parent)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp", prefix="jobs_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            logger.info("Histórico salvo: %d vagas em %s.", len(data), path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.error("Falha ao salvar histórico em %s: %s", path, exc)
        raise


def mark_sent(history: dict[str, JobRecord], stable_id: str) -> None:
    rec = history.get(stable_id)
    if rec:
        rec.notification_status = "sent"
