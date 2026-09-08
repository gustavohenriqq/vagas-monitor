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
    # "Analista de BI" sempre foi ALTA; acrescentar "Power" ao título não pode
    # rebaixar a confiança, que era o que a regra antiga fazia.
    assert classify_title("Analista de Power BI").level == CONF_ALTA
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


def test_dashboard_payload():
    """Payload do painel: campos curtos, ordem por data e contagem de notificadas."""
    from src.dashboard import build_payload
    from src.storage import JobRecord

    def rec(sid, titulo, score, status, quando, provider="lever"):
        job = JobPosting(provider=provider, external_id=sid, title=titulo, company="Acme",
                         url=f"https://x/{sid}", city="Belo Horizonte", state="MG",
                         workplace_type=REMOTE)
        return JobRecord(stable_id=f"{provider}:{sid}", job=job, first_seen_at=quando,
                         last_seen_at=quando, notification_status=status, score=score,
                         confidence="alta", profile="brasil", matched_searches=["Tech"])

    history = {
        "a": rec("1", "Engenheiro de Dados", 9, "sent", "2026-09-01T10:00:00+00:00"),
        "b": rec("2", "Analista de BI", 6, "digest", "2026-09-03T10:00:00+00:00"),
        "c": rec("3", "Suporte", 0, "skipped", "2026-09-02T10:00:00+00:00", provider="gupy"),
    }
    p = build_payload(history)

    assert p["total"] == 3
    assert p["notificadas"] == 2                      # sent + digest, nunca skipped
    assert [v["t"] for v in p["vagas"]] == ["Analista de BI", "Suporte", "Engenheiro de Dados"]
    assert p["agregados"]["provider"] == {"lever": 2, "gupy": 1}
    assert p["agregados"]["status"] == {"sent": 1, "digest": 1, "skipped": 1}
    assert p["agregados"]["score"]["9"] == 1

    primeira = p["vagas"][0]
    assert primeira["l"] == "Belo Horizonte, MG"      # local montado sem campos vazios
    assert primeira["u"] == "https://x/2" and primeira["st"] == "digest"


def test_rescore_so_mexe_no_legado():
    """Repontua registro sem confiança e não encosta no resto."""
    from src.rescore import rescore
    from src.storage import JobRecord

    def rec(sid, titulo, score, conf, status):
        job = JobPosting(provider="gupy", external_id=sid, title=titulo, company="Acme",
                         url=f"https://x/{sid}", workplace_type=REMOTE, seniority="senior")
        return JobRecord(stable_id=f"gupy:{sid}", job=job, first_seen_at="2026-08-05T10:00:00+00:00",
                         last_seen_at="2026-08-05T10:00:00+00:00", notification_status=status,
                         score=score, confidence=conf)

    history = {
        "legado": rec("1", "Engenheiro de Dados Sênior", 0, "", "sent"),
        "legado_nao_tech": rec("2", "Auxiliar de Limpeza", 0, "", "skipped"),
        "atual": rec("3", "Desenvolvedor Python", 9, "alta", "sent"),
    }
    resumo = rescore(history)

    assert resumo["legados"] == 2 and resumo["intactos"] == 1
    # o legado de tech ganha score e confiança de verdade
    assert history["legado"].score >= 7 and history["legado"].confidence == "alta"
    # o que não é tech fica em 0, mas agora marcado como "nenhum", não vazio
    assert history["legado_nao_tech"].score == 0
    assert history["legado_nao_tech"].confidence == "nenhum"
    # registro já pontuado não é tocado, e nenhum status muda
    assert history["atual"].score == 9 and history["atual"].confidence == "alta"
    assert [r.notification_status for r in history.values()] == ["sent", "skipped", "sent"]


