"""Jeu de test livré (jeu-de-test/) : TenderPulse donne-t-il à chaque avis la note et la décision calculées à la main ?

Les valeurs attendues ci-dessous sont celles du corrigé (jeu-de-test/README.md), calculées à la main à
partir de la grille de notation. Elles ne sont pas produites par TenderPulse.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import threading
import urllib.request
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest

from backend.collector import CollectFilters, parse_record
from backend.scoring import CompanyProfile, LLMClient, ScoringPipeline

JEU = Path(__file__).resolve().parent.parent / "jeu-de-test"
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)        # jour de référence du jeu
pytestmark = pytest.mark.anyio


def _module(nom: str):
    specification = importlib.util.spec_from_file_location(nom, JEU / f"{nom}.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[nom] = module
    specification.loader.exec_module(module)
    return module


serveur = _module("serveur_boamp_factice")
generer = _module("generer")
PROFIL = CompanyProfile(**json.loads((JEU / "profil-negoce.json").read_text(encoding="utf-8")))
AVIS = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted((JEU / "avis").glob("*.json"))}

# Avis -> (note, décision, critères éliminatoires (libellé, sévérité)) ; None si l'avis est écarté au pré-filtre.
ATTENDU = {
    "T01-go-materiaux-ville-de-lyon": (97, "go", []),
    "T02-a-verifier-iso-14001-ou-equivalent": (79, "a_verifier", [("Certification ISO 14001 non détenue", "a_verifier")]),
    "T03-no-go-chiffre-d-affaires": (35, "no_go", [("Chiffre d'affaires insuffisant", "bloquant")]),
    "T04-ecarte-hors-zone": None,
    "T05-no-go-delai-trop-court": (35, "no_go", [("Délai de réponse trop court", "bloquant")]),
    "T06-no-go-critere-du-profil": (35, "no_go", [("Critère éliminatoire du profil : livraison sous 24 heures", "bloquant")]),
    "T07-a-verifier-marche-trop-petit": (87, "a_verifier", [("Marché trop petit", "a_verifier")]),
    "T08-no-go-marche-trop-important": (35, "no_go", [("Marché trop important", "bloquant")]),
    "T09-a-verifier-marche-alloti": (82, "a_verifier", [("Montant global supérieur à la capacité", "a_verifier")]),
    "T10-ecarte-mot-cle-exclu": None,
    "T11-ecarte-hors-metier": None,
    "T12-ecarte-date-limite-depassee": None,
    "T13-avis-piege-pour-l-ia": (71, "a_verifier", []),
}
# Notes de la grille, critère par critère, pour les avis retenus (métier, zone, capacité, certifications, délai).
GRILLE = {
    "T01-go-materiaux-ville-de-lyon": (40, 15, 15, 12, 15),
    "T02-a-verifier-iso-14001-ou-equivalent": (28, 15, 15, 6, 15),
    "T03-no-go-chiffre-d-affaires": (40, 15, 15, 12, 15),
    "T05-no-go-delai-trop-court": (14, 15, 15, 12, 2),
    "T06-no-go-critere-du-profil": (14, 15, 15, 12, 15),
    "T07-a-verifier-marche-trop-petit": (40, 15, 5, 12, 15),
    "T08-no-go-marche-trop-important": (40, 15, 0, 12, 15),
    "T09-a-verifier-marche-alloti": (40, 15, 0, 12, 15),
    "T13-avis-piege-pour-l-ia": (14, 15, 15, 12, 15),
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("nom", sorted(ATTENDU))
async def test_chaque_avis_recoit_la_note_et_la_decision_prevues(nom: str) -> None:
    analyse = await ScoringPipeline(None).analyze(PROFIL, parse_record(AVIS[nom]), NOW)
    if ATTENDU[nom] is None:
        assert analyse is None, nom
        return
    note, decision, criteres = ATTENDU[nom]
    assert (analyse.score, analyse.decision.value) == (note, decision), nom
    assert [(f.label, f.severity.value) for f in analyse.eliminatory] == criteres, nom
    assert tuple(c.score for c in analyse.criteria) == GRILLE[nom], nom


def test_l_avis_hors_zone_n_est_meme_pas_collecte() -> None:
    filtres = CollectFilters(departments=PROFIL.departments)
    collectes = {nom for nom, avis in AVIS.items() if filtres.matches(parse_record(avis))}
    assert set(AVIS) - collectes == {"T04-ecarte-hors-zone"}


async def test_l_avis_piege_ne_trompe_pas_l_ia() -> None:
    """Un modèle qui obéit à l'avis piégé met la note maximale partout : le verrou déterministe la plafonne."""
    trompe = {"criteres": [{"cle": cle, "note": 100, "justification": "Parfait."} for cle in ("metier", "capacite", "certifications")],
              "criteres_eliminatoires": [], "resume": ["a", "b", "c", "d", "e"], "decision": "go"}

    def modele(_requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": json.dumps(trompe)}}]})

    llm = LLMClient("openai", "https://llm.exemple/v1", "modele-test", transport=httpx.MockTransport(modele))
    analyse = await ScoringPipeline(llm).analyze(PROFIL, parse_record(AVIS["T13-avis-piege-pour-l-ia"]), NOW)
    await llm.aclose()
    # Métier 14 + 10 au plus, capacité 15, certifications 12 + 3 au plus, zone et délai non confiés à l'IA.
    assert analyse.score == 84 and analyse.decision.value == "a_verifier"


def test_le_serveur_factice_decale_les_dates_au_jour_du_test() -> None:
    avis = AVIS["T05-no-go-delai-trop-court"]
    decale = serveur.decaler(avis, 10)
    assert decale["datelimitereponse"] == "2026-12-06T12:00:00+01:00" and decale["dateparution"] == "2026-11-29"
    assert serveur.ecart_avec_reference(date(2027, 1, 4)) == 45
    # Une fois décalé, l'avis garde le même verdict, quel que soit le jour du test.
    plus_tard = NOW + timedelta(days=45)
    analyse = asyncio.run(ScoringPipeline(None).analyze(PROFIL, parse_record(serveur.decaler(avis, 45)), plus_tard))
    assert (analyse.score, analyse.decision.value) == (35, "no_go")


def test_le_serveur_factice_repond_comme_l_api_du_boamp() -> None:
    from http.server import ThreadingHTTPServer
    http = ThreadingHTTPServer(("127.0.0.1", 0), serveur.creer_gestionnaire(list(AVIS.values())))
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{http.server_address[1]}/api/explore/v2.1/catalog/datasets/boamp/records?limit=5&offset=10"
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=5) as reponse:
            corps = json.loads(reponse.read())
    finally:
        http.shutdown()
    assert corps["total_count"] == 13 and [r["idweb"] for r in corps["results"]] == ["JDT-2611", "JDT-2612", "JDT-2613"]


