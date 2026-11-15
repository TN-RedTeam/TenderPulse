"""Test d'intégration de l'API multi-tenant sur une vraie base PostgreSQL (BOAMP simulé, aucun réseau).

Ce module est ignoré si la variable TEST_DATABASE_URL n'est pas définie. Exemple :
    TEST_DATABASE_URL=postgresql://tenderpulse:tenderpulse@localhost:5432/tenderpulse_test pytest
ATTENTION : les tables de cette base sont vidées au début du test.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import asyncpg
import httpx
import pytest

from backend.api.main import create_app
from backend.config import load_settings
from tests import boamp_fixtures as fx
from tests.conftest import paginated_boamp_handler

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL non défini : test d'intégration PostgreSQL ignoré"),
]

ADMIN = {"X-API-Key": "cle-admin-de-test"}


def _future_records() -> list[dict]:
    """Les avis simulés, avec des dates limites recalées dans le futur par rapport à l'horloge réelle."""
    from datetime import datetime, timedelta, timezone
    shift = datetime.now(timezone.utc) - fx.NOW
    records = []
    for record in fx.ALL_RECORDS:
        deadline = datetime.fromisoformat(record["datelimitereponse"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        records.append(dict(record, datelimitereponse=(deadline + shift + timedelta(minutes=5)).isoformat()))
    return records


@pytest.fixture
async def api():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    await conn.execute("DROP TABLE IF EXISTS tender_scores, tenders, company_profiles, tenants, collection_runs CASCADE")
    await conn.close()
    settings = replace(load_settings(), database_url=TEST_DATABASE_URL, admin_api_key=ADMIN["X-API-Key"],
                       collect_enabled=False, llm_provider="none", boamp_min_interval_s=0.0, smtp_host="")
    handler = paginated_boamp_handler(_future_records())
    app = create_app(settings, boamp_transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def _wait_for_run(client: httpx.AsyncClient, run_id: int) -> dict:
    for _ in range(100):
        run = (await client.get(f"/api/collect/runs/{run_id}", headers=ADMIN)).json()
        if run["status"] != "en_cours":
            return run
        await asyncio.sleep(0.05)
    raise AssertionError("la collecte ne s'est pas terminée")


async def test_full_multi_tenant_workflow(api: httpx.AsyncClient):
    # --- Authentification
    assert (await api.get("/api/health")).json()["status"] == "ok"
    assert (await api.get("/api/tenants")).status_code == 401
    assert (await api.get("/api/tenants", headers={"X-API-Key": "mauvaise-cle"})).status_code == 401
    assert (await api.get("/api/me", headers=ADMIN)).json() == {"role": "admin", "tenant": None}

    # --- Deux PME clientes
    created = await api.post("/api/tenants", headers=ADMIN, json={"name": "Isol'Rhône SAS", "contact_email": "contact@isolrhone.example"})
    assert created.status_code == 201
    tenant = created.json()
    tenant_key = {"X-API-Key": tenant["api_key"]}
    other = (await api.post("/api/tenants", headers=ADMIN, json={"name": "Élec Provence"})).json()
    other_key = {"X-API-Key": other["api_key"]}
    assert (await api.post("/api/tenants", headers=ADMIN, json={"name": "Isol'Rhône SAS"})).status_code == 409
    assert (await api.get("/api/me", headers=tenant_key)).json()["tenant"]["id"] == tenant["id"]
    assert (await api.get("/api/tenants", headers=tenant_key)).status_code == 403
    assert (await api.post("/api/collect", headers=tenant_key)).status_code == 403

    # --- Profils
    base = f"/api/tenants/{tenant['id']}"
    profile = (await api.post(f"{base}/profiles", headers=tenant_key, json=fx.PROFILE_DATA))
    assert profile.status_code == 201
    profile_id = profile.json()["id"]
    assert profile.json()["departments"] == ["69", "38", "01"]
    assert (await api.post(f"{base}/profiles", headers=tenant_key, json=fx.PROFILE_DATA)).status_code == 409
    assert (await api.post(f"{base}/profiles", headers=tenant_key, json={**fx.PROFILE_DATA, "name": "x", "departments": ["Lyon"]})).status_code == 422
    other_profile = (await api.post(f"/api/tenants/{other['id']}/profiles", headers=other_key, json={
        "name": "Électricité", "keywords_include": ["électricité", "courants forts"], "departments": ["13", "84"]})).json()

    # --- Collecte manuelle (API BOAMP simulée) puis scoring de chaque profil
    started = await api.post("/api/collect", headers=ADMIN, json={})
    assert started.status_code == 202 and started.json()["status"] == "en_cours"
    run = await _wait_for_run(api, started.json()["id"])
    assert run["status"] == "termine", run
    assert run["tenders_fetched"] == 7 and run["tenders_new"] == 7
    assert run["scores_written"] == 4
    assert run["filters"]["departments"] == ["01", "13", "38", "69", "84"]

    # Une seconde collecte ne crée aucun doublon (déduplication par idweb).
    again = await _wait_for_run(api, (await api.post("/api/collect", headers=ADMIN, json={"keywords": ["isolation"]})).json()["id"])
    assert again["status"] == "termine" and again["tenders_new"] == 0 and again["tenders_updated"] == 0
    assert again["filters"]["keywords"] == ["isolation"]
    assert len((await api.get("/api/collect/runs", headers=ADMIN)).json()) == 2

    # --- Opportunités triées par score
    listing = (await api.get(f"{base}/profiles/{profile_id}/opportunities", headers=tenant_key)).json()
    assert listing["total"] == 4
    assert listing["counts"] == {"total": 4, "go": 1, "a_verifier": 0, "no_go": 3, "nouveau": 4}
    scores = [item["score"] for item in listing["items"]]
    assert scores == sorted(scores, reverse=True)
    top = listing["items"][0]
    assert top["idweb"] == "26-200001" and top["decision"] == "go" and top["status"] == "nouveau"
    assert len(top["criteria"]) == 5 and len(top["summary"].splitlines()) == 5 and len(top["lots"]) == 2
    only_go = (await api.get(f"{base}/profiles/{profile_id}/opportunities", headers=tenant_key, params={"decision": "go"})).json()
    assert [item["idweb"] for item in only_go["items"]] == ["26-200001"]
    turnover = next(item for item in listing["items"] if item["idweb"] == "26-200002")
    assert turnover["eliminatory"][0]["type"] == "chiffre_affaires" and turnover["eliminatory"][0]["severity"] == "bloquant"

    # --- Isolation entre clients
    assert (await api.get(f"{base}/profiles", headers=other_key)).status_code == 403
    assert (await api.get(f"{base}/opportunities/{top['id']}", headers=other_key)).status_code == 403
    assert (await api.get(f"/api/tenants/{other['id']}/opportunities/{top['id']}", headers=other_key)).status_code == 404
    assert (await api.get(f"/api/tenants/{other['id']}/profiles/{profile_id}/opportunities", headers=other_key)).status_code == 404
    other_list = (await api.get(f"/api/tenants/{other['id']}/profiles/{other_profile['id']}/opportunities", headers=other_key)).json()
    assert other_list["total"] == 0
    assert (await api.get(f"{base}/profiles", headers=ADMIN)).status_code == 200  # l'opérateur voit tous les clients

    # --- Statut de suivi
    detail = (await api.get(f"{base}/opportunities/{top['id']}", headers=tenant_key)).json()
    assert "Texte de l'avis" in detail["full_text"]
    patched = await api.patch(f"{base}/opportunities/{top['id']}", headers=tenant_key, json={"status": "a_etudier"})
    assert patched.status_code == 200 and patched.json()["status"] == "a_etudier" and patched.json()["status_updated_at"]
    assert (await api.patch(f"{base}/opportunities/{top['id']}", headers=tenant_key, json={"status": "peut-etre"})).status_code == 422
    await api.patch(f"{base}/opportunities/{turnover['id']}", headers=tenant_key, json={"status": "ignore"})
    after = (await api.get(f"{base}/profiles/{profile_id}/opportunities", headers=tenant_key)).json()
    assert after["total"] == 3 and "26-200002" not in [i["idweb"] for i in after["items"]]
    ignored = (await api.get(f"{base}/profiles/{profile_id}/opportunities", headers=tenant_key, params={"status": "ignore"})).json()
    assert [i["idweb"] for i in ignored["items"]] == ["26-200002"]

    # --- Digest HTML
    digest = await api.get(f"{base}/profiles/{profile_id}/digest", headers=tenant_key)
    assert digest.status_code == 200 and digest.headers["content-type"].startswith("text/html")
    assert digest.headers["x-digest-count"] == "1"
    assert "Rénovation énergétique du groupe scolaire Jean Jaurès" in digest.text and "salle polyvalente" not in digest.text
    sent = (await api.post(f"{base}/profiles/{profile_id}/digest/send", headers=tenant_key)).json()
    assert sent["sent"] is False and "SMTP non configuré" in sent["detail"]

    # --- Modification du profil : ré-analyse, statut de suivi conservé
    updated = await api.put(f"{base}/profiles/{profile_id}", headers=tenant_key,
                            json={**fx.PROFILE_DATA, "certifications": ["Qualibat 7131", "RGE", "ISO 14001"], "alert_threshold": 80})
    assert updated.status_code == 200 and updated.json()["alert_threshold"] == 80
    rescored = (await api.post(f"{base}/profiles/{profile_id}/rescore", headers=tenant_key)).json()
    assert rescored == {"tenders_examined": 7, "scores_written": 4}
    final = (await api.get(f"{base}/profiles/{profile_id}/opportunities", headers=tenant_key)).json()
    assert final["counts"]["go"] == 2   # l'avis exigeant l'ISO 14001 devient un « Go »
    assert next(i for i in final["items"] if i["idweb"] == "26-200001")["status"] == "a_etudier"

    # --- Suppressions en cascade
    assert (await api.delete(f"{base}/profiles/{profile_id}", headers=tenant_key)).status_code == 204
    assert (await api.get(f"{base}/opportunities/{top['id']}", headers=tenant_key)).status_code == 404
    assert (await api.delete(f"/api/tenants/{other['id']}", headers=ADMIN)).status_code == 204
    assert (await api.get("/api/me", headers=other_key)).status_code == 401
