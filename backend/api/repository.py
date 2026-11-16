"""Accès aux données : toutes les requêtes SQL de l'application."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from backend.collector.models import Lot, Tender
from backend.scoring.models import TenderAnalysis
from backend.scoring.profile import CompanyProfile

Executor = asyncpg.Pool | asyncpg.Connection

PROFILE_FIELDS = [
    "name", "description", "skills", "keywords_include", "keywords_exclude", "cpv_codes", "departments",
    "certifications", "annual_revenue_eur", "min_contract_eur", "max_contract_eur", "min_response_days",
    "eliminatory_criteria", "alert_threshold", "digest_email", "is_active",
]
NUMERIC_FIELDS = {"annual_revenue_eur", "min_contract_eur", "max_contract_eur", "budget_estime"}

OPPORTUNITY_COLUMNS = """
    s.id, s.profile_id, s.tenant_id, s.score, s.decision, s.criteria, s.eliminatory, s.summary,
    s.analysis_source, s.model, s.status, s.status_updated_at, s.scored_at,
    COALESCE(s.date_limite, t.date_limite) AS date_limite,
    COALESCE(s.budget_estime, t.budget_estime) AS budget_estime,
    t.idweb, t.objet, t.acheteur, t.procedure, t.type_marche, t.departments, t.cpv_codes,
    t.url_avis, t.date_parution, t.lots
