# Contexto do projeto — Vagas Monitor

Cole isto no chat do VS Code para dar contexto do projeto a um assistente.

## Visão geral

Monitor automatizado de vagas de **tecnologia**. Varre várias fontes públicas,
filtra por relevância com regras explícitas (sem IA/ML), pontua cada vaga e
notifica no **Telegram**. Roda sozinho e de graça no **GitHub Actions** (cron).
Também tem um **painel web local** (Flask) para configurar as buscas.

- Linguagem: **Python 3.12**. Deps: `requests`, `PyYAML`, `Flask`, `pytest`.
- Sem banco: histórico em **JSON versionado no Git** (`data/jobs.json`, escrita atômica).
- Repositório: `github.com/gustavohenriqq/vagas-monitor` (privado).

## Fluxo (pipeline)

1. Carrega config (`.env`) e buscas (`config/searches.yaml`).
2. Para cada busca habilitada, consulta os providers dos `providers` dela.
3. Normaliza tudo em `JobPosting`, aplica o **matcher** (filtro).
4. Deduplica contra o histórico (`data/jobs.json`) por `stable_id` (`provider:id`).
5. Calcula **score de relevância (0–10)**; score ≥ `HIGH_SCORE_THRESHOLD` (7)
   notifica na hora, o resto vai para um **digest ranqueado** (1x/dia, às 20h BRT).
6. Salva histórico e envia resumo/digest (opcionais).

## Estrutura

```
src/
  main.py            # entrypoint CLI (python -m src.main)
  monitor.py         # orquestrador: build_provider_map() + collect_for_search() + run()
  webapp.py          # painel Flask (python -m src.webapp) — CRUD de buscas, preview, run
  config.py          # variáveis de ambiente (.env), sem python-dotenv
  searches.py        # SearchProfile, SearchesFile (company_lists por provider), load/save YAML
  models.py          # JobPosting normalizado; normalize()/strip_accents(); infer_seniority()
  relevance.py       # filtro em 3 níveis (classify_title) + score_job()/evaluate()
  matcher.py         # matches(job, profile): keywords/exclusões/senioridade/local + modo `precise`
  storage.py         # JobRecord + histórico JSON atômico (score, confidence, profile)
  telegram_notifier.py # alerta individual + digest ranqueado + resumo (noop se sem token)
  providers/
    base.py          # JobProvider (interface), build_session(), fetch_json() (retry/backoff)
    gupy.py          # Gupy — busca GLOBAL por palavra-chave (employability-portal.gupy.io)
    inhire.py        # inhire — por empresa (api.inhire.app, header X-Tenant; chave "jobsPage")
    recrutei.py      # Recrutei — modo GLOBAL (scrape SSR de empregos.recrutei.com.br/busca)
    greenhouse.py    # Greenhouse — por board (boards-api.greenhouse.io), API oficial
    wwr.py           # We Work Remotely — feeds RSS (remoto)
    remotive.py      # Remotive — API pública (remoto global)
    remoteok.py      # RemoteOK — API pública (remoto global; exige User-Agent)
    lever.py         # Lever — por empresa (api.lever.co/v0/postings/<c>?mode=json)
    ashby.py         # Ashby — por empresa (api.ashbyhq.com/posting-api/job-board/<c>)
    recruitee.py     # Recruitee — por empresa (<c>.recruitee.com/api/offers/)
    smartrecruiters.py # SmartRecruiters — por empresa (api.smartrecruiters.com/v1/companies/<c>/postings)
config/searches.yaml # perfis, buscas e listas de empresas por ATS
data/jobs.json       # histórico (commitado pelo próprio workflow)
tests/test_core.py   # testes sem rede (parsers + matcher + relevância), 18 casos
.github/workflows/monitor.yml # cron 8/12/16/20h BRT; digest às 20h; commita jobs.json
```

## Modelo de dados (`JobPosting`)

Campos: `provider, external_id, title, company, url, description, city, state,
country, workplace_type (remote|hybrid|onsite|unknown), seniority
(estagio|junior|pleno|senior|lead|indefinido), published_date, deadline`.
`stable_id = "provider:external_id"`. Senioridade é inferida do título.

## Filtro de relevância (3 níveis) — `relevance.py`

Avalia o **título**:
- **ALTA**: cargo de tech inequívoco (ex.: "Engenheiro de Dados") → passa sozinho.
- **MÉDIA**: cargo ambíguo ("Analista", "Consultor") só com qualificador de tech junto.
- **BAIXA**: ferramenta ("Power BI", "SQL") só com palavra de cargo junto.
- Sem cargo de tech claro → rejeitado.

