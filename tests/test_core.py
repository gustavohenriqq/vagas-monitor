"""Testes do núcleo: parsing dos providers, matcher e senioridade. Sem rede."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.providers.gupy import parse_jobs as gupy_parse
from src.providers.inhire import parse_jobs as inhire_parse, _find_job_list
from src.providers.wwr import parse_feed as wwr_parse
from src.providers.greenhouse import parse_jobs as gh_parse
from src.providers.recrutei import parse_search_html as rec_parse
from src.providers.remotive import parse_jobs as remotive_parse
from src.providers.remoteok import parse_jobs as remoteok_parse
from src.providers.lever import parse_jobs as lever_parse
from src.providers.ashby import parse_jobs as ashby_parse
from src.providers.recruitee import parse_jobs as recruitee_parse
from src.providers.smartrecruiters import parse_jobs as smartr_parse
from src.models import ONSITE
from src.matcher import matches
from src.models import infer_seniority, JobPosting, REMOTE, HYBRID
from src.relevance import classify_title, evaluate, CONF_ALTA, CONF_MEDIA, CONF_BAIXA
from src.searches import SearchProfile


GUPY_PAYLOAD = {
    "data": [
        {"id": 1, "name": "Desenvolvedor Backend Pleno", "description": "<p>Python &nbsp;e Django</p>",
         "careerPageName": "Acme", "jobUrl": "https://acme.gupy.io/job/1",
         "city": "São Paulo", "state": "SP", "country": "Brasil", "workplaceType": "hybrid"},
        {"id": 2, "name": "Estágio em QA", "description": "testes",
         "careerPageName": "Acme", "jobUrl": "https://acme.gupy.io/job/2", "workplaceType": "remote"},
    ],
    "pagination": {"total": 2, "limit": 100, "offset": 0},
}

# Formato real do endpoint público /job-posts/public/pages (observado na Radix).
INHIRE_PAYLOAD = {
    "tenantName": "Radix",
    "jobsPage": [
        {"jobId": "a1", "displayName": "Profissional Cientista de Dados Sênior",
         "status": "published", "workplaceType": "Remote", "location": "BR"},
        {"jobId": "a2", "displayName": "Estágio em Controladoria",
         "status": "published", "workplaceType": "Hybrid", "location": "Rio de Janeiro, RJ, BR"},
        {"jobId": "a3", "displayName": "Vaga em rascunho",
         "status": "draft", "workplaceType": "Remote", "location": "BR"},
    ],
}


def test_gupy_parse_fields():
    jobs = gupy_parse(GUPY_PAYLOAD)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.provider == "gupy"
    assert j.seniority == "pleno"
    assert j.workplace_type == HYBRID
    assert "django" in j.description.lower()
    assert j.stable_id == "gupy:1"


def test_inhire_find_and_parse():
    jobs = inhire_parse(INHIRE_PAYLOAD, "radix")
    assert len(jobs) == 2                        # rascunho (draft) é descartado
    assert jobs[0].company == "Radix"            # vem do tenantName
    assert jobs[0].seniority == "senior"
    assert jobs[0].workplace_type == REMOTE
    assert jobs[0].url == "https://radix.inhire.app/vagas/a1"
    assert jobs[1].seniority == "estagio"
    assert jobs[1].workplace_type == HYBRID
    assert jobs[1].city == "Rio de Janeiro" and jobs[1].state == "RJ"


def test_seniority_inference():
    assert infer_seniority("Vaga Júnior") == "junior"
    assert infer_seniority("Pessoa Desenvolvedora Sênior") == "senior"
    assert infer_seniority("Estágio em Dados") == "estagio"
    assert infer_seniority("Tech Lead de Plataforma") == "lead"
    assert infer_seniority("Desenvolvedor") == "indefinido"


def test_matcher_keyword_and_exclude():
    jobs = gupy_parse(GUPY_PAYLOAD) + inhire_parse(INHIRE_PAYLOAD, "radix")
    prof = SearchProfile(
        name="t", keywords=["desenvolvedor", "python", "dados"],
        exclude_keywords=["estágio"], seniority=["pleno", "senior"],
        workplace_types=["remote", "hybrid"],
    )
    titles = [j.title for j in jobs if matches(j, prof).matched]
    assert "Desenvolvedor Backend Pleno" in titles
    assert "Profissional Cientista de Dados Sênior" in titles
    assert "Estágio em QA" not in titles                # excluído por keyword/senioridade
    assert "Estágio em Controladoria" not in titles     # excluído por keyword


def test_matcher_empty_keywords_accepts_all_non_excluded():
    jobs = gupy_parse(GUPY_PAYLOAD)
    prof = SearchProfile(name="t", keywords=[], exclude_keywords=[])
    assert len(jobs) == len([j for j in jobs if matches(j, prof).matched])


# ---------------------------------------------------------------- 3 níveis + score
def test_classify_title_levels():
    assert classify_title("Desenvolvedor Backend Pleno").level == CONF_ALTA
    assert classify_title("Engenheiro de Dados").level == CONF_ALTA
    assert classify_title("Analista de Dados Júnior").level == CONF_ALTA   # cargo de dados é forte
    # ambíguo sozinho não passa; com qualificador de tech, vira MÉDIA
    assert classify_title("Analista Júnior").passes is False
    assert classify_title("Coordenador de Tecnologia").level == CONF_MEDIA
    # ferramenta sozinha não passa; com cargo junto, passa
    assert classify_title("Power BI").passes is False
    assert classify_title("Analista de Power BI").level in (CONF_MEDIA, CONF_BAIXA)
    # cargo não-tech é rejeitado
    assert classify_title("Analista Financeiro").passes is False
    assert classify_title("Engenheiro de Manutenção HVAC").passes is False


def test_score_prioritizes_remote_strong_role():
    remoto = JobPosting(provider="gupy", external_id="1", title="Engenheiro de Dados Sênior",
                        company="X", url="u", workplace_type=REMOTE)
    presencial = JobPosting(provider="gupy", external_id="2", title="Analista de Dados",
                            company="X", url="u")
    r1, r2 = evaluate(remoto), evaluate(presencial)
    assert r1.passes and r2.passes
    assert r1.score >= 7          # cargo forte + remoto + senioridade => alta prioridade
    assert r1.score > r2.score


def test_precise_matcher_uses_three_levels():
    tech = JobPosting(provider="gupy", external_id="1", title="Desenvolvedor Python",
                      company="X", url="u", workplace_type=REMOTE)
    nao_tech = JobPosting(provider="inhire", external_id="2", title="Engenheiro de Manutenção HVAC",
                          company="Radix", url="u", workplace_type=REMOTE)
    prof = SearchProfile(name="t", precise=True, keywords=[], workplace_types=["remote"])
    assert matches(tech, prof).matched is True
    assert matches(nao_tech, prof).matched is False


# ---------------------------------------------------------------- WWR (RSS)
WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
 <item>
  <title>Acme Corp: Senior Backend Engineer</title>
  <region>Latin America</region>
  <category>Back-End Programming</category>
  <link>https://weworkremotely.com/remote-jobs/acme-senior-backend-engineer</link>
  <description>&lt;p&gt;Python and Go&lt;/p&gt;</description>
  <pubDate>Mon, 18 Aug 2026 10:00:00 +0000</pubDate>
 </item>
 <item>
  <title>Globex: Growth Marketer</title>
  <region>USA Only</region>
  <link>https://weworkremotely.com/remote-jobs/globex-growth</link>
  <description>marketing</description>
 </item>
</channel></rss>"""


