"""Schémas d'entrée/sortie de l'API REST."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from backend.collector.models import Lot
from backend.scoring.models import CriterionScore, Decision, EliminatoryFlag
from backend.scoring.profile import CompanyProfile


class FollowUpStatus(str, Enum):
    NOUVEAU = "nouveau"
    A_ETUDIER = "a_etudier"
    GO = "go"
    IGNORE = "ignore"


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le nom du client est obligatoire")
        return value


class TenantOut(BaseModel):
    id: UUID
    name: str
    contact_email: str | None
    is_active: bool
    created_at: datetime


class TenantCreated(TenantOut):
    api_key: str = Field(description="Clé d'API du client, affichée une seule fois")


class MeOut(BaseModel):
    role: str
    tenant: TenantOut | None


class ProfileOut(CompanyProfile):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


class OpportunityOut(BaseModel):
    id: int
    profile_id: UUID
    idweb: str
    objet: str
    acheteur: str
    procedure: str
    type_marche: list[str]
    departments: list[str]
    cpv_codes: list[str]
    url_avis: str
    date_parution: date | None
    date_limite: datetime | None
    budget_estime: float | None
    score: int
    decision: Decision
    criteria: list[CriterionScore]
    eliminatory: list[EliminatoryFlag]
    summary: str
    analysis_source: str
    model: str | None
    status: FollowUpStatus
    status_updated_at: datetime | None
    scored_at: datetime
    lots: list[Lot]


class OpportunityDetail(OpportunityOut):
    full_text: str


class OpportunityCounts(BaseModel):
    total: int
    go: int
    a_verifier: int
    no_go: int
    nouveau: int


class OpportunityList(BaseModel):
    items: list[OpportunityOut]
    total: int
    counts: OpportunityCounts


class StatusUpdate(BaseModel):
    status: FollowUpStatus


class CollectRequest(BaseModel):
    """Filtres facultatifs d'une collecte manuelle (par défaut : périmètre des profils actifs)."""

    cpv_codes: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    max_records: int | None = Field(default=None, ge=1, le=100000)


class CollectionRunOut(BaseModel):
    id: int
    trigger: str
    status: str
    filters: dict[str, Any]
    tenders_fetched: int
    tenders_new: int
    tenders_updated: int
    scores_written: int
    llm_calls: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RescoreOut(BaseModel):
    tenders_examined: int
    scores_written: int


class DigestSendOut(BaseModel):
    sent: bool
    recipient: str | None
    opportunities: int
    detail: str
