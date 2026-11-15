"""Structures de résultat du moteur de scoring."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Decision(str, Enum):
    GO = "go"
    A_VERIFIER = "a_verifier"
    NO_GO = "no_go"


DECISION_LABELS = {Decision.GO: "Go", Decision.A_VERIFIER: "À vérifier", Decision.NO_GO: "No-Go"}


class Severity(str, Enum):
    BLOQUANT = "bloquant"
    A_VERIFIER = "a_verifier"


class EliminatoryType(str, Enum):
    CHIFFRE_AFFAIRES = "chiffre_affaires"
    CERTIFICATION = "certification"
    ZONE = "zone"
    DELAI = "delai"
    BUDGET = "budget"
    PERSONNALISE = "personnalise"
    AUTRE = "autre"


class CriterionScore(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0)
    max_score: int = Field(gt=0)
    justification: str


class EliminatoryFlag(BaseModel):
    type: EliminatoryType
    label: str
    detail: str
    severity: Severity
    source: str = "regles"  # "regles" (détection déterministe) ou "llm"


class PrefilterResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    matched_cpv: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)


class TenderAnalysis(BaseModel):
    """Résultat complet de l'analyse d'un avis pour un profil."""

    idweb: str
    score: int = Field(ge=0, le=100)
    decision: Decision
    criteria: list[CriterionScore]
    eliminatory: list[EliminatoryFlag]
    summary: str
    date_limite: datetime | None = None
    budget_estime: float | None = None
    analysis_source: str = "heuristique"  # "heuristique" ou "llm"
    model: str | None = None

    @property
    def has_blocking_flag(self) -> bool:
        return any(flag.severity == Severity.BLOQUANT for flag in self.eliminatory)
