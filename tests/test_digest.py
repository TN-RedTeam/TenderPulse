"""Digest quotidien : sélection par seuil et rendu HTML prêt pour l'e-mail."""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.api.digest import digest_subject, render_digest, select_digest_items
from backend.scoring import ScoringPipeline
from tests import boamp_fixtures as fx

pytestmark = pytest.mark.anyio
NOW = fx.NOW


@pytest.fixture
async def candidates(profile, tenders):
    """Lignes telles que renvoyées par la base : avis + analyse, pour chaque avis retenu par le pipeline."""
    rows = []
    for tender in tenders.values():
        analysis = await ScoringPipeline().analyze(profile, tender, NOW)
        if analysis is None:
            continue
        rows.append({
            "idweb": tender.idweb, "objet": tender.objet, "acheteur": tender.acheteur, "departments": tender.departments,
            "url_avis": tender.url_avis, "score": analysis.score, "decision": analysis.decision.value,
            "eliminatory": [f.model_dump(mode="json") for f in analysis.eliminatory], "summary": analysis.summary,
            "date_limite": analysis.date_limite, "budget_estime": analysis.budget_estime, "status": "nouveau",
        })
    return rows


async def test_only_opportunities_above_threshold_are_selected(candidates, profile):
    assert len(candidates) == 4
    selected = select_digest_items(candidates, profile.alert_threshold, NOW)
    assert [item["idweb"] for item in selected] == ["26-200001"]
    assert all(item["score"] >= profile.alert_threshold for item in selected)


async def test_lower_threshold_includes_more_and_sorts_by_score(candidates):
    selected = select_digest_items(candidates, 20, NOW)
    scores = [item["score"] for item in selected]
    assert len(selected) == 4 and scores == sorted(scores, reverse=True)


async def test_ignored_and_expired_opportunities_are_left_out(candidates):
    candidates[0]["status"] = "ignore"
    candidates[1]["date_limite"] = NOW - timedelta(hours=1)
    kept = {item["idweb"] for item in select_digest_items(candidates, 0, NOW)}
    assert kept == {"26-200003", "26-200007"}


async def test_digest_html_is_email_ready(candidates, profile):
    html, count = render_digest(
        tenant_name="Isol'Rhône SAS", profile_name=profile.name, threshold=profile.alert_threshold,
        candidates=candidates, now=NOW, app_url="https://app.tenderpulse.example",
    )
    assert count == 1
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    assert "<script" not in html and "<link" not in html and "<style" not in html   # styles en ligne uniquement
    assert "1 opportunité</strong>" in html and "60/100" in html
    assert "Rénovation énergétique du groupe scolaire Jean Jaurès" in html
    assert "https://www.boamp.fr/pages/avis/?q=idweb:26-200001" in html
    assert "15/12/2026 à 12h00 (J-31)" in html and "480 000 €" in html
    assert ">Go</span>" in html
    assert "Recommandation : Go" in html
    assert "https://app.tenderpulse.example" in html
    # Les opportunités sous le seuil n'apparaissent pas.
    assert "salle polyvalente" not in html and "26-200003" not in html


async def test_digest_shows_eliminatory_alerts_and_escapes_content(candidates):
    candidates[1]["objet"] = 'Réfection <script>alert("x")</script> de la toiture'
    html, count = render_digest(tenant_name="Client", profile_name="Profil", threshold=0, candidates=candidates,
                                now=NOW, app_url="https://app.example", since_hours=None)
    assert count == 4
    assert "Chiffre d&#39;affaires insuffisant" in html
    assert ">No-Go</span>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "parmi les consultations ouvertes" in html


async def test_empty_digest_and_subject(profile):
    html, count = render_digest(tenant_name="Client", profile_name=profile.name, threshold=60, candidates=[],
                                now=NOW, app_url="https://app.example")
    assert count == 0 and "Aucune opportunité" in html
    assert digest_subject(profile.name, 3, NOW) == "TenderPulse — 3 opportunités pour Isol'Rhône Rénovation (14/11/2026)"
