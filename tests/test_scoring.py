"""Moteur de scoring : pré-filtrage, grille, critères éliminatoires, synthèse et analyse LLM simulée."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.collector import parse_record
from backend.scoring import (
    CompanyProfile, Decision, EliminatoryType, LLMClient, ScoringPipeline, Severity, prefilter,
)
from backend.scoring.eliminatory import detect_eliminatory, detect_minimum_turnover
from backend.textutils import normalize, parse_amounts
from tests import boamp_fixtures as fx

pytestmark = pytest.mark.anyio
NOW = fx.NOW


# ----------------------------------------------------------------------------- pré-filtrage

def test_prefilter_keeps_tenders_matching_keywords_cpv_and_zone(profile, tenders):
    result = prefilter(profile, tenders["26-200001"], NOW)
    assert result.passed and result.reasons == []
    assert {"isolation", "menuiserie", "rénovation énergétique"} <= set(result.matched_keywords)
    assert result.matched_cpv == ["45321000", "45421000"]


def test_prefilter_rejects_excluded_keyword(profile, tenders):
    result = prefilter(profile, tenders["26-200004"], NOW)
    assert not result.passed
    assert result.excluded_keywords == ["désamiantage"]
    assert any("Mot-clé exclu" in reason for reason in result.reasons)


def test_prefilter_rejects_out_of_zone_department(profile, tenders):
    result = prefilter(profile, tenders["26-200005"], NOW)
    assert not result.passed
    assert any("Hors zone" in reason and "13" in reason for reason in result.reasons)


def test_prefilter_rejects_tender_without_any_business_match(profile, tenders):
    result = prefilter(profile, tenders["26-200006"], NOW)
    assert not result.passed
    assert result.reasons == ["Aucun mot-clé, compétence ou code CPV du profil ne correspond"]


def test_prefilter_rejects_expired_deadline(profile, tenders):
    expired = tenders["26-200001"].model_copy(update={"date_limite": NOW})
    assert not prefilter(profile, expired, NOW).passed


def test_prefilter_matches_whole_words_only(profile, tenders):
    # « sol » ne doit pas correspondre à « isolation », mais le pluriel « menuiseries » correspond à « menuiserie ».
    narrow = profile.model_copy(update={"keywords_include": ["sol"], "skills": [], "cpv_codes": []})
    assert not prefilter(narrow, tenders["26-200003"], NOW).passed
    plural = profile.model_copy(update={"keywords_include": ["menuiserie"], "skills": [], "cpv_codes": []})
    assert prefilter(plural, tenders["26-200007"], NOW).passed


async def test_pipeline_selects_exactly_the_relevant_tenders(profile, tenders):
    pipeline = ScoringPipeline()
    analyses = {idweb: await pipeline.analyze(profile, tender, NOW) for idweb, tender in tenders.items()}
    kept = {idweb for idweb, analysis in analyses.items() if analysis is not None}
    assert kept == {"26-200001", "26-200002", "26-200003", "26-200007"}


# ----------------------------------------------------------------------------- scoring

async def test_ideal_tender_scores_go_with_justified_criteria(profile, tenders):
    analysis = await ScoringPipeline().analyze(profile, tenders["26-200001"], NOW)
    assert analysis.decision == Decision.GO
    assert analysis.score >= 85
    assert analysis.eliminatory == []
    assert [c.key for c in analysis.criteria] == ["metier", "zone", "capacite", "certifications", "delai"]
    assert sum(c.max_score for c in analysis.criteria) == 100
    assert analysis.score == sum(c.score for c in analysis.criteria)
    assert all(c.justification for c in analysis.criteria)
    by_key = {c.key: c for c in analysis.criteria}
    assert by_key["metier"].score == 40 and "isolation" in by_key["metier"].justification
    assert by_key["zone"].score == 15 and "69" in by_key["zone"].justification
    assert by_key["certifications"].score == 15 and "RGE" in by_key["certifications"].justification
    assert analysis.budget_estime == 480000
    assert analysis.date_limite == tenders["26-200001"].date_limite


async def test_summary_is_five_decision_oriented_lines(profile, tenders):
    analysis = await ScoringPipeline().analyze(profile, tenders["26-200001"], NOW)
    lines = analysis.summary.splitlines()
    assert len(lines) == 5
    assert "Ville de Villeurbanne" in lines[0]
    assert "480 000 €" in lines[1]
    assert "15/12/2026" in lines[2] and "dans 31 jour(s)" in lines[2]
    assert lines[4].startswith("Recommandation : Go")


async def test_weak_business_fit_never_yields_an_automatic_go(profile, tenders):
    # Un seul mot-clé dans le corps de l'avis : zone, budget et délai parfaits ne suffisent pas pour un « Go ».
    weak = profile.model_copy(update={"keywords_include": ["façades"], "skills": [], "cpv_codes": []})
    analysis = await ScoringPipeline().analyze(weak, tenders["26-200001"], NOW)
    by_key = {c.key: c for c in analysis.criteria}
    assert by_key["metier"].score == 7 and analysis.score >= 45
    assert analysis.eliminatory == [] and analysis.decision == Decision.A_VERIFIER


def test_multiline_title_is_flattened_so_summary_keeps_five_lines(profile):
    record = dict(fx.RENOVATION_ECOLE, objet="Rénovation énergétique\n  du groupe scolaire :\nisolation et menuiseries")
    tender = parse_record(record)
    assert tender.objet == "Rénovation énergétique du groupe scolaire : isolation et menuiseries"
    analysis = ScoringPipeline().analyze_rules(profile, tender, prefilter(profile, tender, NOW), NOW)
    assert len(analysis.summary.splitlines()) == 5


# ----------------------------------------------------------------------------- critères éliminatoires

async def test_minimum_turnover_requirement_is_detected_as_blocking(profile, tenders):
    """Preuve de la détection d'un critère éliminatoire : CA minimum exigé de 5 M€ pour une PME à 2,4 M€."""
    analysis = await ScoringPipeline().analyze(profile, tenders["26-200002"], NOW)
    flags = [f for f in analysis.eliminatory if f.type == EliminatoryType.CHIFFRE_AFFAIRES]
    assert len(flags) == 1
    assert flags[0].severity == Severity.BLOQUANT
    assert "5 000 000 €" in flags[0].detail and "2 400 000 €" in flags[0].detail
    assert analysis.decision == Decision.NO_GO
    assert analysis.score <= 35
    assert analysis.summary.splitlines()[4].startswith("Recommandation : No-Go")