"""


def _row(record: asyncpg.Record | None) -> dict[str, Any] | None:
    """Convertit une ligne en dict, avec les NUMERIC en float."""
    if record is None:
        return None
    data = dict(record)
    for field in NUMERIC_FIELDS & data.keys():
        if data[field] is not None:
            data[field] = float(data[field])
    return data


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "tp_" + secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- tenants

async def create_tenant(db: Executor, name: str, contact_email: str | None) -> tuple[dict[str, Any], str]:
    api_key = generate_api_key()
    record = await db.fetchrow(
        "INSERT INTO tenants (name, contact_email, api_key_hash) VALUES ($1, $2, $3) "
        "RETURNING id, name, contact_email, is_active, created_at",
        name, contact_email, hash_api_key(api_key),
    )
    return dict(record), api_key


async def rotate_tenant_key(db: Executor, tenant_id: UUID) -> tuple[dict[str, Any], str] | None:
    api_key = generate_api_key()
    record = await db.fetchrow(
        "UPDATE tenants SET api_key_hash = $2 WHERE id = $1 RETURNING id, name, contact_email, is_active, created_at",
        tenant_id, hash_api_key(api_key),
    )
    return (dict(record), api_key) if record else None


async def list_tenants(db: Executor) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT id, name, contact_email, is_active, created_at FROM tenants ORDER BY name")
    return [dict(r) for r in rows]


async def get_tenant(db: Executor, tenant_id: UUID) -> dict[str, Any] | None:
    record = await db.fetchrow("SELECT id, name, contact_email, is_active, created_at FROM tenants WHERE id = $1", tenant_id)
    return dict(record) if record else None


async def get_tenant_by_api_key(db: Executor, api_key: str) -> dict[str, Any] | None:
    record = await db.fetchrow(
        "SELECT id, name, contact_email, is_active, created_at FROM tenants WHERE api_key_hash = $1 AND is_active",
        hash_api_key(api_key),
    )
    return dict(record) if record else None


async def delete_tenant(db: Executor, tenant_id: UUID) -> bool:
    return await db.execute("DELETE FROM tenants WHERE id = $1", tenant_id) == "DELETE 1"


# --------------------------------------------------------------------------- profils

async def create_profile(db: Executor, tenant_id: UUID, profile: CompanyProfile) -> dict[str, Any]:
    data = profile.model_dump()
    columns = ", ".join(PROFILE_FIELDS)
    placeholders = ", ".join(f"${i}" for i in range(2, len(PROFILE_FIELDS) + 2))
    record = await db.fetchrow(
        f"INSERT INTO company_profiles (tenant_id, {columns}) VALUES ($1, {placeholders}) RETURNING *",
        tenant_id, *[data[field] for field in PROFILE_FIELDS],
    )
    return _row(record)


async def update_profile(db: Executor, tenant_id: UUID, profile_id: UUID, profile: CompanyProfile) -> dict[str, Any] | None:
    data = profile.model_dump()
    assignments = ", ".join(f"{field} = ${i}" for i, field in enumerate(PROFILE_FIELDS, start=3))
    record = await db.fetchrow(
        f"UPDATE company_profiles SET {assignments}, updated_at = now() WHERE id = $1 AND tenant_id = $2 RETURNING *",
        profile_id, tenant_id, *[data[field] for field in PROFILE_FIELDS],
    )
    return _row(record)


async def list_profiles(db: Executor, tenant_id: UUID) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT * FROM company_profiles WHERE tenant_id = $1 ORDER BY name", tenant_id)
    return [_row(r) for r in rows]


async def list_active_profiles(db: Executor) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT p.*, t.name AS tenant_name FROM company_profiles p JOIN tenants t ON t.id = p.tenant_id "
        "WHERE p.is_active AND t.is_active ORDER BY p.created_at"
    )
    return [_row(r) for r in rows]


async def get_profile(db: Executor, tenant_id: UUID, profile_id: UUID) -> dict[str, Any] | None:
    record = await db.fetchrow("SELECT * FROM company_profiles WHERE id = $1 AND tenant_id = $2", profile_id, tenant_id)
    return _row(record)


async def delete_profile(db: Executor, tenant_id: UUID, profile_id: UUID) -> bool:
    result = await db.execute("DELETE FROM company_profiles WHERE id = $1 AND tenant_id = $2", profile_id, tenant_id)
    return result == "DELETE 1"


def profile_from_row(row: dict[str, Any]) -> CompanyProfile:
    return CompanyProfile(**{field: row[field] for field in PROFILE_FIELDS})


# --------------------------------------------------------------------------- avis

def tender_from_row(row: dict[str, Any]) -> Tender:
    return Tender(
        idweb=row["idweb"], objet=row["objet"], acheteur=row["acheteur"], famille=row["famille"],
        nature=row["nature"], procedure=row["procedure"], type_marche=row["type_marche"],
        departments=row["departments"], cpv_codes=row["cpv_codes"], descripteurs=row["descripteurs"],
        date_parution=row["date_parution"], date_limite=row["date_limite"], budget_estime=row["budget_estime"],
        url_avis=row["url_avis"], full_text=row["full_text"], lots=[Lot(**lot) for lot in row["lots"]],
        content_hash=row["content_hash"],
    )


async def upsert_tender(db: Executor, tender: Tender) -> tuple[int, str]:
    """Insère ou met à jour un avis (déduplication par `idweb`).

    Retourne (id, état) avec état ∈ {'nouveau', 'modifie', 'inchange'}.
    """
    existing = await db.fetchrow("SELECT id, content_hash FROM tenders WHERE idweb = $1", tender.idweb)
    if existing and existing["content_hash"] == tender.content_hash:
        return existing["id"], "inchange"
    record = await db.fetchrow(
        """
        INSERT INTO tenders (idweb, objet, acheteur, famille, nature, procedure, type_marche, departments, cpv_codes,
                             descripteurs, date_parution, date_limite, budget_estime, url_avis, full_text, lots, content_hash)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
        ON CONFLICT (idweb) DO UPDATE SET
            objet = EXCLUDED.objet, acheteur = EXCLUDED.acheteur, famille = EXCLUDED.famille, nature = EXCLUDED.nature,
            procedure = EXCLUDED.procedure, type_marche = EXCLUDED.type_marche, departments = EXCLUDED.departments,
            cpv_codes = EXCLUDED.cpv_codes, descripteurs = EXCLUDED.descripteurs, date_parution = EXCLUDED.date_parution,
            date_limite = EXCLUDED.date_limite, budget_estime = EXCLUDED.budget_estime, url_avis = EXCLUDED.url_avis,
            full_text = EXCLUDED.full_text, lots = EXCLUDED.lots, content_hash = EXCLUDED.content_hash, updated_at = now()
        RETURNING id
        """,
        tender.idweb, tender.objet, tender.acheteur, tender.famille, tender.nature, tender.procedure,
        tender.type_marche, tender.departments, tender.cpv_codes, tender.descripteurs, tender.date_parution,
        tender.date_limite, tender.budget_estime, tender.url_avis, tender.full_text,
        [lot.model_dump() for lot in tender.lots], tender.content_hash,
    )
    return record["id"], "modifie" if existing else "nouveau"


async def list_open_tenders(db: Executor, now: datetime, max_age_days: int = 90, limit: int = 5000) -> list[tuple[int, Tender]]:
    """Avis encore ouverts (date limite future ou inconnue), des plus récents aux plus anciens."""
    rows = await db.fetch(
        """
        SELECT * FROM tenders
        WHERE (date_limite IS NULL OR date_limite > $1)
          AND collected_at > $1 - make_interval(days => $2)
        ORDER BY date_parution DESC NULLS LAST, id DESC
        LIMIT $3
        """,
        now, max_age_days, limit,
    )
    return [(r["id"], tender_from_row(_row(r))) for r in rows]


# --------------------------------------------------------------------------- scores

async def upsert_score(db: Executor, tenant_id: UUID, profile_id: UUID, tender_id: int, analysis: TenderAnalysis) -> None:
    """Enregistre l'analyse ; le statut de suivi choisi par l'utilisateur est conservé en cas de ré-analyse."""
    await db.execute(
        """
        INSERT INTO tender_scores (tenant_id, profile_id, tender_id, score, decision, criteria, eliminatory, summary,
                                   date_limite, budget_estime, analysis_source, model)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (profile_id, tender_id) DO UPDATE SET
            score = EXCLUDED.score, decision = EXCLUDED.decision, criteria = EXCLUDED.criteria,
            eliminatory = EXCLUDED.eliminatory, summary = EXCLUDED.summary, date_limite = EXCLUDED.date_limite,
            budget_estime = EXCLUDED.budget_estime, analysis_source = EXCLUDED.analysis_source,
            model = EXCLUDED.model, scored_at = now()
        """,
        tenant_id, profile_id, tender_id, analysis.score, analysis.decision.value,
        [c.model_dump(mode="json") for c in analysis.criteria],
        [f.model_dump(mode="json") for f in analysis.eliminatory],
        analysis.summary, analysis.date_limite, analysis.budget_estime, analysis.analysis_source, analysis.model,
    )


async def current_timestamp(db: Executor) -> datetime:
    """Horloge de la base : sert de repère aux opérations qui comparent des `scored_at`."""
    return await db.fetchval("SELECT clock_timestamp()")


async def delete_untouched_scores(
    db: Executor, profile_id: UUID, keep_tender_ids: list[int], scored_before: datetime,
) -> None:
    """Après une ré-analyse : retire les scores jamais traités par l'utilisateur et devenus hors cible.

    Seuls les scores antérieurs au début de la ré-analyse (`scored_before`) sont concernés : un score
    écrit entre-temps par une collecte concurrente porte sur un avis que la ré-analyse n'a pas vu,
    il ne doit pas être effacé.
    """
    await db.execute(
        "DELETE FROM tender_scores WHERE profile_id = $1 AND status = 'nouveau' "
        "AND NOT (tender_id = ANY($2::bigint[])) AND scored_at < $3",
        profile_id, keep_tender_ids, scored_before,
    )


async def list_opportunities(
    db: Executor, tenant_id: UUID, profile_id: UUID, *, now: datetime, status: str | None = None,
    decision: str | None = None, min_score: int = 0, include_expired: bool = False,
    include_ignored: bool = False, limit: int = 100, offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conditions = ["s.tenant_id = $1", "s.profile_id = $2", "s.score >= $3"]
    params: list[Any] = [tenant_id, profile_id, min_score]
    if status:
        params.append(status)
        conditions.append(f"s.status = ${len(params)}")
    elif not include_ignored:
        conditions.append("s.status <> 'ignore'")
    if decision:
        params.append(decision)
        conditions.append(f"s.decision = ${len(params)}")
    if not include_expired:
        params.append(now)
        conditions.append(f"(COALESCE(s.date_limite, t.date_limite) IS NULL OR COALESCE(s.date_limite, t.date_limite) > ${len(params)})")
    where = " AND ".join(conditions)
    total = await db.fetchval(f"SELECT count(*) FROM tender_scores s JOIN tenders t ON t.id = s.tender_id WHERE {where}", *params)
    params.extend([limit, offset])
    rows = await db.fetch(
        f"""
        SELECT {OPPORTUNITY_COLUMNS}
        FROM tender_scores s JOIN tenders t ON t.id = s.tender_id
        WHERE {where}
        ORDER BY s.score DESC, COALESCE(s.date_limite, t.date_limite) ASC NULLS LAST, s.id DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return [_row(r) for r in rows], int(total)


