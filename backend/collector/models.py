"""Modèles de données du collecteur BOAMP."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from backend.textutils import clean_list, cpv_matches, find_keywords, normalize, normalize_department


class Lot(BaseModel):
    numero: str = ""
    intitule: str = ""
    description: str = ""
    cpv_codes: list[str] = Field(default_factory=list)
    budget_estime: float | None = None


class Tender(BaseModel):
    """Avis de marché normalisé, indépendant du format source (eForms, FNSimple, MAPA)."""

    idweb: str
    objet: str = ""
    acheteur: str = ""
    famille: str = ""
    nature: str = ""
    procedure: str = ""
    type_marche: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    cpv_codes: list[str] = Field(default_factory=list)
    descripteurs: list[str] = Field(default_factory=list)
    date_parution: date | None = None
    date_limite: datetime | None = None
    budget_estime: float | None = None
    url_avis: str = ""
    full_text: str = ""
    lots: list[Lot] = Field(default_factory=list)
    content_hash: str = ""

    def searchable_text(self) -> str:
        """Texte normalisé (objet + descripteurs + texte complet) pour la recherche de mots-clés."""
        return normalize(" \n ".join([self.objet, " ".join(self.descripteurs), self.full_text]))


class CollectFilters(BaseModel):
    """Filtres configurables d'une collecte BOAMP."""

    cpv_codes: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    natures: list[str] = Field(default_factory=lambda: ["APPEL_OFFRE"])
    max_records: int = Field(default=5000, ge=1, le=100000)

    @field_validator("cpv_codes", "keywords", "natures")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return clean_list(value)

    @field_validator("departments")
    @classmethod
    def _clean_departments(cls, value: list[str]) -> list[str]:
        return clean_list([normalize_department(v) for v in value])

    def resolved_dates(self, today: date, lookback_days: int = 2) -> tuple[date, date]:
        date_to = self.date_to or today
        date_from = self.date_from or (date_to - timedelta(days=lookback_days))
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    def matches(self, tender: Tender) -> bool:
        """Contrôle local des filtres : garantit le résultat même si l'API filtre plus large."""
        if self.departments and tender.departments:
            if not set(self.departments) & set(tender.departments):
                return False
        if self.natures and tender.nature and tender.nature not in self.natures:
            return False
        if not self.keywords and not self.cpv_codes:
            return True
        if self.cpv_codes and cpv_matches(self.cpv_codes, tender.cpv_codes):
            return True
        if self.keywords and find_keywords(self.keywords, tender.searchable_text()):
            return True
        return False
