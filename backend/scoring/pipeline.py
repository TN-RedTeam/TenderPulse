"""Pipeline d'analyse hybride : pré-filtre → règles éliminatoires → grille → LLM (optionnel)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.collector.models import Tender
from backend.scoring.eliminatory import detect_eliminatory
from backend.scoring.heuristic import GRID, build_criteria, build_summary, finalize
from backend.scoring.llm import LLM_CRITERIA, LLMAnalysis, LLMClient, LLMError
from backend.scoring.models import (
    CriterionScore, Decision, EliminatoryFlag, EliminatoryType, PrefilterResult, Severity, TenderAnalysis,
)
from backend.scoring.prefilter import prefilter
from backend.scoring.profile import CompanyProfile
from backend.textutils import normalize

logger = logging.getLogger("tenderpulse.scoring")

SUMMARY_LINES = 5


def _merge_criteria(baseline: list[CriterionScore], llm: LLMAnalysis) -> list[CriterionScore]:
    """Remplace les critères sémantiques par ceux du LLM, bornés par la grille."""
    merged = []
    for criterion in baseline:
        proposal = llm.criterion(criterion.key) if criterion.key in LLM_CRITERIA else None
        if proposal is None:
            merged.append(criterion)
            continue
        max_score = GRID[criterion.key][1]
        merged.append(CriterionScore(
            key=criterion.key, label=criterion.label, max_score=max_score,
            score=max(0, min(max_score, round(proposal.note))),
            justification=proposal.justification.strip() or criterion.justification,
        ))
    return merged


def _merge_flags(rule_flags: list[EliminatoryFlag], llm: LLMAnalysis) -> list[EliminatoryFlag]:
    """Ajoute les critères éliminatoires du LLM qui ne doublonnent pas ceux des règles."""
    flags = list(rule_flags)
    seen_labels = {normalize(flag.label) for flag in flags}
    # Types déjà couverts de façon fiable par les règles : on ne laisse pas le LLM les dupliquer.
    covered_types = {flag.type for flag in rule_flags if flag.type != EliminatoryType.CERTIFICATION}
    for item in llm.criteres_eliminatoires:
        flag_type = EliminatoryType(item.type)
        label_key = normalize(item.libelle)
        if not label_key or label_key in seen_labels or flag_type in covered_types:
            continue
        if flag_type == EliminatoryType.CERTIFICATION and any(
            f.type == EliminatoryType.CERTIFICATION and (normalize(f.label) in label_key or label_key in normalize(f.label)
                                                         or _shared_token(f.label, item.libelle))
            for f in rule_flags
        ):
            continue
        seen_labels.add(label_key)
        flags.append(EliminatoryFlag(
            type=flag_type, label=item.libelle.strip(), detail=item.detail.strip() or item.libelle.strip(),
            severity=Severity(item.severite), source="llm",
        ))
    return flags


def _shared_token(label_a: str, label_b: str) -> bool:
    ignored = {"certification", "non", "detenue", "exigee", "qualification", "requise", "obligatoire", "de", "la", "le"}
    tokens_a = {t for t in normalize(label_a).split() if len(t) > 2 and t not in ignored}
    tokens_b = {t for t in normalize(label_b).split() if len(t) > 2 and t not in ignored}
    return bool(tokens_a & tokens_b)


def _five_lines(llm_lines: list[str], fallback: str) -> str:
    """Garantit un résumé d'exactement 5 lignes, complété au besoin par la synthèse déterministe."""
    lines = [line for line in llm_lines if line][:SUMMARY_LINES]
    fallback_lines = fallback.splitlines()
    while len(lines) < SUMMARY_LINES:
        lines.append(fallback_lines[len(lines)])
    return "\n".join(lines)


class ScoringPipeline:
    """Analyse un avis pour un profil. Sans client LLM, l'analyse est entièrement déterministe."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm

    def prefilter(self, profile: CompanyProfile, tender: Tender, now: datetime | None = None) -> PrefilterResult:
        return prefilter(profile, tender, now or datetime.now(timezone.utc))

    def analyze_rules(self, profile: CompanyProfile, tender: Tender, pre: PrefilterResult, now: datetime) -> TenderAnalysis:
        """Analyse déterministe complète (grille + critères éliminatoires + synthèse)."""
        flags = detect_eliminatory(profile, tender, now)
        criteria = build_criteria(profile, tender, pre, now)
        score, decision = finalize(criteria, flags)
        return TenderAnalysis(
            idweb=tender.idweb, score=score, decision=decision, criteria=criteria, eliminatory=flags,
            summary=build_summary(tender, criteria, flags, score, decision, now),
            date_limite=tender.date_limite, budget_estime=tender.budget_estime,
            analysis_source="heuristique", model=None,
        )

    async def analyze(
        self, profile: CompanyProfile, tender: Tender, now: datetime | None = None, *, use_llm: bool = True,
    ) -> TenderAnalysis | None:
        """Retourne l'analyse de l'avis, ou None s'il est écarté par le pré-filtre."""
        now = now or datetime.now(timezone.utc)
        pre = prefilter(profile, tender, now)
        if not pre.passed:
            return None
        baseline = self.analyze_rules(profile, tender, pre, now)
        if self.llm is None or not use_llm:
            return baseline
        try:
            llm_result = await self.llm.analyze(profile, tender, baseline.criteria, baseline.eliminatory, now)
        except LLMError as exc:
            logger.warning("Repli sur l'analyse déterministe pour l'avis %s : %s", tender.idweb, exc)
            return baseline

        criteria = _merge_criteria(baseline.criteria, llm_result)
        flags = _merge_flags(baseline.eliminatory, llm_result)
        score, decision = finalize(criteria, flags)
        # Le LLM peut tempérer un « Go », jamais transformer seul un avis en « Go ».
        if decision == Decision.GO and llm_result.decision != "go":
            decision = Decision.A_VERIFIER
        date_limite = tender.date_limite or llm_result.parsed_deadline()
        budget = tender.budget_estime if tender.budget_estime is not None else llm_result.budget_estime
        enriched = tender.model_copy(update={"date_limite": date_limite, "budget_estime": budget})
        fallback_summary = build_summary(enriched, criteria, flags, score, decision, now)
        return TenderAnalysis(
            idweb=tender.idweb, score=score, decision=decision, criteria=criteria, eliminatory=flags,
            summary=_five_lines(llm_result.resume, fallback_summary),
            date_limite=date_limite, budget_estime=budget,
            analysis_source="llm", model=self.llm.model,
        )