def test_turnover_requirement_is_not_blocking_when_company_is_large_enough(profile, tenders):
    bigger = profile.model_copy(update={"annual_revenue_eur": 8_000_000})
    flags = detect_eliminatory(bigger, tenders["26-200002"], NOW)
    assert not [f for f in flags if f.type == EliminatoryType.CHIFFRE_AFFAIRES]


@pytest.mark.parametrize("sentence, expected", [
    ("Chiffre d'affaires annuel minimum exigé : 1,5 million d'euros.", 1_500_000),
    ("Le chiffre d'affaires doit être au moins égal à 750 k€ sur le dernier exercice.", 750_000),
    ("Chiffre d’affaires minimal de 300.000 € HT.", 300_000),
    ("Déclaration concernant le chiffre d'affaires global des trois derniers exercices.", None),
])
def test_minimum_turnover_parsing(sentence, expected):
    assert detect_minimum_turnover(normalize(sentence)) == expected


def test_amount_parsing_handles_french_formats():
    amounts = [value for _, value in parse_amounts(normalize("Lot 1 : 150000,00 € HT ; lot 2 : 2 M€ ; lot 3 : 45 000 euros"))]
    assert amounts == [150000.0, 2_000_000.0, 45000.0]


async def test_mandatory_certification_not_held_is_blocking(profile, tenders):
    analysis = await ScoringPipeline().analyze(profile, tenders["26-200007"], NOW)
    flags = [f for f in analysis.eliminatory if f.type == EliminatoryType.CERTIFICATION]
    assert [f.label for f in flags] == ["Certification ISO 14001 non détenue"]
    assert flags[0].severity == Severity.BLOQUANT
    assert analysis.decision == Decision.NO_GO


