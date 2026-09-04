"""
webapp.py — Painel web local para configurar buscas e testar/ver vagas.

Rodar:
    python -m src.webapp
    # abre em http://localhost:5000

Funcionalidades:
- Listar / criar / editar / excluir buscas (searches.yaml)
- Gerenciar a lista de empresas (tenants) do inhire
- Testar uma busca ao vivo (preview, sem gravar nem notificar)
- Rodar o monitor agora (grava histórico + notifica)
- Ver as vagas já armazenadas

É um app single-user local — sem autenticação. Não exponha na internet.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.config import load_config
    from src.matcher import matches
    from src.monitor import run, setup_logging, collect_for_search
    from src.providers import GupyProvider, InhireProvider, WwrProvider, GreenhouseProvider, build_session
    from src.searches import SearchProfile, SearchesFile, load_searches, save_searches, VALID_PROVIDERS, VALID_SENIORITY, VALID_WORKPLACE
    from src.storage import load_history
else:
    from .config import load_config
    from .matcher import matches
    from .monitor import run, setup_logging, collect_for_search
    from .providers import GupyProvider, InhireProvider, WwrProvider, GreenhouseProvider, build_session
    from .searches import SearchProfile, SearchesFile, load_searches, save_searches, VALID_PROVIDERS, VALID_SENIORITY, VALID_WORKPLACE
    from .storage import load_history

from flask import Flask, redirect, render_template_string, request, url_for

app = Flask(__name__)
CONFIG = load_config()
setup_logging(CONFIG.log_level)


def _searches_path() -> Path:
    return Path(CONFIG.searches_path)


def _split(value: str) -> list[str]:
    return [v.strip() for v in (value or "").replace("\n", ",").split(",") if v.strip()]


PAGE = """
<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vagas Monitor</title>
<style>
 :root{--bg:#0f1420;--card:#1a2130;--line:#2a3547;--fg:#e7edf5;--mut:#94a3b8;--acc:#3b82f6;--ok:#22c55e;--warn:#f59e0b}
 *{box-sizing:border-box} body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
 header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px;flex-wrap:wrap}
 h1{font-size:18px;margin:0} a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
 .wrap{max-width:960px;margin:0 auto;padding:24px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
 .row{display:flex;gap:12px;flex-wrap:wrap} .row>div{flex:1;min-width:180px}
 label{display:block;font-size:12px;color:var(--mut);margin:8px 0 4px}
 input,select,textarea{width:100%;padding:9px;border-radius:8px;border:1px solid var(--line);background:#0d1320;color:var(--fg);font-size:14px}
 textarea{min-height:56px;resize:vertical}
 .btn{display:inline-block;padding:9px 16px;border-radius:8px;border:1px solid var(--line);background:var(--acc);color:#fff;cursor:pointer;font-size:14px}
 .btn.sec{background:transparent;color:var(--fg)} .btn.danger{background:#ef4444} .btn.ok{background:var(--ok)}
 .tag{display:inline-block;padding:2px 8px;border-radius:999px;background:#0d1320;border:1px solid var(--line);font-size:12px;color:var(--mut);margin:2px}
 .muted{color:var(--mut);font-size:13px} .between{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
 .job{border-top:1px solid var(--line);padding:12px 0} .job:first-child{border-top:none}
 .pill{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
 .off{opacity:.55}
</style></head><body>
<header>
 <h1>🧭 Vagas Monitor</h1>
 <a href="{{ url_for('index') }}">Buscas</a>
 <a href="{{ url_for('companies') }}">Empresas inhire</a>
 <a href="{{ url_for('stored') }}">Vagas salvas</a>
 <form method="post" action="{{ url_for('run_now') }}" style="margin-left:auto">
   <button class="btn ok" onclick="return confirm('Rodar o monitor agora? Isso grava o histórico e envia notificações.')">▶ Rodar monitor agora</button>
 </form>
</header>
<div class="wrap">{{ body|safe }}</div>
</body></html>
"""


def render(body: str, **kw):
    return render_template_string(PAGE, body=render_template_string(body, **kw))


# ---------------------------------------------------------------- Buscas
INDEX_BODY = """
{% if msg %}<div class="card" style="border-color:var(--ok)">{{ msg }}</div>{% endif %}
<div class="between"><h2>Buscas configuradas</h2><a class="btn" href="{{ url_for('new_search') }}">+ Nova busca</a></div>
{% for s in searches %}
 <div class="card {{ '' if s.enabled else 'off' }}">
  <div class="between">
   <div><strong>{{ s.name }}</strong>
     <span class="pill">{{ 'ativa' if s.enabled else 'desativada' }}</span>
     {% for p in s.providers %}<span class="pill">{{ p }}</span>{% endfor %}
   </div>
   <div>
     <a class="btn sec" href="{{ url_for('edit_search', idx=loop.index0) }}">Editar</a>
     <a class="btn sec" href="{{ url_for('preview', idx=loop.index0) }}">Testar</a>
     <form method="post" action="{{ url_for('delete_search', idx=loop.index0) }}" style="display:inline">
       <button class="btn danger" onclick="return confirm('Excluir a busca {{ s.name }}?')">Excluir</button>
     </form>
   </div>
  </div>
  <div class="muted" style="margin-top:8px">
   Palavras: {% for k in s.keywords %}<span class="tag">{{ k }}</span>{% endfor %}{% if not s.keywords %}(qualquer){% endif %}
   {% if s.exclude_keywords %}<br>Excluir: {% for k in s.exclude_keywords %}<span class="tag">{{ k }}</span>{% endfor %}{% endif %}
   <br>Senioridade: {{ s.seniority|join(', ') or 'qualquer' }} · Local: {{ s.workplace_types|join(', ') or 'qualquer' }}
   {% if s.locations %}· Regiões: {{ s.locations|join(', ') }}{% endif %}
  </div>
 </div>
{% else %}
 <div class="card muted">Nenhuma busca ainda. Crie a primeira.</div>
{% endfor %}
"""


@app.route("/")
def index():
    data = load_searches(_searches_path())
    return render(INDEX_BODY, searches=data.searches, msg=request.args.get("msg"))


FORM_BODY = """
<div class="between"><h2>{{ 'Editar busca' if idx is not none else 'Nova busca' }}</h2>
 <a class="btn sec" href="{{ url_for('index') }}">Voltar</a></div>
<form method="post" class="card">
 <label>Nome</label><input name="name" value="{{ s.name }}" required>
 <div class="row">
  <div><label>Ativa?</label>
   <select name="enabled"><option value="1" {{ 'selected' if s.enabled }}>Sim</option>
   <option value="0" {{ 'selected' if not s.enabled }}>Não</option></select></div>
  <div><label>Fontes (providers)</label>
   <select name="providers" multiple size="2">
    {% for p in valid_providers %}<option value="{{ p }}" {{ 'selected' if p in s.providers }}>{{ p }}</option>{% endfor %}
   </select></div>
 </div>
 <label>Palavras-chave (separe por vírgula) — casa QUALQUER uma; vazio = tudo</label>
 <textarea name="keywords">{{ s.keywords|join(', ') }}</textarea>
 <label>Excluir se contiver (vírgula)</label>
 <textarea name="exclude_keywords">{{ s.exclude_keywords|join(', ') }}</textarea>
 <div class="row">
  <div><label>Senioridade (vazio = qualquer)</label>
   <select name="seniority" multiple size="6">
    {% for v in valid_seniority %}<option value="{{ v }}" {{ 'selected' if v in s.seniority }}>{{ v }}</option>{% endfor %}
   </select></div>
  <div><label>Tipo de local (vazio = qualquer)</label>
   <select name="workplace_types" multiple size="6">
    {% for v in valid_workplace %}<option value="{{ v }}" {{ 'selected' if v in s.workplace_types }}>{{ v }}</option>{% endfor %}
   </select></div>
 </div>
 <label>Regiões/cidades (vírgula; vazio = qualquer)</label>
 <textarea name="locations">{{ s.locations|join(', ') }}</textarea>
 <div style="margin-top:14px"><button class="btn">Salvar</button></div>
</form>
"""


def _render_form(s: SearchProfile, idx):
    return render(FORM_BODY, s=s, idx=idx,
                  valid_providers=VALID_PROVIDERS, valid_seniority=VALID_SENIORITY, valid_workplace=VALID_WORKPLACE)


def _form_to_profile() -> SearchProfile:
    f = request.form
    return SearchProfile(
        name=f.get("name", "").strip() or "sem-nome",
        enabled=f.get("enabled", "1") == "1",
        providers=f.getlist("providers") or list(VALID_PROVIDERS),
        keywords=_split(f.get("keywords", "")),
        exclude_keywords=_split(f.get("exclude_keywords", "")),
        seniority=f.getlist("seniority"),
        workplace_types=f.getlist("workplace_types"),
        locations=_split(f.get("locations", "")),
    )


@app.route("/search/new", methods=["GET", "POST"])
def new_search():
    if request.method == "POST":
        data = load_searches(_searches_path())
        data.searches.append(_form_to_profile())
        save_searches(data, _searches_path())
        return redirect(url_for("index", msg="Busca criada."))
    return _render_form(SearchProfile(name="", providers=list(VALID_PROVIDERS)), None)


@app.route("/search/<int:idx>/edit", methods=["GET", "POST"])
def edit_search(idx: int):
    data = load_searches(_searches_path())
    if idx < 0 or idx >= len(data.searches):
        return redirect(url_for("index", msg="Busca inexistente."))
    if request.method == "POST":
        data.searches[idx] = _form_to_profile()
        save_searches(data, _searches_path())
        return redirect(url_for("index", msg="Busca atualizada."))
    return _render_form(data.searches[idx], idx)


@app.route("/search/<int:idx>/delete", methods=["POST"])
def delete_search(idx: int):
    data = load_searches(_searches_path())
    if 0 <= idx < len(data.searches):
        removed = data.searches.pop(idx)
        save_searches(data, _searches_path())
        return redirect(url_for("index", msg=f"Busca '{removed.name}' excluída."))
    return redirect(url_for("index"))


# ---------------------------------------------------------------- Empresas inhire
COMPANIES_BODY = """
{% if msg %}<div class="card" style="border-color:var(--ok)">{{ msg }}</div>{% endif %}
<div class="between"><h2>Empresas (tenants) do inhire</h2><a class="btn sec" href="{{ url_for('index') }}">Voltar</a></div>
<div class="card muted">O inhire não tem busca global. Liste aqui as empresas — o tenant é o início do link do portal,
 ex.: <strong>programmers</strong>.inhire.app. O monitor consulta cada uma e filtra pela palavra-chave da busca.</div>
<form method="post" class="card">
 <label>Uma empresa por linha (ou separadas por vírgula)</label>
 <textarea name="companies" style="min-height:160px">{{ companies|join('\n') }}</textarea>
 <div style="margin-top:12px"><button class="btn">Salvar empresas</button></div>
</form>
"""


@app.route("/companies", methods=["GET", "POST"])
def companies():
    data = load_searches(_searches_path())
    if request.method == "POST":
        data.inhire_companies = [c.lower() for c in _split(request.form.get("companies", ""))]
        save_searches(data, _searches_path())
        return redirect(url_for("companies", msg="Empresas atualizadas."))
    return render(COMPANIES_BODY, companies=data.inhire_companies, msg=request.args.get("msg"))


# ---------------------------------------------------------------- Preview ao vivo
PREVIEW_BODY = """
<div class="between"><h2>Teste: {{ name }}</h2><a class="btn sec" href="{{ url_for('index') }}">Voltar</a></div>
<div class="card muted">Prévia ao vivo — {{ jobs|length }} vaga(s) casaram com o filtro. Nada é gravado nem notificado.</div>
{% for j in jobs %}
 <div class="card job">
  <div class="between"><strong>{{ j.title }}</strong>
   <span class="pill">{{ j.provider }}</span></div>
  <div class="muted">{{ j.company or 'empresa não informada' }} · {{ j.location_label }}
   {% if j.seniority != 'indefinido' %}· {{ j.seniority }}{% endif %}</div>
  <div style="margin-top:6px"><a href="{{ j.url }}" target="_blank">Abrir vaga ↗</a></div>
 </div>
{% else %}<div class="card muted">Nenhuma vaga casou. Ajuste as palavras-chave/filtros.</div>{% endfor %}
"""


@app.route("/search/<int:idx>/preview")
def preview(idx: int):
    data = load_searches(_searches_path())
    if idx < 0 or idx >= len(data.searches):
        return redirect(url_for("index", msg="Busca inexistente."))
    profile = data.searches[idx]
    session = build_session()
    gupy = GupyProvider(session=session, delay=CONFIG.request_delay_seconds)
    inhire = InhireProvider(tenants=data.inhire_companies, session=session, delay=CONFIG.request_delay_seconds)
    wwr = WwrProvider(session=session, delay=CONFIG.request_delay_seconds)
    greenhouse = GreenhouseProvider(tokens=data.greenhouse_companies, session=session, delay=CONFIG.request_delay_seconds)
    try:
        jobs = collect_for_search(profile, gupy=gupy, inhire=inhire, wwr=wwr, greenhouse=greenhouse,
                                  max_jobs=min(CONFIG.max_jobs_per_search, 60),
                                  inhire_companies=data.inhire_companies,
                                  greenhouse_companies=data.greenhouse_companies)
    finally:
        gupy.close(); inhire.close(); wwr.close(); greenhouse.close()
    return render(PREVIEW_BODY, name=profile.name, jobs=jobs)


# ---------------------------------------------------------------- Vagas salvas
STORED_BODY = """
<div class="between"><h2>Vagas salvas ({{ records|length }})</h2><a class="btn sec" href="{{ url_for('index') }}">Voltar</a></div>
{% for r in records %}
 <div class="card job">
  <div class="between"><strong>{{ r.job.title }}</strong>
   <span class="pill">{{ r.job.provider }}</span></div>
  <div class="muted">{{ r.job.company }} · {{ r.job.location_label }} · visto em {{ r.first_seen_at[:10] }}
   · <span class="pill">{{ r.notification_status }}</span></div>
  <div style="margin-top:6px"><a href="{{ r.job.url }}" target="_blank">Abrir vaga ↗</a></div>
 </div>
{% else %}<div class="card muted">Nenhuma vaga no histórico ainda. Rode o monitor.</div>{% endfor %}
"""


@app.route("/stored")
def stored():
    history = load_history(Path(CONFIG.storage_path))
    records = sorted(history.values(), key=lambda r: r.first_seen_at, reverse=True)
    return render(STORED_BODY, records=records)


@app.route("/run", methods=["POST"])
def run_now():
    result = run(CONFIG, load_searches(_searches_path()))
    return redirect(url_for("index", msg=f"Monitor executado: {result['new']} vaga(s) nova(s)."))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
