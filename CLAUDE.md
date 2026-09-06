# CLAUDE.md — instruções do projeto Vagas Monitor

Monitor de vagas de tecnologia em Python 3.12. Varre fontes públicas, filtra por
relevância (regras, sem IA), pontua e notifica no Telegram. Roda no GitHub Actions.
Histórico em JSON versionado no Git. Sem banco de dados.

## Regras de arquitetura

- **Providers** (`src/providers/`): cada fonte herda de `JobProvider` e implementa
  `search(keywords, max_jobs=...) -> list[JobPosting]`. Sempre devolver
  `JobPosting` normalizado (nunca dicts crus). Falha de rede é logada e retorna
  lista vazia — **nunca** deixar exceção derrubar a execução.
- **Registro central**: adicionar provider = criar o arquivo + registrar em
  `providers/__init__.py`, em `VALID_PROVIDERS` (`searches.py`) e em
  `build_provider_map()` (`monitor.py`). Se for por-empresa, adicionar a chave em
  `COMPANY_LIST_KEYS` (`searches.py`).
- **Normalização/relevância**: comparações de texto passam por `models.normalize()`
  (minúsculas, sem acento). O filtro de 3 níveis vive em `relevance.py`
  (`classify_title`, `score_job`, `evaluate`) — mexer no vocabulário lá, não espalhar.
- **Matcher** (`matcher.py`): casa por fronteira de palavra (regex), não substring.
  `precise: true` na busca usa o filtro de 3 níveis; senão usa `keywords`.
- **Storage** (`storage.py`): escrita atômica (temp + `os.replace`). Dedup por
  `stable_id = "provider:external_id"`. Nunca marcar como notificado sem confirmar envio.
- **Notificador** (`telegram_notifier.py`): sem credenciais vira *noop*. Escapar
  HTML de todo campo dinâmico. Não logar o token.

## Convenções

- Comentários e mensagens de log em **português**. Código/identificadores em inglês.
- Sem dependências novas sem necessidade (stack atual: requests, PyYAML, Flask, pytest).
- Nada de `print()` — usar `logging`.
- Toda mudança de parser/lógica precisa de teste em `tests/test_core.py`
  (**sem rede** — usar fixtures). Rodar `pytest -q` antes de considerar pronto.
- Não commitar `.env` (segredos ficam nos secrets do Actions).

## Fontes e limites

- Só fontes com **API/RSS público** ou **SSR** — sem login, sem burlar proteção.
- **Proibido**: LinkedIn, Indeed e scraping que viole ToS (decisão de projeto).
- Providers por-empresa precisam de tokens verificados (ex.: Greenhouse em
  `boards-api.greenhouse.io/v1/boards/<token>`).

## Comandos

```
pytest -q            # testes (sem rede)
python -m src.main   # roda o monitor
python -m src.webapp # painel local :5000
```

Ver `CONTEXT.md` para o mapa completo de arquivos, schema do `searches.yaml` e
variáveis de ambiente.