async def test_certification_held_by_company_raises_no_flag(profile, tenders):
    certified = profile.model_copy(update={"certifications": profile.certifications + ["ISO 14001:2015"]})
    analysis = await ScoringPipeline().analyze(certified, tenders["26-200007"], NOW)
    assert analysis.eliminatory == []
    assert analysis.decision == Decision.GO


def test_certification_with_equivalence_clause_is_only_to_verify(profile):
    record = dict(fx.MENUISERIES_ISO)
    record["donnees"] = record["donnees"].replace(
        "La certification ISO 14001 est obligatoire et devra être jointe à la candidature.",
        "Qualification Qualifelec exigée ou équivalent.")
    flags = detect_eliminatory(profile, parse_record(record), NOW)
    assert [(f.type, f.severity) for f in flags] == [(EliminatoryType.CERTIFICATION, Severity.A_VERIFIER)]


async def test_response_deadline_too_short_is_blocking(profile, tenders):
    analysis = await ScoringPipeline().analyze(profile, tenders["26-200003"], NOW)
    flags = [f for f in analysis.eliminatory if f.type == EliminatoryType.DELAI]
    assert len(flags) == 1 and flags[0].severity == Severity.BLOQUANT
    assert "3 jour(s)" in flags[0].detail and "10 jours" in flags[0].detail
    assert analysis.decision == Decision.NO_GO


def test_out_of_zone_budget_and_custom_criteria_are_flagged(profile, tenders):
    out_of_zone = detect_eliminatory(profile, tenders["26-200005"], NOW)
    assert [f.type for f in out_of_zone] == [EliminatoryType.ZONE]

    small_company = profile.model_copy(update={"max_contract_eur": 300_000})
    too_big = [f for f in detect_eliminatory(small_company, tenders["26-200002"], NOW) if f.type == EliminatoryType.BUDGET]
    assert too_big[0].severity == Severity.BLOQUANT and "650 000 €" in too_big[0].detail
    alloti = [f for f in detect_eliminatory(small_company, tenders["26-200001"], NOW) if f.type == EliminatoryType.BUDGET]
    assert alloti[0].severity == Severity.A_VERIFIER  # marché alloti : le lot visé peut rester accessible

    record = dict(fx.RENOVATION_ECOLE)
    record["donnees"] = record["donnees"].replace("Les travaux sont réalisés en site occupé",
                                                  "Une visite obligatoire du site est organisée. Les travaux sont réalisés en site occupé")
    custom = [f for f in detect_eliminatory(profile, parse_record(record), NOW) if f.type == EliminatoryType.PERSONNALISE]
    assert len(custom) == 1 and "visite obligatoire" in custom[0].label


def test_profile_validation_normalizes_and_rejects_bad_input():
    cleaned = CompanyProfile(name="Test", departments=["1", "2a", "69", "69"], cpv_codes=["45321000-3", "4542"],
                             keywords_include=[" Isolation ", "isolation", ""])
    assert cleaned.departments == ["01", "2A", "69"]
    assert cleaned.cpv_codes == ["45321000", "4542"]
    assert cleaned.keywords_include == ["Isolation"]
    with pytest.raises(ValueError):
        CompanyProfile(name="Test", departments=["Rhône"])
    with pytest.raises(ValueError):
        CompanyProfile(name="Test", alert_threshold=140)


# ----------------------------------------------------------------------------- analyse LLM (simulée, sans réseau)