def test_wwr_parse_feed():
    jobs = wwr_parse(WWR_RSS)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.provider == "wwr"
    assert j.company == "Acme Corp"
    assert j.title == "Senior Backend Engineer"
    assert j.workplace_type == REMOTE
    assert j.country == "Latin America"
    assert j.url.endswith("acme-senior-backend-engineer")


def test_greenhouse_parse():
    payload = {"jobs": [
        {"id": 101, "title": "Senior Backend Engineer",
         "absolute_url": "https://job-boards.greenhouse.io/coinbase/jobs/101",
         "location": {"name": "Remote - Americas"}, "content": "&lt;p&gt;Go and Python&lt;/p&gt;",
         "updated_at": "2026-08-01T00:00:00Z"},
        {"id": 102, "title": "Office Manager",
         "absolute_url": "https://job-boards.greenhouse.io/coinbase/jobs/102",
         "location": {"name": "New York, NY"}, "content": "admin"},
    ], "meta": {"total": 2}}
    jobs = gh_parse(payload, "coinbase")
    assert len(jobs) == 2
    assert jobs[0].provider == "greenhouse"
    assert jobs[0].workplace_type == REMOTE
    assert jobs[0].stable_id == "greenhouse:coinbase:101"
    assert "go and python" in jobs[0].description.lower()   # HTML desescapado e limpo
    # filtro preciso: engenheiro passa, office manager não
    prof = SearchProfile(name="i", precise=True, providers=["greenhouse"], workplace_types=["remote"],
                         locations=["americas", "anywhere", "latin america"])
    titles = [j.title for j in jobs if matches(j, prof).matched]
    assert "Senior Backend Engineer" in titles
    assert "Office Manager" not in titles