Score 0–10 = nível + remoto/híbrido + stack concreta + senioridade conhecida.
Uma busca usa esse filtro quando tem `precise: true`; senão usa `keywords`.

## Providers

Dois tipos:
- **Globais** (endpoint único, sem lista de empresa): `gupy` (por palavra-chave),
  `recrutei` (SSR global), `wwr`, `remotive`, `remoteok`.
- **Por empresa** (precisam de lista de tokens/slugs): `inhire` (`inhire_companies`),
  `greenhouse` (`greenhouse_companies`), `lever`, `ashby`, `recruitee`,
  `smartrecruiters` (`<provider>_companies`).

Todos expõem `search(keywords, max_jobs=...) -> list[JobPosting]`. Falha de um
provider é logada e não derruba a execução. `monitor.build_provider_map()` instancia
todos a partir do `SearchesFile`; `collect_for_search()` itera `profile.providers`.

## Config das buscas (`config/searches.yaml`)

```yaml
inhire_companies: [radix, matera, ...]        # tenants (minúsculo)
greenhouse_companies: [ifoodcarreiras, nubank, stone, ...]  # board tokens
lever_companies: []        # ATS por empresa (prontos; preencher para ativar)
ashby_companies: []
recruitee_companies: []
smartrecruiters_companies: []

searches:
  - name: "Tech — Remoto"
    enabled: true
    profile: brasil
    precise: true                    # usa o filtro de 3 níveis
    providers: [gupy, inhire, recrutei, greenhouse]
    keywords: [...]                  # opcional; restringe ainda mais
    workplace_types: [remote]        # remote|hybrid|onsite; vazio = qualquer
    locations: []                    # substrings de cidade/estado; vazio = qualquer
  - name: "Tech — Híbrido (BH e região)"
    ...
    workplace_types: [hybrid]
    locations: [belo horizonte, contagem, sete lagoas, ...]  # sem "mg" (casaria o estado)
  - name: "Internacional — Remoto (PT/ES)"
    profile: internacional
    providers: [wwr, greenhouse, remotive, remoteok]
    workplace_types: [remote]
    locations: [anywhere, latin america, americas, ...]
```

Perfis atuais: **Brasil** (remoto em qualquer lugar OU híbrido em BH e região) e
**Internacional** (remoto aberto a Brasil/LatAm).

## Variáveis de ambiente (`.env` / secrets do Actions)

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `INITIAL_NOTIFY` (false),
`SEND_SUMMARY`, `SEND_DIGEST`, `HIGH_SCORE_THRESHOLD` (7),
`MAX_JOBS_PER_SEARCH` (1500 no Actions), `REQUEST_DELAY_SECONDS`, `LOG_LEVEL`.
Sem credenciais do Telegram, o notificador vira *noop* (só loga).

## Execução

```bash
pip install -r requirements.txt
pytest -q                       # 18 testes, sem rede
python -m src.main              # roda o monitor (lê .env + searches.yaml)
python -m src.webapp            # painel em http://localhost:5000
```

GitHub Actions: `.github/workflows/monitor.yml` roda testes → monitor → commita
`data/jobs.json`. Cron 8/12/16h (só alertas) e 20h (alertas + digest), BRT.
Precisa dos secrets do Telegram e do escopo `workflow` no push.

## Como estender

- **Nova empresa** num ATS por-empresa: adicione o token na lista
  `<provider>_companies` e inclua o provider no `providers` de uma busca.
  (Greenhouse: token = trecho de `job-boards.greenhouse.io/<token>`; verificável em
  `boards-api.greenhouse.io/v1/boards/<token>`.)
- **Nova fonte**: crie `src/providers/<x>.py` (herda `JobProvider`, implementa
  `search`), registre em `providers/__init__.py`, em `VALID_PROVIDERS`
  (`searches.py`) e no `build_provider_map()` (`monitor.py`). Se for por empresa,
  adicione a chave em `COMPANY_LIST_KEYS`.

## Estado atual / pendências

- Ativos: Gupy, inhire (48 empresas), Recrutei (global), Greenhouse (25 boards:
  17 BR + 8 intl), WWR, Remotive, RemoteOK.
- Prontos mas sem tokens: Lever, Ashby, Recruitee, SmartRecruiters (listas vazias).
- Limitações conhecidas: Greenhouse não distingue "híbrido" (só remoto/cidade);
  Recrutei global não traz cidade (por isso fica fora do híbrido-BH); filtro por
  título pode escapar vaga de tech com título atípico (ajustar vocabulário em
  `relevance.py`).
- Fora do escopo por risco de ToS/bloqueio: LinkedIn, Indeed, GeekHunter, 99Jobs, Solides.
```