async def opportunity_counts(db: Executor, tenant_id: UUID, profile_id: UUID, now: datetime) -> dict[str, int]:
    record = await db.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE s.decision = 'go') AS go,
               count(*) FILTER (WHERE s.decision = 'a_verifier') AS a_verifier,
               count(*) FILTER (WHERE s.decision = 'no_go') AS no_go,
               count(*) FILTER (WHERE s.status = 'nouveau') AS nouveau
        FROM tender_scores s JOIN tenders t ON t.id = s.tender_id
        WHERE s.tenant_id = $1 AND s.profile_id = $2 AND s.status <> 'ignore'
          AND (COALESCE(s.date_limite, t.date_limite) IS NULL OR COALESCE(s.date_limite, t.date_limite) > $3)
        """,
        tenant_id, profile_id, now,
    )
    return {key: int(value) for key, value in dict(record).items()}


async def get_opportunity(db: Executor, tenant_id: UUID, score_id: int) -> dict[str, Any] | None:
    record = await db.fetchrow(
        f"SELECT {OPPORTUNITY_COLUMNS}, t.full_text FROM tender_scores s JOIN tenders t ON t.id = s.tender_id "
        "WHERE s.id = $1 AND s.tenant_id = $2",
        score_id, tenant_id,
    )
    return _row(record)


async def update_opportunity_status(db: Executor, tenant_id: UUID, score_id: int, status: str) -> bool:
    result = await db.execute(
        "UPDATE tender_scores SET status = $3, status_updated_at = now() WHERE id = $1 AND tenant_id = $2",
        score_id, tenant_id, status,
    )
    return result == "UPDATE 1"


async def list_digest_candidates(db: Executor, tenant_id: UUID, profile_id: UUID, since: datetime | None) -> list[dict[str, Any]]:
    """Opportunités non ignorées du profil, éventuellement limitées à celles apparues depuis `since`."""
    rows = await db.fetch(
        f"""
        SELECT {OPPORTUNITY_COLUMNS}
        FROM tender_scores s JOIN tenders t ON t.id = s.tender_id
        WHERE s.tenant_id = $1 AND s.profile_id = $2 AND s.status <> 'ignore'
          AND ($3::timestamptz IS NULL OR s.first_scored_at >= $3)
        ORDER BY s.score DESC
        """,
        tenant_id, profile_id, since,
    )
    return [_row(r) for r in rows]


# --------------------------------------------------------------------------- collectes

async def create_run(db: Executor, trigger: str, filters: dict[str, Any]) -> dict[str, Any]:
    record = await db.fetchrow("INSERT INTO collection_runs (trigger, filters) VALUES ($1, $2) RETURNING *", trigger, filters)
    return dict(record)


async def finish_run(db: Executor, run_id: int, *, status: str, stats: dict[str, int], error: str | None = None) -> dict[str, Any]:
    record = await db.fetchrow(
        """
        UPDATE collection_runs SET status = $2, tenders_fetched = $3, tenders_new = $4, tenders_updated = $5,
               scores_written = $6, llm_calls = $7, error = $8, finished_at = now()
        WHERE id = $1 RETURNING *
        """,
        run_id, status, stats.get("tenders_fetched", 0), stats.get("tenders_new", 0), stats.get("tenders_updated", 0),
        stats.get("scores_written", 0), stats.get("llm_calls", 0), error,
    )
    return dict(record)


async def fail_interrupted_runs(db: Executor) -> None:
    await db.execute(
        "UPDATE collection_runs SET status = 'echec', error = 'Collecte interrompue par un redémarrage', finished_at = now() "
        "WHERE status = 'en_cours'"
    )


async def list_runs(db: Executor, limit: int = 20) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT * FROM collection_runs ORDER BY started_at DESC, id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def get_run(db: Executor, run_id: int) -> dict[str, Any] | None:
    record = await db.fetchrow("SELECT * FROM collection_runs WHERE id = $1", run_id)
    return dict(record) if record else None