def test_exclude_locations_barra_pais_e_poupa_local_generico():
    """Local de fora é barrado; local vazio ou genérico continua passando."""
    prof = SearchProfile(name="br", precise=True, keywords=[], workplace_types=["remote"],
                         exclude_locations=["united states", "san francisco", "singapore"])

    def vaga(city="", country=""):
        return JobPosting(provider="ashby", external_id="1", title="Backend Engineer",
                          company="Acme", url="u", city=city, country=country,
                          workplace_type=REMOTE)

    assert matches(vaga(city="San Francisco"), prof).matched is False
    assert matches(vaga(city="Remote - United States"), prof).matched is False
    assert matches(vaga(city="Asia", country="SG"), prof).matched is True   # "SG" não está na lista
    assert matches(vaga(city="Singapore"), prof).matched is False
    # o que interessa preservar: sem local e local genérico seguem valendo
    assert matches(vaga(), prof).matched is True
    assert matches(vaga(city="Remote"), prof).matched is True
    assert matches(vaga(city="São Paulo, Brasil"), prof).matched is True


def test_exclude_locations_tem_prioridade_sobre_locations():
    """Mesmo casando a lista de inclusão, local excluído não passa."""
    prof = SearchProfile(name="bh", precise=True, keywords=[], workplace_types=["remote"],
                         locations=["belo horizonte"], exclude_locations=["united states"])
    fora = JobPosting(provider="lever", external_id="2", title="Data Engineer", company="Acme",
                      url="u", city="Belo Horizonte", country="United States", workplace_type=REMOTE)
    dentro = JobPosting(provider="lever", external_id="3", title="Data Engineer", company="Acme",
                        url="u", city="Belo Horizonte", country="Brasil", workplace_type=REMOTE)
    assert matches(fora, prof).matched is False
    assert matches(dentro, prof).matched is True


def test_regiao_classifica_pelo_local():
    """Região sai do local da vaga, não do perfil da busca que casou."""
    from src.dashboard import regiao

    assert regiao("Belo Horizonte", "MG", "Brasil") == "brasil"
    assert regiao("", "", "BR") == "brasil"          # código de país
    assert regiao("Remoto", "", "BR") == "brasil"
    assert regiao("Bogotá", "", "CO") == "latam"
    assert regiao("Santa Cruz", "", "Bolivia") == "latam"

    # país de fora vence o genérico: "Remote - USA" não é vaga sem país
    assert regiao("Remote - USA", "", "") == "outros"
    assert regiao("Remote U.S.", "", "") == "outros"
    assert regiao("San Francisco", "California", "") == "outros"
    assert regiao("Asia", "", "SG") == "outros"

    # sem país declarado fica num balde próprio: pode aceitar o Brasil
    assert regiao("", "", "") == "sem_pais"
    assert regiao("Remote", "", "") == "sem_pais"
    assert regiao("Anywhere in the World", "", "") == "sem_pais"

    # "us" não pode casar dentro de outra palavra
    assert regiao("Belarus", "", "") == "outros"     # cai no default, não por "us"
    from src.dashboard import _RE_EUA
    from src.models import normalize
    assert not _RE_EUA.search(normalize("Belarus"))
    assert not _RE_EUA.search(normalize("Business Analyst"))


def test_vocabulario_cobre_espanhol_e_abreviacoes():
    """Lacunas reais achadas no histórico: espanhol, 'dev', formas nominais."""
    aprovados = [
        "Ingeniero de Datos",
        "Desarrollador Java - Microservicios",
        "Ingeniero de Software Senior",
        "Dev Back Java Pleno",
        ".NET DEV - PLENO",
        "Analytics Engineer Sênior",
        "Tech Leader Mobile",
        "Mobile Engineer - IOS",
        "CAS | Engenharia de Software SR",
        "Profissional de Ciência de Dados Sênior",
        "Profissional de Desenvolvimento de Software Pleno",
        "CIENTISTA DADOS SR",
        "SR Data Architect",
        "BUSINESS INTELLIGENCE SENIOR",
        "Profissional Testador de Software Pleno",
        "ADMINISTRADOR BANCO DADOS SR",
    ]
    for titulo in aprovados:
        assert classify_title(titulo).passes, f"deveria passar: {titulo}"


