# Vagas Monitor

Monitora vagas de emprego no **Gupy** e no **inhire**, filtra por palavra-chave,
área, senioridade e local, e notifica as novidades pelo **Telegram**. Inclui um
**painel web local** para configurar as buscas sem editar arquivo.

Inspirado no `dio-bootcamp-monitor`: mesma arquitetura modular (providers →
matcher → storage JSON atômico → notificador Telegram → orquestrador), com
testes e execução diária via GitHub Actions.

---

## O que ele faz

- **Gupy:** busca global por palavra-chave na API pública
  `employability-portal.gupy.io/api/v1/jobs` (todas as empresas de uma vez).
- **inhire:** o inhire **não tem** busca global pública — cada empresa expõe sua
  página de carreira em `api.inhire.app/job-posts/public/pages` (header
  `X-Tenant`). Você lista as empresas no painel e o monitor filtra pela sua
  palavra-chave localmente.
- **Filtros:** palavra-chave (casa qualquer), exclusões, senioridade
  (estágio/júnior/pleno/sênior/lead), tipo de local (remoto/híbrido/presencial) e
  região.
- **Notificação:** uma mensagem no Telegram por vaga nova, sem repetir (dedup por
  `provider:id`).

> Nenhum login é feito. Apenas conteúdo público via HTTP. O LinkedIn **não** está
> incluído por opção: exige automação logada, viola os Termos de Uso e arrisca o
> banimento da conta. A arquitetura de providers permite plugá-lo depois se você
> quiser assumir esse risco.

---

## Estrutura

```
vagas-monitor/
├── src/
│   ├── main.py              # entrypoint CLI (python -m src.main)
│   ├── monitor.py           # orquestrador do ciclo completo
│   ├── webapp.py            # painel web Flask (python -m src.webapp)
│   ├── config.py            # variáveis de ambiente (.env)
│   ├── searches.py          # leitura/gravação do searches.yaml
│   ├── models.py            # JobPosting normalizado + senioridade
│   ├── matcher.py           # regras de filtro
│   ├── storage.py           # histórico JSON atômico
│   ├── telegram_notifier.py # envio Telegram
│   └── providers/
│       ├── base.py          # interface + HTTP resiliente
│       ├── gupy.py          # provider Gupy (busca global)
│       └── inhire.py        # provider inhire (por empresa)
├── config/searches.yaml     # suas buscas + empresas do inhire
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
Abra a conversa com o seu bot e envie **`/start`** (um bot não inicia conversa;
sem isso todo envio falha com `chat not found`). Descubra seu chat ID com o
[@userinfobot](https://t.me/userinfobot).

### 2. Configuração

```bash
cp .env.example .env           # Copy-Item no PowerShell
```

Preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`.

### 3. Painel web (configurar buscas)

```bash
python -m src.webapp
# abre em http://localhost:5000
```

No painel você pode:

- criar/editar/excluir **buscas** (palavras-chave, exclusões, senioridade, local);
- gerenciar a **lista de empresas do inhire**;
- **testar** uma busca ao vivo (prévia, sem gravar nem notificar);
- **rodar o monitor agora** (grava histórico e notifica).

Tudo é salvo em `config/searches.yaml`, que você também pode editar à mão.

### 4. Primeira execução (registrar sem inundar o Telegram)

```bash
# Linux/macOS
INITIAL_NOTIFY=false python -m src.main
# Windows PowerShell
$env:INITIAL_NOTIFY="false"; python -m src.main
```

Com `INITIAL_NOTIFY=false` (padrão), a primeira execução só registra as vagas
atuais, sem notificar. Da próxima vez em diante, só chega vaga nova.

---

## Configuração das buscas (`config/searches.yaml`)

```yaml
inhire_companies:          # tenants do inhire (o início do link do portal)
  - programmers            # -> programmers.inhire.app
  - appmax

searches:
  - name: "Backend Python Remoto"
    enabled: true
    providers: [gupy, inhire]
    keywords: ["python", "backend", "django"]   # casa QUALQUER uma; vazio = tudo
    exclude_keywords: ["estágio"]               # descarta se aparecer
    seniority: [pleno, senior]                  # vazio = qualquer
    workplace_types: [remote]                   # remote|hybrid|onsite; vazio = qualquer
    locations: ["são paulo", "remoto"]          # substrings; vazio = qualquer
```

Senioridade reconhecida: `estagio`, `junior`, `pleno`, `senior`, `lead`,
`indefinido`. É deduzida do título da vaga (e, no inhire, do campo próprio quando
existe).

---

## Variáveis de ambiente

| Variável | Padrão | Função |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Token do bot |
| `TELEGRAM_CHAT_ID` | — | Chat de destino |
| `INITIAL_NOTIFY` | `false` | Notificar tudo na primeira execução |
| `SEND_SUMMARY` | `false` | Enviar resumo ao final |
| `SEND_EMPTY_SUMMARY` | `false` | Resumo mesmo sem novidades |
| `MAX_JOBS_PER_SEARCH` | `200` | Teto de vagas por busca/provider |
| `REQUEST_DELAY_SECONDS` | `1.0` | Intervalo entre requisições |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/... |

Sem credenciais do Telegram, o notificador vira *noop* (só registra no log o que
enviaria) — útil para testar a filtragem.

---

## GitHub Actions (rodar sozinho)

Crie os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` em
**Settings → Secrets and variables → Actions**. O workflow
`.github/workflows/monitor.yml` roda a suíte de testes, executa o monitor
diariamente às 08:00 BRT e commita `data/jobs.json` quando há mudança.
O painel web (`webapp.py`) é para uso **local** — o Actions roda só o `main.py`.

---

## Como adicionar uma nova fonte (ex.: LinkedIn no futuro)

Crie `src/providers/<fonte>.py` com uma classe que herde de `JobProvider` e
implemente `search(keywords, max_jobs)` devolvendo `JobPosting` normalizado.
Registre em `src/providers/__init__.py` e no `monitor.collect_for_search`. Matcher,
storage e notifier funcionam sem alteração.

---

## Limitações

- **inhire sem busca global:** depende da lista de empresas que você mantiver.
- **Schema do inhire:** o parser é defensivo (tenta várias chaves), mas se o
  inhire mudar muito o formato pode precisar de ajuste em `providers/inhire.py`.
- **Texto em imagens** (banners) não é lido — só o texto das vagas.
```
