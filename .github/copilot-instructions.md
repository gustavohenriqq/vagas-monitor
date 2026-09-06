# Copilot — instruções do repositório (Vagas Monitor)

Monitor de vagas de tecnologia em **Python 3.12**. Varre fontes públicas, filtra
por relevância com regras (sem IA), pontua e notifica no **Telegram**. Roda no
**GitHub Actions**; histórico em **JSON versionado no Git**; sem banco.

Stack: `requests`, `PyYAML`, `Flask`, `pytest`. Não adicione dependências sem necessidade.

## Ao gerar código, siga:

- **Novo provider de vagas** → `src/providers/<x>.py`, herdando `JobProvider` com
  `search(keywords, max_jobs=...) -> list[JobPosting]`. Retorne `JobPosting`
  normalizado. Trate erro de rede com log + lista vazia (não propague exceção).
  Registre em `providers/__init__.py`, `VALID_PROVIDERS` (`src/searches.py`) e
  `build_provider_map()` (`src/monitor.py`); se por-empresa, some em `COMPANY_LIST_KEYS`.
- **Comparação de texto**: use `models.normalize()` (sem acento, minúsculo). Filtro
  de cargo/relevância só em `src/relevance.py`. Matcher casa por fronteira de palavra.
- **Persistência**: escrita atômica, dedup por `stable_id = "provider:external_id"`.
- **Telegram**: escape de HTML em campos dinâmicos; noop sem token; nunca logar token.

## Estilo

- Comentários e logs em **português**; identificadores em inglês.
- Use `logging`, nunca `print()`.
- Toda lógica/parsers novos precisam de teste em `tests/test_core.py` **sem rede**
  (fixtures). Rode `pytest -q`.
- Nunca commite `.env`.

## Fontes permitidas

Só API/RSS público ou SSR (sem login, sem burlar proteção). **Não** implemente
LinkedIn, Indeed ou scraping que viole ToS.

Contexto completo (arquitetura, schema do `searches.yaml`, env vars): ver `CONTEXT.md` e `CLAUDE.md`.