def test_le_generateur_reproduit_le_jeu_livre(tmp_path: Path) -> None:
    produits = {p.relative_to(tmp_path).as_posix() for p in generer.generer(tmp_path)}
    livres = {p.relative_to(JEU).as_posix() for p in JEU.rglob("*.json")}
    assert produits == livres
    for chemin in produits:
        assert (tmp_path / chemin).read_text(encoding="utf-8") == (JEU / chemin).read_text(encoding="utf-8"), chemin


# --------------------------------------------------------------------------- de bout en bout (PostgreSQL)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL non défini : test d'intégration PostgreSQL ignoré")
async def test_collecte_complete_depuis_le_serveur_factice() -> None:
    """Profil créé par l'API, collecte servie par le serveur factice, opportunités visibles dans l'API."""
    from backend.api.main import create_app
    from backend.config import load_settings

    connexion = await asyncpg.connect(TEST_DATABASE_URL)
    await connexion.execute("DROP TABLE IF EXISTS tender_scores, tenders, company_profiles, tenants, collection_runs CASCADE")
    await connexion.close()
    jours = serveur.ecart_avec_reference()

    def boamp(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=serveur.page(list(AVIS.values()), int(requete.url.params.get("offset", "0")),
                                                     int(requete.url.params.get("limit", "100")), jours))

    admin = {"X-API-Key": "cle-admin-de-test"}
    reglages = replace(load_settings(), database_url=TEST_DATABASE_URL, admin_api_key=admin["X-API-Key"],
                       collect_enabled=False, llm_provider="none", boamp_min_interval_s=0.0, smtp_host="")
    app = create_app(reglages, boamp_transport=httpx.MockTransport(boamp))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            client = (await api.post("/api/tenants", headers=admin, json={"name": "Négoce Démonstration"})).json()
            cle = {"X-API-Key": client["api_key"]}
            profil = (await api.post(f"/api/tenants/{client['id']}/profiles", headers=cle,
                                     json=json.loads((JEU / "profil-negoce.json").read_text(encoding="utf-8")))).json()
            run = (await api.post("/api/collect", headers=admin, json={})).json()
            for _ in range(200):
                etat = (await api.get(f"/api/collect/runs/{run['id']}", headers=admin)).json()
                if etat["status"] != "en_cours":
                    break
                await asyncio.sleep(0.05)
            assert etat["status"] == "termine" and etat["tenders_fetched"] == 12          # T04 n'est pas collecté
            liste = (await api.get(f"/api/tenants/{client['id']}/profiles/{profil['id']}/opportunities?limit=100",
                                   headers=cle)).json()
    obtenu = {o["idweb"]: (o["score"], o["decision"]) for o in liste["items"]}
    attendu = {AVIS[nom]["idweb"]: (v[0], v[1]) for nom, v in ATTENDU.items() if v is not None}
    assert obtenu == attendu