def test_vocabulario_nao_abre_a_porta_para_nao_tech():
    """O risco de ampliar vocabulário é justamente este — trava aqui."""
    rejeitados = [
        "Médica Ginecologista e Obstetra",
        "Vendedor LATAM Remoto",
        "SDR LATAM Remoto",
        "Supervisor de Desenvolvimento de Mercado Sênior",
        "Analista de Growth e Performance Sênior",
        "Profissional Desenvolvimento de Negócios",
        "Auxiliar de Limpeza",
        "Enfermeiro Plantonista",
        "Assistente Administrativo",
        "Analista de Recursos Humanos Pleno",
        "Gerente Comercial",
        "Consultor de Vendas",
        "Analista Financeiro Sênior",
        "Professor de Matemática",
    ]
    for titulo in rejeitados:
        assert not classify_title(titulo).passes, f"não deveria passar: {titulo}"


def test_dev_nao_casa_dentro_de_development():
    """'dev' entrou como cargo; a fronteira de palavra é o que o torna seguro."""
    assert classify_title("Dev .NET SR").passes
    assert not classify_title("Business Development Representative").passes
    assert not classify_title("Development Manager - Comercial").passes


def test_variantes_do_mesmo_cargo_caem_no_mesmo_nivel():
    """A equivalência é regra, não lista: mesma função, mesmo nível."""
    equivalentes = [
        ("Tech Lead", "Tech Leader"),
        ("Engenheiro de Banco de Dados", "ADMINISTRADOR BANCO DADOS SR"),
        ("Desenvolvedor Java", "Desenvolvedora Java"),
        ("Cientista de Dados", "CIENTISTA DADOS SR"),
        ("Ingeniero de Datos", "Ingeniera de Datos"),
        ("Arquiteto de Soluções", "Pessoa Arquiteta de Soluções e Software"),
        ("Analista de Sistemas", "Analista Sistemas"),
    ]
    for a, b in equivalentes:
        assert classify_title(a).level == classify_title(b).level, f"{a} != {b}"


def test_canon_ignora_conectivos():
    """'de/da/do' não mudam o cargo, então não podem mudar a comparação."""
    from src.relevance import canon
    assert canon("Engenheiro de Banco de Dados") == "engenheiro banco dados"
    assert canon("ADMINISTRADOR  BANCO   DADOS") == "administrador banco dados"
    assert canon("Analista de Dados") == canon("Analista Dados")


def test_sufixo_curinga_cobre_genero_e_plural():
    """'desenvolvedor*' resolve o que exigia uma entrada por variação."""
    for t in ["Desenvolvedor Python", "Desenvolvedora Python",
              "Desenvolvedores Python", "Engenheira de Dados"]:
        assert classify_title(t).passes, t


def test_cargo_forte_vence_contexto_de_outra_area():
    """Vaga de tech dentro de outra área do negócio continua sendo de tech."""
    assert classify_title("Dev Backend Java Pleno - Segmento Financeiro").passes
    assert classify_title("Data Analyst Pleno - Marketing").passes
    assert classify_title("Pessoa Desenvolvedora Fullstack (Venda Direta)").passes
    assert classify_title("Analista de People Analytics II").passes
    # já sem cargo forte, o contexto veta
    assert not classify_title("Consultor de Vendas de Software").passes
    assert not classify_title("Coordenador de Desenvolvimento Comercial").passes
    assert not classify_title("Analista Recursos Humanos III").passes


# ---------------------------------------------------------------- Workday
WORKDAY_PAYLOAD = {
    "total": 2,
    "jobPostings": [
        {"title": "Senior Machine Learning Engineer", "externalPath": "/job/Porto-Alegre/ML-Eng_JR1",
         "locationsText": "Porto Alegre, Rio Grande do Sul, Brazil",
         "postedOn": "Posted 3 Days Ago", "bulletFields": ["JR1"]},
        {"title": "Software Engineer", "externalPath": "/job/Multi/SW_JR2",
         "locationsText": "6 Locations", "postedOn": "Posted Today", "bulletFields": ["JR2"]},
    ],
}


