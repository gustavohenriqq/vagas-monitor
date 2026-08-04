"""Testes do núcleo: parsing dos providers, matcher e senioridade. Sem rede."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.providers.gupy import parse_jobs as gupy_parse
from src.providers.inhire import parse_jobs as inhire_parse, _find_job_list
from src.matcher import matches
from src.models import infer_seniority, REMOTE, HYBRID
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
