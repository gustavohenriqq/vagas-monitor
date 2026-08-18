"""Testes do núcleo: parsing dos providers, matcher e senioridade. Sem rede."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.providers.gupy import parse_jobs as gupy_parse
from src.providers.inhire import parse_jobs as inhire_parse, _find_job_list
from src.providers.wwr import parse_feed as wwr_parse
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
