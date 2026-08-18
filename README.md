# Vagas Monitor

Monitor automatizado de vagas de **tecnologia** que varre múltiplas fontes,
filtra por relevância com regras explícitas (sem IA), pontua cada vaga e notifica
no **Telegram** — rodando sozinho e de graça no **GitHub Actions**.

Inclui um **painel web local** para configurar as buscas sem editar arquivo.

---

## O que faz

- **3 fontes públicas (sem login, sem violar ToS):**
  - **Gupy** — busca global por palavra-chave (`employability-portal.gupy.io`), todas as empresas.
  - **inhire** — vagas das empresas (tenants) configuradas (`api.inhire.app`, por `X-Tenant`).
  - **We Work Remotely** — feeds RSS públicos, vagas 100% remotas (internacional).
- **Dois perfis:**
  - **Brasil** — remoto em qualquer lugar **ou** híbrido em BH e região metropolitana.
  - **Internacional** — remoto em regiões que aceitam Brasil/LatAm (Anywhere, Latin America).
- **Filtro em 3 níveis de confiança** (não aprova por palavra-chave solta):
  - Cargo de tech inequívoco no título passa sozinho.
  - Cargo ambíguo ("Analista", "Consultor") só conta com um qualificador de tech junto.
  - Ferramenta ("Power BI", "SQL") só conta com uma palavra de cargo junto.
- **Score de relevância 0–10** por regras (cargo, modelo de trabalho, stack, senioridade).
- **Anti-flood:** vaga de **alta relevância (score ≥ 7) chega na hora**; o resto entra
  num **digest ranqueado** enviado 1x/dia.
- **Notificação no Telegram**, sem repetir (dedup por `fonte:id`).

> LinkedIn, Indeed, GeekHunter, 99Jobs e Solides **não** estão incluídos: exigem
> login/scraping frágil ou API de parceiro, com risco de ToS/bloqueio. A
> arquitetura de providers permite plugar novas fontes depois.

---

## Estrutura

```
vagas-monitor/
├── src/
│   ├── main.py              # entrypoint CLI (python -m src.main)
│   ├── monitor.py           # orquestrador: busca, pontua, notifica/digest
│   ├── webapp.py            # painel web Flask (python -m src.webapp)
│   ├── config.py            # variáveis de ambiente (.env)
│   ├── searches.py          # leitura/gravação do searches.yaml
│   ├── models.py            # JobPosting normalizado + senioridade
│   ├── relevance.py         # filtro em 3 níveis + score de relevância
│   ├── matcher.py           # regras de filtro (keywords/senioridade/local/preciso)
│   ├── storage.py           # histórico JSON atômico (score, digest, perfil)
│   ├── telegram_notifier.py # alerta individual + digest ranqueado
│   └── providers/
│       ├── base.py          # interface + HTTP resiliente
│       ├── gupy.py          # Gupy (busca global)
│       ├── inhire.py        # inhire (por empresa)
│       └── wwr.py           # We Work Remotely (RSS)
├── config/searches.yaml     # perfis, buscas, empresas do inhire
├── data/jobs.json           # histórico (commitado pelo Actions)
├── tests/test_core.py       # testes sem rede
├── .github/workflows/monitor.yml
├── .env.example
└── requirements.txt
```

---

