"""Pré-filtrage rapide (sans LLM) : écarte les avis manifestement hors cible."""
from __future__ import annotations

from datetime import datetime

from backend.collector.models import Tender
from backend.scoring.models import PrefilterResult
from backend.scoring.profile import CompanyProfile
from backend.textutils import cpv_matches, find_keywords


def prefilter(profile: CompanyProfile, tender: Tender, now: datetime) -> PrefilterResult:
    """Décide si un avis mérite une analyse fine.

    Un avis est écarté si : la date limite est dépassée, il contient un mot-clé exclu,
    il est hors des départements d'intervention, ou il ne correspond à aucun mot-clé,
    compétence ou code CPV du profil.
    """
    reasons: list[str] = []
    text = tender.searchable_text()

    if tender.date_limite is not None and tender.date_limite <= now:
        reasons.append("Date limite de remise des offres dépassée")

    excluded = find_keywords(profile.keywords_exclude, text)
    if excluded:
        reasons.append("Mot-clé exclu présent : " + ", ".join(excluded))

    if profile.departments and tender.departments:
        if not set(profile.departments) & set(tender.departments):
            reasons.append(
                "Hors zone d'intervention : avis sur " + ", ".join(tender.departments)
                + " ; zone couverte : " + ", ".join(profile.departments)
            )

    matched_keywords = find_keywords(profile.search_terms(), text)
    matched_cpv = cpv_matches(profile.cpv_codes, tender.cpv_codes)
    has_targeting = bool(profile.search_terms() or profile.cpv_codes)
    if has_targeting and not matched_keywords and not matched_cpv:
        reasons.append("Aucun mot-clé, compétence ou code CPV du profil ne correspond")

    return PrefilterResult(
        passed=not reasons,
        reasons=reasons,
        matched_keywords=matched_keywords,
        matched_cpv=matched_cpv,
        excluded_keywords=excluded,
    )