def test_workday_parse():
    from src.providers.workday import parse_jobs
    from datetime import date, timedelta

    jobs = parse_jobs(WORKDAY_PAYLOAD, "hp.wd5.myworkdayjobs.com", "ExternalCareerSite", "HP")
    assert len(jobs) == 2
    a, b = jobs
    assert a.company == "HP" and a.stable_id == "workday:HP:JR1"
    assert a.url == "https://hp.wd5.myworkdayjobs.com/ExternalCareerSite/job/Porto-Alegre/ML-Eng_JR1"
    assert a.city == "Porto Alegre, Rio Grande do Sul, Brazil"
    assert a.published_date == (date.today() - timedelta(days=3)).isoformat()
    # "6 Locations" não é um local: some, senão viraria texto lixo no painel
    assert b.city == ""
    assert b.published_date == date.today().isoformat()
    # o Workday não informa modelo de trabalho em lugar nenhum
    assert a.workplace_type == "unknown" and b.workplace_type == "unknown"


def test_workday_detalhe_sobrescreve_local_e_data():
    """O detalhe traz local completo e startDate real; a listagem, não."""
    from src.providers.workday import parse_jobs, aplica_detalhe

    job = parse_jobs(WORKDAY_PAYLOAD, "h", "s", "HP")[1]   # o de "6 Locations"
    assert job.city == ""
    aplica_detalhe(job, {
        "location": "Porto Alegre, Rio Grande do Sul, Brazil",
        "country": {"descriptor": "Brazil"},
        "startDate": "2026-08-28",
    })
    assert job.city == "Porto Alegre, Rio Grande do Sul, Brazil"
    assert job.country == "Brazil"
    assert job.published_date == "2026-08-28"


def test_workday_entrada_malformada_e_ignorada():
    """Config errada não pode derrubar a execução."""
    from src.providers.workday import _partes
    assert _partes("host|tenant|site|HP") == ("host", "tenant", "site", "HP")
    assert _partes("host|tenant|site")[3] == "tenant"       # nome cai no tenant
    assert _partes("host|tenant") is None
    assert _partes("") is None


def test_workday_remoto_so_quando_o_local_diz():
    from src.providers.workday import _modelo
    assert _modelo("Remote - Brazil") == REMOTE
    assert _modelo("Brazil - Remoto") == REMOTE
    assert _modelo("Porto Alegre, Brazil") == "unknown"
    assert _modelo("") == "unknown"


def test_workday_busca_pelo_pais_e_nao_por_cargo():
    """O searchText do Workday casa com o local. Buscar por cargo devolve o
    mundo inteiro e o Brasil não cabe no teto de páginas — medido: 282 vagas
    e zero brasileiras. Buscar pelo país traz o recorte certo."""
    from src.providers.workday import TERMOS_PADRAO
    assert TERMOS_PADRAO == ("Brazil", "Brasil")


# ---------------------------------------------------------------- execução silenciosa
def _cfg(**kw):
    from src.config import Config
    base = dict(silent_run=False, initial_notify=False, high_score_threshold=7)
    base.update(kw)
    return Config(**base)


def test_decide_destino_normal():
    """Fora do modo silencioso: score alto notifica na hora, o resto vai pro digest."""
    from src.monitor import decide_destino
    c = _cfg()
    assert decide_destino(is_first_run=False, config=c, score=9) == "sent"
    assert decide_destino(is_first_run=False, config=c, score=7) == "sent"
    assert decide_destino(is_first_run=False, config=c, score=6) == "digest"


def test_decide_destino_silencioso_nao_notifica_nada():
    """SILENT_RUN grava no histórico sem mandar nada — nem alerta, nem digest."""
    from src.monitor import decide_destino
    c = _cfg(silent_run=True)
    for score in (0, 6, 7, 10):
        assert decide_destino(is_first_run=False, config=c, score=score) == "skipped"
    # e continua calado mesmo com initial_notify pedido
    c2 = _cfg(silent_run=True, initial_notify=True)
    assert decide_destino(is_first_run=True, config=c2, score=10) == "skipped"


def test_decide_destino_primeira_execucao():
    """Histórico vazio não dispara enxurrada, a menos que peçam."""
    from src.monitor import decide_destino
    assert decide_destino(is_first_run=True, config=_cfg(), score=10) == "skipped"
    assert decide_destino(is_first_run=True, config=_cfg(initial_notify=True), score=10) == "sent"