LLM_JSON = {
    "criteres": [
        {"cle": "metier", "note": 36, "justification": "ITE et menuiseries extérieures : cœur de métier de l'entreprise."},
        {"cle": "capacite", "note": 13, "justification": "480 k€ répartis en deux lots, soit 20 % du chiffre d'affaires."},
        {"cle": "certifications", "note": 99, "justification": "Mention RGE détenue."},
    ],
    "criteres_eliminatoires": [
        {"type": "autre", "libelle": "Travaux en site occupé pendant les vacances scolaires",
         "detail": "Les travaux sont réalisés en site occupé, pendant les vacances scolaires.", "severite": "a_verifier"},
    ],
    "resume": [
        "Rénovation énergétique d'un groupe scolaire pour la Ville de Villeurbanne.",
        "Deux lots (ITE 310 k€, menuiseries 170 k€), 480 k€ au total.",
        "Offres à remettre avant le 15/12/2026 à 12h00.",
        "Atout : cœur de métier et mention RGE ; risque : planning contraint par les vacances scolaires.",
        "À vérifier : confirmer la disponibilité des équipes sur les congés scolaires avant de répondre.",
    ],
    "decision": "a_verifier",
    "date_limite": "2026-12-15T12:00:00+01:00",
    "budget_estime": 480000,
}


def _openai_transport(content: str, calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content), "auth": request.headers.get("Authorization")})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})
    return httpx.MockTransport(handler)


async def test_llm_analysis_is_merged_with_deterministic_rules(profile, tenders):
    calls: list[dict] = []
    llm = LLMClient("openai", "https://llm.example/v1", "modele-test", "cle-secrete",
                    transport=_openai_transport("```json\n" + json.dumps(LLM_JSON, ensure_ascii=False) + "\n```", calls))
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200001"], NOW)
    await llm.aclose()

    assert calls[0]["url"] == "https://llm.example/v1/chat/completions"
    assert calls[0]["auth"] == "Bearer cle-secrete"
    assert calls[0]["body"]["response_format"] == {"type": "json_object"}
    assert "Isol'Rhône Rénovation" in calls[0]["body"]["messages"][1]["content"]

    by_key = {c.key: c for c in analysis.criteria}
    assert by_key["metier"].score == 36 and "cœur de métier" in by_key["metier"].justification
    assert by_key["certifications"].score == 15          # note hors barème ramenée au maximum de la grille
    assert by_key["zone"].score == 15 and by_key["delai"].score == 15  # critères factuels : restent déterministes
    assert analysis.score == 36 + 15 + 13 + 15 + 15
    assert [(f.source, f.severity) for f in analysis.eliminatory] == [("llm", Severity.A_VERIFIER)]
    assert analysis.decision == Decision.A_VERIFIER    # un point à vérifier interdit le « Go » automatique
    assert analysis.summary.splitlines() == LLM_JSON["resume"]
    assert analysis.analysis_source == "llm" and analysis.model == "modele-test"


async def test_llm_cannot_override_a_blocking_rule(profile, tenders):
    optimistic = dict(LLM_JSON, criteres_eliminatoires=[], decision="go")
    llm = LLMClient("openai", "https://llm.example/v1", "modele-test", transport=_openai_transport(json.dumps(optimistic), []))
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200002"], NOW)
    await llm.aclose()
    assert analysis.decision == Decision.NO_GO and analysis.score <= 35
    assert any(f.type == EliminatoryType.CHIFFRE_AFFAIRES and f.source == "regles" for f in analysis.eliminatory)


async def test_ollama_provider_uses_native_json_mode(profile, tenders):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(LLM_JSON)}})

    llm = LLMClient("ollama", "http://ollama:11434", "llama3.1", transport=httpx.MockTransport(handler))
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200001"], NOW)
    await llm.aclose()
    assert calls[0]["url"] == "http://ollama:11434/api/chat"
    assert calls[0]["body"]["format"] == "json" and calls[0]["body"]["stream"] is False
    assert analysis.analysis_source == "llm"


