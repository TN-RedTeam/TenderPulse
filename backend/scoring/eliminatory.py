"""Détection déterministe des critères éliminatoires dans le texte d'un avis."""
from __future__ import annotations

import re
from datetime import datetime

from backend.collector.models import Tender
from backend.scoring.models import EliminatoryFlag, EliminatoryType, Severity
from backend.scoring.profile import CompanyProfile
from backend.textutils import find_keywords, format_eur, normalize, parse_amounts

# Référentiel des certifications/qualifications courantes des marchés publics français.
# Les motifs s'appliquent à un texte normalisé (minuscules, sans accents).
CERTIFICATION_CATALOG: dict[str, tuple[str, str]] = {
    "qualibat": ("Qualibat", r"qualibat"),
    "qualifelec": ("Qualifelec", r"qualifelec"),
    "qualipaysage": ("QualiPaysage", r"quali ?paysage"),
    "qualipv": ("QualiPV", r"quali ?pv"),
    "qualipac": ("QualiPAC", r"quali ?pac"),
    "qualiopi": ("Qualiopi", r"qualiopi"),
    "rge": ("RGE", r"(?<![a-z0-9])rge(?![a-z0-9])|reconnu garant de l'environnement"),
    "opqibi": ("OPQIBI", r"opqibi"),
    "opqcm": ("OPQCM", r"opqcm"),
    "fntp": ("Identification professionnelle FNTP", r"(?<![a-z0-9])fntp(?![a-z0-9])"),
    "mase": ("MASE", r"(?<![a-z0-9])mase(?![a-z0-9])"),
    "iso_9001": ("ISO 9001", r"iso[\s\-/]*9001"),
    "iso_14001": ("ISO 14001", r"iso[\s\-/]*14001"),
    "iso_27001": ("ISO 27001", r"iso(?:[\s\-/]|cei|iec)*27001"),
    "iso_45001": ("ISO 45001", r"iso[\s\-/]*45001"),
    "hds": ("HDS (hébergeur de données de santé)", r"(?<![a-z0-9])hds(?![a-z0-9])|hebergeur de donnees de sante"),
    "secnumcloud": ("SecNumCloud", r"secnumcloud"),
    "certibiocide": ("Certibiocide", r"certibiocide"),
    "amiante_ss3": ("Certification amiante (sous-section 3)", r"sous[\s\-]section 3|certification amiante|(?<![a-z0-9])ss3(?![a-z0-9])"),
    "apsad": ("APSAD", r"(?<![a-z0-9])apsad(?![a-z0-9])"),
    "cofrac": ("Accréditation COFRAC", r"cofrac"),
}

_MANDATORY_RE = re.compile(
    r"exige|obligatoire|requis|imperati|indispensable|sous peine|doit etre titulaire|devra etre titulaire|"
    r"doivent etre titulaires|devront etre titulaires|doit justifier|devra justifier|doit detenir|devra detenir|"
    r"doit posseder|devra posseder|doit disposer|devra disposer|titulaire d"
)
_EQUIVALENT_RE = re.compile(r"ou equivalent|ou equivalente|equivalence|references equivalentes|moyen de preuve equivalent")
_TURNOVER_RE = re.compile(r"chiffre d'affaires|chiffres d'affaires|(?<![a-z0-9])ca (?:annuel|minimum|minimal|global)")
_MINIMUM_RE = re.compile(r"minimum|minimal|au moins|superieur|egal|ne peut etre inferieur|d'au moins|plancher")


def profile_certification_keys(profile: CompanyProfile) -> set[str]:
    """Clés du référentiel couvertes par les certifications déclarées dans le profil."""
    held: set[str] = set()
    for certification in profile.certifications:
        norm = normalize(certification)
        for key, (_, pattern) in CERTIFICATION_CATALOG.items():
            if re.search(pattern, norm):
                held.add(key)
    return held


def detect_required_certifications(normalized_text: str) -> list[tuple[str, str, Severity, str]]:
    """Certifications citées dans l'avis : (clé, libellé, sévérité, extrait)."""
    detected = []
    for key, (label, pattern) in CERTIFICATION_CATALOG.items():
        match = re.search(pattern, normalized_text)
        if not match:
            continue
        start, end = max(0, match.start() - 160), min(len(normalized_text), match.end() + 160)
        window = normalized_text[start:end]
        mandatory = _MANDATORY_RE.search(window) is not None
        equivalent = _EQUIVALENT_RE.search(normalized_text[match.end(): end]) is not None
        severity = Severity.BLOQUANT if mandatory and not equivalent else Severity.A_VERIFIER
        detected.append((key, label, severity, window.strip()))
    return detected


def detect_minimum_turnover(normalized_text: str) -> float | None:
    """Chiffre d'affaires minimum exigé par l'avis, en euros, s'il est chiffré."""
    best: float | None = None
    for match in _TURNOVER_RE.finditer(normalized_text):
        window = normalized_text[match.start(): match.start() + 260]
        if not _MINIMUM_RE.search(window):
            continue
        amounts = [amount for _, amount in parse_amounts(window) if amount >= 1000]
        if amounts and (best is None or amounts[0] > best):
            best = amounts[0]
    return best


