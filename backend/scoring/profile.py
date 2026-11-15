"""Profil d'entreprise d'une PME cliente : ce qu'elle sait faire, où, et ses limites."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.textutils import clean_list, normalize_department


class CompanyProfile(BaseModel):
    """Critères de recherche et de qualification d'une PME."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)

    # Compétences métier et ciblage
    skills: list[str] = Field(default_factory=list, description="Compétences métier, en langage libre")
    keywords_include: list[str] = Field(default_factory=list, description="Mots-clés recherchés dans les avis")
    keywords_exclude: list[str] = Field(default_factory=list, description="Mots-clés qui écartent un avis")
    cpv_codes: list[str] = Field(default_factory=list, description="Codes ou préfixes CPV ciblés")

    # Zones géographiques d'intervention (liste vide = France entière)
    departments: list[str] = Field(default_factory=list)

    # Certifications et qualifications détenues
    certifications: list[str] = Field(default_factory=list)

    # Capacités financières
    annual_revenue_eur: float | None = Field(default=None, ge=0, description="Chiffre d'affaires annuel")
    min_contract_eur: float | None = Field(default=None, ge=0, description="Montant de marché minimum intéressant")
    max_contract_eur: float | None = Field(default=None, ge=0, description="Montant de marché maximum supportable")

    # Critères éliminatoires propres à l'entreprise
    min_response_days: int = Field(default=7, ge=0, le=180, description="Délai minimum pour répondre, en jours")
    eliminatory_criteria: list[str] = Field(
        default_factory=list,
        description="Expressions qui, présentes dans un avis, constituent un motif d'abandon (ex. « visite obligatoire »)",
    )

    # Alerte
    alert_threshold: int = Field(default=60, ge=0, le=100, description="Score minimum pour figurer au digest")
    digest_email: str | None = Field(default=None, max_length=320)
    is_active: bool = True

    @field_validator("skills", "keywords_include", "keywords_exclude", "certifications", "eliminatory_criteria")
    @classmethod
    def _clean_labels(cls, value: list[str]) -> list[str]:
        return clean_list(value)

    @field_validator("cpv_codes")
    @classmethod
    def _clean_cpv(cls, value: list[str]) -> list[str]:
        codes = []
        for raw in clean_list(value):
            digits = "".join(ch for ch in raw.split("-")[0] if ch.isdigit())
            if len(digits) < 2 or len(digits) > 8:
                raise ValueError(f"Code CPV invalide : {raw!r} (2 à 8 chiffres attendus)")
            codes.append(digits)
        return list(dict.fromkeys(codes))

    @field_validator("departments")
    @classmethod
    def _clean_departments(cls, value: list[str]) -> list[str]:
        codes = []
        for raw in clean_list(value):
            code = normalize_department(raw)
            if not (code in {"2A", "2B"} or (code.isdigit() and len(code) in (2, 3))):
                raise ValueError(f"Code département invalide : {raw!r}")
            codes.append(code)
        return list(dict.fromkeys(codes))

    @field_validator("digest_email")
    @classmethod
    def _clean_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        local, _, domain = value.partition("@")
        if not local or "." not in domain or " " in value:
            raise ValueError("Adresse e-mail du digest invalide")
        return value

    def search_terms(self) -> list[str]:
        """Mots-clés inclus + compétences : tout ce qui signale un avis pertinent."""
        return clean_list(self.keywords_include + self.skills)