@pytest.mark.parametrize("status, content", [(500, "panne"), (200, "Désolé, je ne peux pas répondre."), (200, '{"criteres": "oups"}')])
async def test_llm_failure_falls_back_to_deterministic_analysis(profile, tenders, status, content):
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if status != 200:
            return httpx.Response(status, text=content)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    llm = LLMClient("openai", "https://llm.example/v1", "modele-test", transport=httpx.MockTransport(handler))
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200001"], NOW)
    await llm.aclose()
    assert attempts["count"] == 2                      # une nouvelle tentative avant le repli
    assert analysis.analysis_source == "heuristique"
    assert analysis.decision == Decision.GO and len(analysis.summary.splitlines()) == 5


async def test_llm_is_never_called_for_prefiltered_tenders(profile, tenders):
    calls: list[dict] = []
    llm = LLMClient("openai", "https://llm.example/v1", "modele-test", transport=_openai_transport(json.dumps(LLM_JSON), calls))
    assert await ScoringPipeline(llm).analyze(profile, tenders["26-200006"], NOW) is None
    await llm.aclose()
    assert calls == []


# ----------------------------------------------------------------------------- verrou déterministe du score

def _inflating_llm(decision: str = "go") -> dict:
    """Réponse d'un LLM trompé par un avis piégé : notes maximales partout et décision « go »."""
    return {
        "criteres": [{"cle": key, "note": 100, "justification": "Adéquation parfaite."}
                     for key in ("metier", "capacite", "certifications")],
        "criteres_eliminatoires": [], "resume": ["a", "b", "c", "d", "e"], "decision": decision,
    }


async def test_llm_cannot_inflate_scores_beyond_the_deterministic_lock(profile, tenders):
    from backend.scoring.heuristic import GRID
    from backend.scoring.llm import LLM_CRITERIA
    from backend.scoring.pipeline import max_llm_uplift

    for idweb in ("26-200001", "26-200003", "26-200004"):
        baseline = await ScoringPipeline(None).analyze(profile, tenders[idweb], NOW)
        if baseline is None:
            continue
        llm = LLMClient("openai", "https://llm.example/v1", "modele-test",
                        transport=_openai_transport(json.dumps(_inflating_llm()), []))
        analysis = await ScoringPipeline(llm).analyze(profile, tenders[idweb], NOW)
        await llm.aclose()

        base = {c.key: c.score for c in baseline.criteria}
        for criterion in analysis.criteria:
            if criterion.key in LLM_CRITERIA:
                ceiling = min(criterion.max_score, base[criterion.key] + max_llm_uplift(criterion.max_score))
                assert criterion.score <= ceiling, (idweb, criterion.key)
            else:
                assert criterion.score == base[criterion.key]     # critères factuels : jamais confiés au LLM
        max_gain = sum(max_llm_uplift(GRID[key][1]) for key in LLM_CRITERIA)
        assert analysis.score <= baseline.score + max_gain
        # Le LLM ne transforme jamais seul un avis en « Go ».
        if baseline.decision != Decision.GO:
            assert analysis.decision != Decision.GO, idweb


async def test_capped_note_is_explained_in_the_justification(profile, tenders):
    llm = LLMClient("openai", "https://llm.example/v1", "modele-test",
                    transport=_openai_transport(json.dumps(_inflating_llm()), []))
    baseline = await ScoringPipeline(None).analyze(profile, tenders["26-200003"], NOW)
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200003"], NOW)
    await llm.aclose()
    capped = [c for c, b in zip(analysis.criteria, baseline.criteria) if c.score > b.score or "plafonnée" in c.justification]
    assert any("plafonnée" in c.justification for c in capped)


async def test_llm_can_still_lower_a_score(profile, tenders):
    pessimistic = dict(_inflating_llm("no_go"), criteres=[
        {"cle": key, "note": 0, "justification": "Hors sujet."} for key in ("metier", "capacite", "certifications")])
    llm = LLMClient("openai", "https://llm.example/v1", "modele-test",
                    transport=_openai_transport(json.dumps(pessimistic), []))
    analysis = await ScoringPipeline(llm).analyze(profile, tenders["26-200001"], NOW)
    await llm.aclose()
    assert {c.key: c.score for c in analysis.criteria}["metier"] == 0
    assert analysis.decision != Decision.GO
