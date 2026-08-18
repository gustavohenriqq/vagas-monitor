"""
config.py — Leitura, parsing e validação das configurações de ambiente.

Todas as variáveis são lidas de variáveis de ambiente. Para execução local,
um arquivo .env na raiz do projeto é carregado por um parser mínimo embutido
(sem dependência de python-dotenv). Variáveis já presentes no ambiente têm
precedência sobre o .env — o que preserva o comportamento no GitHub Actions,
onde os secrets são injetados diretamente no ambiente.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Raiz do projeto: src/config.py -> src/ -> raiz
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(path: Path = DEFAULT_ENV_PATH, override: bool = False) -> int:
    """Carrega pares CHAVE=VALOR de um arquivo .env para os.environ."""
    if not path.is_file():
        logger.debug("Arquivo .env não encontrado em %s. Usando apenas o ambiente.", path)
        return 0

    loaded = 0
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Não foi possível ler %s: %s. Usando apenas o ambiente.", path, exc)
        return 0

    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            logger.warning("Linha %d do .env ignorada (sem '='): %s", lineno, raw_line[:40])
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded += 1

    if loaded:
        logger.debug("Carregadas %d variáveis de %s.", loaded, path)
    return loaded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def _env_int(key: str, default: int, min_val: int = 0) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return max(int(raw), min_val)
    except ValueError:
        logger.warning("Variável %s inválida '%s', usando padrão %d.", key, raw, default)
        return default


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, "").strip() or default


# ---------------------------------------------------------------------------
# Dataclass de configuração
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Agrupa todas as configurações da aplicação."""

    telegram_bot_token: str = field(default="")
    telegram_chat_id: str = field(default="")

    initial_notify: bool = False
    send_summary: bool = False
    send_empty_summary: bool = False
    send_digest: bool = False          # envia o digest ranqueado nesta execução
    high_score_threshold: int = 7      # score >= isto notifica na hora; abaixo vai pro digest

    max_jobs_per_search: int = 200
    request_delay_seconds: float = 1.0

    log_level: str = "INFO"

    searches_path: str = "config/searches.yaml"
    storage_path: str = "data/jobs.json"

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_config(env_path: Optional[Path] = DEFAULT_ENV_PATH) -> Config:
    """Carrega e valida as configurações a partir das variáveis de ambiente."""
    if env_path is not None:
        load_dotenv(env_path)

    delay_raw = os.environ.get("REQUEST_DELAY_SECONDS", "").strip()
    try:
        delay = max(float(delay_raw), 0.0) if delay_raw else 1.0
    except ValueError:
        logger.warning("REQUEST_DELAY_SECONDS inválido, usando 1.0s.")
        delay = 1.0

    cfg = Config(
        telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=_env_str("TELEGRAM_CHAT_ID", ""),
        initial_notify=_env_bool("INITIAL_NOTIFY", False),
        send_summary=_env_bool("SEND_SUMMARY", False),
        send_empty_summary=_env_bool("SEND_EMPTY_SUMMARY", False),
        send_digest=_env_bool("SEND_DIGEST", False),
        high_score_threshold=_env_int("HIGH_SCORE_THRESHOLD", 7, min_val=0),
        max_jobs_per_search=_env_int("MAX_JOBS_PER_SEARCH", 200, min_val=1),
        request_delay_seconds=delay,
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        searches_path=_env_str("SEARCHES_PATH", "config/searches.yaml"),
        storage_path=_env_str("STORAGE_PATH", "data/jobs.json"),
    )

    if not cfg.telegram_configured:
        logger.warning(
            "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados. "
            "Notificações serão desativadas (modo noop)."
        )

    return cfg