RECRUTEI_HTML = """
<div class="jobs">
  <a href="https://empregos.recrutei.com.br/vaga/digisystem/156191-desenvolvedor-backend-java-senior?has_bot=1">Dev</a>
  <a href="/vaga/thera-consulting/157032-consultor-sap-apo-senior">SAP</a>
  <a href="/vaga/rehva-tech/156945-desenvolvedora-php-laravel">PHP</a>
  <a href="/vaga/rehva-tech/156945-desenvolvedora-php-laravel">PHP dup</a>
</div>
"""


def test_recrutei_global_parse():
    jobs = rec_parse(RECRUTEI_HTML, "remote")
    assert len(jobs) == 3                        # deduplica o link repetido
    by_id = {j.external_id: j for j in jobs}
    dev = by_id["digisystem:156191"]
    assert dev.provider == "recrutei"
    assert dev.workplace_type == REMOTE          # veio de model=remote
    assert dev.company == "Digisystem"
    assert dev.title == "Desenvolvedor Backend Java Senior"
    assert dev.url.endswith("156191-desenvolvedor-backend-java-senior")
    # 3 níveis + remoto: dev/consultor tech passam
    prof = SearchProfile(name="r", precise=True, providers=["recrutei"], workplace_types=["remote"])
    titles = [j.title for j in jobs if matches(j, prof).matched]
    assert "Desenvolvedor Backend Java Senior" in titles


def test_remotive_parse():
    jobs = remotive_parse({"jobs": [
        {"id": 1, "title": "Backend Engineer", "company_name": "Acme",
         "url": "https://remotive.com/x", "candidate_required_location": "Latin America"},
        {"id": 2, "title": "", "company_name": "X", "url": "https://y"},  # sem título -> ignora
    ]})
    assert len(jobs) == 1
    assert jobs[0].provider == "remotive" and jobs[0].workplace_type == REMOTE
    assert jobs[0].company == "Acme"


def test_remoteok_parse_skips_legal():
    jobs = remoteok_parse([
        {"legal": "aviso"},
        {"id": "9", "position": "Data Engineer", "company": "Globex",
         "url": "https://remoteok.com/x", "tags": ["python", "sql"]},
    ])
    assert len(jobs) == 1
    assert jobs[0].title == "Data Engineer" and jobs[0].workplace_type == REMOTE


def test_lever_parse_workplace():
    jobs = lever_parse([
        {"id": "a", "text": "Software Engineer", "hostedUrl": "https://jobs.lever.co/acme/a",
         "categories": {"location": "Remote - Brazil", "team": "Eng"}, "workplaceType": "remote"},
        {"id": "b", "text": "Designer", "hostedUrl": "https://jobs.lever.co/acme/b",
         "categories": {"location": "São Paulo"}, "workplaceType": "on-site"},
    ], "acme")
    assert len(jobs) == 2
    by = {j.title: j for j in jobs}
    assert by["Software Engineer"].workplace_type == REMOTE
    assert by["Designer"].workplace_type == ONSITE
    assert by["Software Engineer"].stable_id == "lever:acme:a"


def test_ashby_parse():
    jobs = ashby_parse({"jobs": [
        {"id": "1", "title": "Data Scientist", "location": "Remote", "isRemote": True,
         "jobUrl": "https://jobs.ashbyhq.com/acme/1"},
    ]}, "acme")
    assert len(jobs) == 1
    assert jobs[0].workplace_type == REMOTE and jobs[0].company == "acme"


