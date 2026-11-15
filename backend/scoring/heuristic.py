"""Grille de notation déterministe et synthèse sans LLM.

Sert de base à toute analyse : le LLM, lorsqu'il est configuré, affine ensuite les critères
qui demandent une lecture sémantique. En l'absence de LLM (ou en cas de panne), cette grille
fournit seule un résultat complet et reproductible.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.collector.models import Tender
from backend.scoring.eliminatory import days_until, detect_required_certifications, profile_certification_keys
from backend.scoring.models import (
    DECISION_LABELS, CriterionScore, Decision, EliminatoryFlag, PrefilterResult, Severity,
)
from backend.scoring.profile import CompanyProfile
from backend.textutils import find_keywords, format_eur, normalize

PARIS = ZoneInfo("Europe/Paris")

# Grille de notation : clé -> (libellé, points maximum). Total = 100.
GRID: dict[str, tuple[str, int]] = {
    "metier": ("Adéquation métier", 40),
    "zone": ("Zone géographique", 15),
    "capacite": ("Capacité financière", 15),
    "certifications": ("Certifications", 15),
    "delai": ("Délai de réponse", 15),
}

GO_THRESHOLD = 70
VERIFY_THRESHOLD = 45
BLOCKING_SCORE_CAP = 35
# Un « Go » exige une vraie adéquation métier : les critères annexes ne suffisent pas à eux seuls.
GO_MIN_METIER_RATIO = 0.6


def _criterion(key: str, score: int, justification: str) -> CriterionScore:
    label, max_score = GRID[key]
    return CriterionScore(key=key, label=label, score=max(0, min(score, max_score)), max_score=max_score,
                          justification=justification)


def score_metier(profile: CompanyProfile, tender: Tender, pre: PrefilterResult) -> CriterionScore:
    if not profile.search_terms() and not profile.cpv_codes:
        return _criterion("metier", 20, "Aucun mot-clé ni code CPV dans le profil : adéquation métier non évaluable.")
    title = normalize(tender.objet + " " + " ".join(tender.descripteurs))
    in_title = find_keywords(pre.matched_keywords, title)
    in_body = [kw for kw in pre.matched_keywords if kw not in in_title]
    points = 14 * len(in_title) + 7 * len(in_body) + (14 if pre.matched_cpv else 0)
    parts = []
    if in_title:
        parts.append("mots-clés dans l'objet : " + ", ".join(in_title))
    if in_body:
        parts.append("mots-clés dans le corps de l'avis : " + ", ".join(in_body))
    if pre.matched_cpv:
        parts.append("codes CPV ciblés : " + ", ".join(pre.matched_cpv))
    if not parts:
        parts.append("aucune correspondance avec les mots-clés, compétences ou codes CPV du profil")
    return _criterion("metier", points, "Correspondances — " + " ; ".join(parts) + ".")


def score_zone(profile: CompanyProfile, tender: Tender) -> CriterionScore:
    if not profile.departments:
        return _criterion("zone", 12, "Aucune restriction géographique dans le profil (France entière).")
    if not tender.departments:
        return _criterion("zone", 8, "Lieu d'exécution non précisé dans l'avis : à confirmer.")
    common = sorted(set(profile.departments) & set(tender.departments))
    if common:
        return _criterion("zone", 15, "Marché situé dans la zone d'intervention (départements " + ", ".join(common) + ").")
    return _criterion("zone", 0, "Marché hors zone : départements " + ", ".join(tender.departments) + ".")


def score_capacite(profile: CompanyProfile, tender: Tender) -> CriterionScore:
    budget = tender.budget_estime
    if budget is None:
        return _criterion("capacite", 9, "Budget non mentionné dans l'avis : capacité financière à apprécier sur le DCE.")
    if profile.max_contract_eur is not None and budget > profile.max_contract_eur:
        return _criterion("capacite", 0, f"Montant estimé ({format_eur(budget)}) supérieur au plafond de l'entreprise "
                                         f"({format_eur(profile.max_contract_eur)}).")
    if profile.min_contract_eur is not None and budget < profile.min_contract_eur:
        return _criterion("capacite", 5, f"Montant estimé ({format_eur(budget)}) inférieur au minimum visé "
                                         f"({format_eur(profile.min_contract_eur)}).")
    if profile.annual_revenue_eur and budget > 0.5 * profile.annual_revenue_eur:
        return _criterion("capacite", 6, f"Montant estimé ({format_eur(budget)}) supérieur à 50 % du chiffre d'affaires "
                                         f"annuel ({format_eur(profile.annual_revenue_eur)}) : risque de dépendance.")
    return _criterion("capacite", 15, f"Montant estimé ({format_eur(budget)}) compatible avec les capacités de l'entreprise.")


def score_certifications(profile: CompanyProfile, tender: Tender) -> CriterionScore:
    detected = detect_required_certifications(tender.searchable_text())
    if not detected:
        return _criterion("certifications", 12, "Aucune certification particulière repérée dans l'avis.")
    held = profile_certification_keys(profile)
    missing_blocking = [label for key, label, sev, _ in detected if key not in held and sev == Severity.BLOQUANT]
    missing_soft = [label for key, label, sev, _ in detected if key not in held and sev == Severity.A_VERIFIER]
    owned = [label for key, label, _, _ in detected if key in held]
    if missing_blocking:
        return _criterion("certifications", 0, "Certification(s) exigée(s) non détenue(s) : " + ", ".join(missing_blocking) + ".")
    if missing_soft:
        return _criterion("certifications", 6, "Certification(s) citée(s) non détenue(s), équivalence possible : "
                          + ", ".join(missing_soft) + ".")
    return _criterion("certifications", 15, "Certification(s) demandée(s) détenue(s) : " + ", ".join(owned) + ".")


def score_delai(profile: CompanyProfile, tender: Tender, now: datetime) -> CriterionScore:
    remaining = days_until(tender.date_limite, now)
    if remaining is None:
        return _criterion("delai", 8, "Date limite non précisée dans l'avis.")
    days = int(remaining)
    if remaining <= 0:
        return _criterion("delai", 0, "Date limite de remise des offres dépassée.")
    if remaining < profile.min_response_days:
        return _criterion("delai", 2, f"{days} jour(s) restant(s), moins que le minimum de {profile.min_response_days} jours du profil.")
    if remaining >= 21:
        return _criterion("delai", 15, f"{days} jours restants : délai confortable pour préparer l'offre.")
    return _criterion("delai", 10, f"{days} jours restants : délai suffisant mais à planifier sans attendre.")


def build_criteria(profile: CompanyProfile, tender: Tender, pre: PrefilterResult, now: datetime) -> list[CriterionScore]:
    return [
        score_metier(profile, tender, pre),
        score_zone(profile, tender),
        score_capacite(profile, tender),
        score_certifications(profile, tender),
        score_delai(profile, tender, now),
    ]


def finalize(criteria: list[CriterionScore], flags: list[EliminatoryFlag]) -> tuple[int, Decision]:
    """Score final et décision à partir de la grille et des critères éliminatoires."""
    score = max(0, min(100, sum(c.score for c in criteria)))
    blocking = any(flag.severity == Severity.BLOQUANT for flag in flags)
    if blocking:
        return min(score, BLOCKING_SCORE_CAP), Decision.NO_GO
    metier = next((c for c in criteria if c.key == "metier"), None)
    strong_fit = metier is None or metier.score >= GO_MIN_METIER_RATIO * metier.max_score
    if score >= GO_THRESHOLD and not flags and strong_fit:
        return score, Decision.GO
    if score >= VERIFY_THRESHOLD:
        return score, Decision.A_VERIFIER
    return score, Decision.NO_GO


def format_deadline(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return "non précisée"
    remaining = days_until(deadline, now) or 0
    label = f"{deadline.astimezone(PARIS):%d/%m/%Y à %Hh%M}"
    if remaining <= 0:
        return f"{label} (dépassée)"
    return f"{label} (dans {int(remaining)} jour(s))"


def build_summary(
    tender: Tender, criteria: list[CriterionScore], flags: list[EliminatoryFlag],
    score: int, decision: Decision, now: datetime,
) -> str:
    """Résumé exécutif en 5 lignes, orienté décision."""
    place = ", ".join(tender.departments) if tender.departments else "lieu non précisé"
    nature = ", ".join(t.capitalize() for t in tender.type_marche) or "Marché"
    strengths = [c for c in criteria if c.score >= 0.75 * c.max_score]
    weaknesses = [c for c in criteria if c.score <= 0.4 * c.max_score]
    if flags:
        vigilance = "Points bloquants ou à lever : " + " ; ".join(flag.label for flag in flags[:4]) + "."
    elif weaknesses:
        vigilance = "Points de vigilance : " + ", ".join(c.label.lower() for c in weaknesses) + "."
    else:
        vigilance = "Aucun critère éliminatoire détecté dans l'avis."
    atouts = ("Atouts : " + ", ".join(c.label.lower() for c in strengths) + "."
              if strengths else "Atouts : aucun critère nettement favorable.")
    action = {
        Decision.GO: "retirer le DCE et lancer la réponse.",
        Decision.A_VERIFIER: "lire le règlement de consultation pour lever les points signalés avant de décider.",
        Decision.NO_GO: "ne pas donner suite, sauf élément nouveau.",
    }[decision]
    lot_info = f" — {len(tender.lots)} lot(s)" if tender.lots else ""
    lines = [
        f"{nature} : {tender.objet.strip() or 'objet non précisé'} — {tender.acheteur or 'acheteur non précisé'}.",
        f"Lieu : {place}{lot_info}. Budget estimé : {format_eur(tender.budget_estime)}.",
        f"Date limite de remise des offres : {format_deadline(tender.date_limite, now)}.",
        f"{atouts} {vigilance}",
        f"Recommandation : {DECISION_LABELS[decision]} ({score}/100) — {action}",
    ]
    return "\n".join(lines)