## Começando

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/macOS
pip install -r requirements.txt
pytest -q                      # deve passar tudo
```

### 1. Bot do Telegram

Fale com o [@BotFather](https://t.me/BotFather) → `/newbot` → guarde o token.
Abra a conversa com o seu bot e envie **`/start`** (um bot não inicia conversa).
Descubra seu chat ID com o [@userinfobot](https://t.me/userinfobot).

### 2. Configuração

```bash
cp .env.example .env           # Copy-Item no PowerShell
```

Preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

### 3. Painel web (configurar buscas)

```bash
python -m src.webapp           # abre em http://localhost:5000
```

Criar/editar/testar buscas, gerenciar empresas do inhire, rodar o monitor. Tudo
salvo em `config/searches.yaml` (que você também pode editar à mão).

### 4. Primeira execução (baseline silencioso)

```bash
# Windows PowerShell
$env:INITIAL_NOTIFY="false"; python -m src.main
```

Registra as vagas atuais sem notificar. Das próximas em diante, só chega novidade.

---

## Como funciona a relevância

**Filtro em 3 níveis** (`src/relevance.py`) — avalia o TÍTULO:

| Nível | Regra | Exemplo |
|---|---|---|
| ALTA | cargo de tech inequívoco | "Engenheiro de Dados", "Desenvolvedor Python" |
| MÉDIA | cargo ambíguo + qualificador de tech | "Coordenador de Tecnologia" |
| BAIXA | ferramenta + palavra de cargo | "Analista de Power BI" |
| — (rejeita) | sem cargo de tech claro | "Engenheiro de Manutenção HVAC" |

**Score 0–10** = nível de confiança + remoto/híbrido + stack concreta + senioridade.
Score **≥ `HIGH_SCORE_THRESHOLD` (padrão 7)** notifica na hora; abaixo vai pro digest.

Ative o filtro numa busca com `precise: true`. Sem ele, a busca volta ao modo de
palavra-chave (`keywords`).

---

## Configuração das buscas (`config/searches.yaml`)

```yaml
inhire_companies: [radix, matera, dp6, ...]   # tenants do inhire (subdomínio)

searches:
  - name: "Tech — Remoto"
    enabled: true
    profile: brasil
    precise: true                 # usa o filtro de 3 níveis
    providers: [gupy, inhire]
    keywords: [...]               # opcional; restringe ainda mais quando presente
    workplace_types: [remote]     # remote|hybrid|onsite; vazio = qualquer
    locations: []                 # substrings de cidade/estado; vazio = qualquer

  - name: "Internacional — Remoto (PT/ES)"
    enabled: true
    profile: internacional
    precise: true
    providers: [wwr]
    workplace_types: [remote]
    locations: ["anywhere", "latin america", "americas"]
```

Senioridade reconhecida: `estagio`, `junior`, `pleno`, `senior`, `lead`. É deduzida
do título (e do campo próprio no inhire, quando existe).

---

## Variáveis de ambiente

| Variável | Padrão | Função |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Token do bot |
| `TELEGRAM_CHAT_ID` | — | Chat de destino |
| `INITIAL_NOTIFY` | `false` | Notificar tudo na primeira execução |
| `SEND_SUMMARY` | `false` | Enviar resumo ao final |
| `SEND_DIGEST` | `false` | Enviar o digest ranqueado nesta execução |
| `HIGH_SCORE_THRESHOLD` | `7` | Score mínimo (0–10) para notificar na hora |
| `MAX_JOBS_PER_SEARCH` | `200` | Teto de vagas por busca/provider |
| `REQUEST_DELAY_SECONDS` | `1.0` | Intervalo entre requisições |
| `LOG_LEVEL` | `INFO` | Nível de log |

Sem credenciais do Telegram, o notificador vira *noop* (só registra no log).

---

## GitHub Actions (rodando sozinho)

Crie os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` em
**Settings → Secrets and variables → Actions**. O workflow roda os testes, executa
o monitor e commita `data/jobs.json` quando muda.

Agenda (BRT = UTC-3):

- **8h, 12h, 16h** — só alertas imediatos (alta relevância).
- **20h** — alertas imediatos **+ digest ranqueado** do resto do dia (`SEND_DIGEST`).

---

## Como adicionar uma nova fonte

Crie `src/providers/<fonte>.py` com uma classe que herde de `JobProvider` e
implemente `search(keywords, max_jobs)` devolvendo `JobPosting` normalizado.
Registre em `src/providers/__init__.py`, no `monitor.collect_for_search` e em
`VALID_PROVIDERS` (`src/searches.py`). Filtro, score, storage e notifier funcionam
sem alteração.

---

## Limitações

- **inhire sem busca global:** depende da lista de empresas em `inhire_companies`.
- **Filtro por título:** vaga de tech com título fora do padrão pode escapar —
  ajuste o vocabulário em `src/relevance.py`.
- **WWR em inglês:** a `region` define o mercado; o perfil internacional usa só as
  regiões abertas ao Brasil/LatAm.
```