def test_recruitee_parse():
    jobs = recruitee_parse({"offers": [
        {"id": 5, "title": "DevOps Engineer", "company_name": "Acme",
         "careers_url": "https://acme.recruitee.com/o/devops", "remote": True, "city": ""},
    ]}, "acme")
    assert len(jobs) == 1
    assert jobs[0].workplace_type == REMOTE and jobs[0].title == "DevOps Engineer"


def test_smartrecruiters_parse():
    jobs = smartr_parse({"content": [
        {"id": "77", "name": "Backend Developer",
         "location": {"city": "", "region": "", "country": "br", "remote": True}},
    ]}, "acme")
    assert len(jobs) == 1
    assert jobs[0].workplace_type == REMOTE
    assert jobs[0].url == "https://jobs.smartrecruiters.com/acme/77"


def test_wwr_international_filter_and_precision():
    jobs = wwr_parse(WWR_RSS)
    prof = SearchProfile(
        name="intl", precise=True, providers=["wwr"], keywords=[],
        workplace_types=["remote"],
        locations=["anywhere", "latin america", "americas"],
    )
    titles = [j.title for j in jobs if matches(j, prof).matched]
    assert "Senior Backend Engineer" in titles   # tech + Latin America
    assert "Growth Marketer" not in titles        # não-tech (e USA Only)


def _smartr_fake_fetch(total: int, chamadas: list):
    """fetch_json falso: devolve páginas de 100 até somar `total` vagas."""
    def fake(session, url, *, params=None, headers=None, delay=1.0):
        offset = params["offset"]
        chamadas.append(offset)
        restante = max(0, total - offset)
        size = min(100, restante)
        return {
            "offset": offset, "limit": 100, "totalFound": total,
            "content": [
                {"id": str(offset + i), "name": f"Backend Developer {offset + i}",
                 "location": {"city": "", "region": "", "country": "br", "remote": True}}
                for i in range(size)
            ],
        }
    return fake


def test_smartrecruiters_paginates_until_total(monkeypatch):
    """Board com 250 vagas exige 3 páginas — antes só a primeira era vista."""
    from src.providers import smartrecruiters as sr

    chamadas: list = []
    monkeypatch.setattr(sr, "fetch_json", _smartr_fake_fetch(250, chamadas))

    jobs = sr.SmartRecruitersProvider(companies=["acme"], delay=0).search([], max_jobs=1000)

    assert chamadas == [0, 100, 200]
    assert len(jobs) == 250
    assert jobs[0].url == "https://jobs.smartrecruiters.com/acme/0"


def test_smartrecruiters_respeita_max_jobs_por_empresa(monkeypatch):
    """Para de paginar ao atingir max_jobs, sem varrer o board inteiro."""
    from src.providers import smartrecruiters as sr

    chamadas: list = []
    monkeypatch.setattr(sr, "fetch_json", _smartr_fake_fetch(5000, chamadas))

    jobs = sr.SmartRecruitersProvider(companies=["acme"], delay=0).search([], max_jobs=150)

    assert chamadas == [0, 100]
    assert len(jobs) == 150


def test_ashby_teto_por_org(monkeypatch):
    """Org com board gigante não pode zerar a cota das orgs seguintes."""
    from src.providers import ashby as ab

    boards = {
        "gigante": {"jobs": [
            {"id": f"g{i}", "title": "Backend Engineer", "jobUrl": f"https://jobs.ashbyhq.com/gigante/g{i}",
             "location": "Remote", "isRemote": True}
            for i in range(500)
        ]},
        "pequena": {"jobs": [
            {"id": "p1", "title": "Data Engineer", "jobUrl": "https://jobs.ashbyhq.com/pequena/p1",
             "location": "Remote", "isRemote": True},
        ]},
    }

    def fake(session, url, *, params=None, headers=None, delay=1.0):
        return boards[url.rstrip("/").rsplit("/", 1)[-1]]

    monkeypatch.setattr(ab, "fetch_json", fake)

    jobs = ab.AshbyProvider(companies=["gigante", "pequena"], delay=0).search([], max_jobs=10)
    empresas = {j.company for j in jobs}

    assert empresas == {"gigante", "pequena"}      # antes: só "gigante"
    assert sum(1 for j in jobs if j.company == "gigante") == 10
