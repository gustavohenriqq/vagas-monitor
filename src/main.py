"""
main.py — Entry point de linha de comando do Vagas Monitor.

Uso:
    python -m src.main            # a partir da raiz do projeto
    python src/main.py            # também funciona
"""

import sys
from pathlib import Path

# Permite rodar tanto como módulo (-m src.main) quanto como script direto.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.config import load_config
    from src.monitor import run, setup_logging
else:
    from .config import load_config
    from .monitor import run, setup_logging


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)
    run(config)


if __name__ == "__main__":
    main()