def days_until(deadline: datetime | None, now: datetime) -> float | None:
    if deadline is None:
        return None
    return (deadline - now).total_seconds() / 86400


def detect_eliminatory(profile: CompanyProfile, tender: Tender, now: datetime) -> list[EliminatoryFlag]:
    """Applique toutes les règles éliminatoires du profil à un avis."""
    flags: list[EliminatoryFlag] = []
    text = tender.searchable_text()

    # 1. Chiffre d'affaires minimum exigé
    required_turnover = detect_minimum_turnover(text)
    if required_turnover is not None:
        if profile.annual_revenue_eur is None:
            flags.append(EliminatoryFlag(
                type=EliminatoryType.CHIFFRE_AFFAIRES,
                label="Chiffre d'affaires minimum exigé",
                detail=f"L'avis exige un chiffre d'affaires minimum de {format_eur(required_turnover)} ; "
                       "le chiffre d'affaires de l'entreprise n'est pas renseigné dans le profil.",
                severity=Severity.A_VERIFIER,
            ))
        elif profile.annual_revenue_eur < required_turnover:
            flags.append(EliminatoryFlag(
                type=EliminatoryType.CHIFFRE_AFFAIRES,
                label="Chiffre d'affaires insuffisant",
                detail=f"L'avis exige un chiffre d'affaires minimum de {format_eur(required_turnover)} ; "
                       f"celui de l'entreprise est de {format_eur(profile.annual_revenue_eur)}.",
                severity=Severity.BLOQUANT,
            ))

    # 2. Certifications exigées et non détenues
    held = profile_certification_keys(profile)
    for key, label, severity, _ in detect_required_certifications(text):
        if key in held:
            continue
        if severity == Severity.BLOQUANT:
            detail = f"L'avis exige la certification {label}, absente du profil de l'entreprise."
        else:
            detail = (f"L'avis mentionne la certification {label} (éventuellement « ou équivalent »), "
                      "absente du profil : vérifier si une preuve équivalente est recevable.")
        flags.append(EliminatoryFlag(
            type=EliminatoryType.CERTIFICATION, label=f"Certification {label} non détenue",
            detail=detail, severity=severity,
        ))

    # 3. Zone géographique hors périmètre
    if profile.departments and tender.departments and not set(profile.departments) & set(tender.departments):
        flags.append(EliminatoryFlag(
            type=EliminatoryType.ZONE,
            label="Zone hors périmètre",
            detail="Marché situé dans le(s) département(s) " + ", ".join(tender.departments)
                   + ", hors de la zone d'intervention (" + ", ".join(profile.departments) + ").",
            severity=Severity.BLOQUANT,
        ))

    # 4. Délai de réponse trop court
    remaining = days_until(tender.date_limite, now)
    if remaining is not None:
        if remaining <= 0:
            flags.append(EliminatoryFlag(
                type=EliminatoryType.DELAI, label="Date limite dépassée",
                detail="La date limite de remise des offres est dépassée.", severity=Severity.BLOQUANT,
            ))
        elif remaining < profile.min_response_days:
            flags.append(EliminatoryFlag(
                type=EliminatoryType.DELAI,
                label="Délai de réponse trop court",
                detail=f"Il reste {max(int(remaining), 0)} jour(s) avant la date limite ; "
                       f"l'entreprise demande au moins {profile.min_response_days} jours pour répondre.",
                severity=Severity.BLOQUANT,
            ))

    # 5. Budget hors capacité financière
    budget = tender.budget_estime
    if budget is not None:
        if profile.max_contract_eur is not None and budget > profile.max_contract_eur:
            if tender.lots and len(tender.lots) > 1:
                flags.append(EliminatoryFlag(
                    type=EliminatoryType.BUDGET,
                    label="Montant global supérieur à la capacité",
                    detail=f"Montant global estimé à {format_eur(budget)} pour un plafond de "
                           f"{format_eur(profile.max_contract_eur)} ; le marché est alloti en {len(tender.lots)} lots : "
                           "vérifier le montant du ou des lots visés.",
                    severity=Severity.A_VERIFIER,
                ))
            else:
                flags.append(EliminatoryFlag(
                    type=EliminatoryType.BUDGET,
                    label="Marché trop important",
                    detail=f"Montant estimé à {format_eur(budget)}, supérieur au plafond de l'entreprise "
                           f"({format_eur(profile.max_contract_eur)}).",
                    severity=Severity.BLOQUANT,
                ))
        elif profile.min_contract_eur is not None and budget < profile.min_contract_eur:
            flags.append(EliminatoryFlag(
                type=EliminatoryType.BUDGET,
                label="Marché trop petit",
                detail=f"Montant estimé à {format_eur(budget)}, inférieur au minimum visé "
                       f"({format_eur(profile.min_contract_eur)}).",
                severity=Severity.A_VERIFIER,
            ))

    # 6. Critères éliminatoires personnalisés du profil
    for criterion in find_keywords(profile.eliminatory_criteria, text):
        flags.append(EliminatoryFlag(
            type=EliminatoryType.PERSONNALISE,
            label=f"Critère éliminatoire du profil : {criterion}",
            detail=f"L'avis contient « {criterion} », déclaré comme critère éliminatoire par l'entreprise.",
            severity=Severity.BLOQUANT,
        ))

    return flags
