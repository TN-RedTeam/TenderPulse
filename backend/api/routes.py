"""Endpoints REST de TenderPulse."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse

from backend.api import repository as repo
from backend.api.schemas import (
    CollectionRunOut, CollectRequest, DigestSendOut, FollowUpStatus, MeOut, OpportunityCounts, OpportunityDetail,
    OpportunityList, OpportunityOut, ProfileOut, RescoreOut, StatusUpdate, TenantCreate, TenantCreated, TenantOut,
)
from backend.api.services import CollectionBusyError, TenderPulseService, filters_from_request, has_custom_filters
from backend.scoring.models import Decision
from backend.scoring.profile import CompanyProfile

router = APIRouter(prefix="/api")


@dataclass(frozen=True)
class Principal:
    role: str  # "admin" ou "tenant"
    tenant: dict[str, Any] | None = None


def get_service(request: Request) -> TenderPulseService:
    return request.app.state.service


async def get_principal(
    service: TenderPulseService = Depends(get_service),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """Authentifie l'appelant : clé d'administration (opérateur) ou clé d'un client (tenant)."""
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "En-tête X-API-Key manquant")
    if hmac.compare_digest(x_api_key.encode(), service.settings.admin_api_key.encode()):
        return Principal(role="admin")
    tenant = await repo.get_tenant_by_api_key(service.pool, x_api_key)
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé d'API invalide")
    return Principal(role="tenant", tenant=tenant)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé à l'administrateur")
    return principal


async def tenant_scope(
    tenant_id: UUID, principal: Principal = Depends(get_principal), service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    """Garantit l'isolation multi-tenant : un client n'accède qu'à ses propres données."""
    if principal.role == "tenant":
        if principal.tenant is None or principal.tenant["id"] != tenant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès refusé à ce client")
        return principal.tenant
    tenant = await repo.get_tenant(service.pool, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client introuvable")
    return tenant


async def _profile_or_404(service: TenderPulseService, tenant_id: UUID, profile_id: UUID) -> dict[str, Any]:
    profile = await repo.get_profile(service.pool, tenant_id, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")
    return profile


# --------------------------------------------------------------------------- général

@router.get("/health")
async def health(service: TenderPulseService = Depends(get_service)) -> dict[str, Any]:
    await service.pool.fetchval("SELECT 1")
    return {
        "status": "ok",
        "llm_provider": service.settings.llm_provider,
        "collection_running": service.collection_running,
        "next_collection_at": service.next_run_at(datetime.now(timezone.utc)).isoformat() if service.settings.collect_enabled else None,
    }


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(get_principal)) -> MeOut:
    return MeOut(role=principal.role, tenant=TenantOut(**principal.tenant) if principal.tenant else None)


# --------------------------------------------------------------------------- clients (tenants)

@router.get("/tenants", response_model=list[TenantOut], dependencies=[Depends(require_admin)])
async def list_tenants(service: TenderPulseService = Depends(get_service)) -> list[dict[str, Any]]:
    return await repo.list_tenants(service.pool)


@router.post("/tenants", response_model=TenantCreated, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_tenant(payload: TenantCreate, service: TenderPulseService = Depends(get_service)) -> dict[str, Any]:
    try:
        tenant, api_key = await repo.create_tenant(service.pool, payload.name, payload.contact_email)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Un client porte déjà ce nom") from None
    return {**tenant, "api_key": api_key}


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant: dict[str, Any] = Depends(tenant_scope)) -> dict[str, Any]:
    return tenant


@router.post("/tenants/{tenant_id}/rotate-key", response_model=TenantCreated, dependencies=[Depends(require_admin)])
async def rotate_key(tenant_id: UUID, service: TenderPulseService = Depends(get_service)) -> dict[str, Any]:
    rotated = await repo.rotate_tenant_key(service.pool, tenant_id)
    if rotated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client introuvable")
    tenant, api_key = rotated
    return {**tenant, "api_key": api_key}


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_tenant(tenant_id: UUID, service: TenderPulseService = Depends(get_service)) -> Response:
    if not await repo.delete_tenant(service.pool, tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client introuvable")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- profils

@router.get("/tenants/{tenant_id}/profiles", response_model=list[ProfileOut])
async def list_profiles(tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service)) -> list[dict[str, Any]]:
    return await repo.list_profiles(service.pool, tenant["id"])


@router.post("/tenants/{tenant_id}/profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: CompanyProfile, tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    try:
        profile = await repo.create_profile(service.pool, tenant["id"], payload)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce client a déjà un profil portant ce nom") from None
    service.spawn(service.rescore_profile(tenant["id"], profile["id"]))
    return profile


@router.get("/tenants/{tenant_id}/profiles/{profile_id}", response_model=ProfileOut)
async def get_profile(
    profile_id: UUID, tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    return await _profile_or_404(service, tenant["id"], profile_id)


@router.put("/tenants/{tenant_id}/profiles/{profile_id}", response_model=ProfileOut)
async def update_profile(
    profile_id: UUID, payload: CompanyProfile, tenant: dict[str, Any] = Depends(tenant_scope),
    service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    try:
        profile = await repo.update_profile(service.pool, tenant["id"], profile_id, payload)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce client a déjà un profil portant ce nom") from None
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")
    service.spawn(service.rescore_profile(tenant["id"], profile_id))
    return profile


@router.delete("/tenants/{tenant_id}/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: UUID, tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> Response:
    if not await repo.delete_profile(service.pool, tenant["id"], profile_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tenants/{tenant_id}/profiles/{profile_id}/rescore", response_model=RescoreOut)
async def rescore_profile(
    profile_id: UUID, tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> dict[str, int]:
    await _profile_or_404(service, tenant["id"], profile_id)
    return await service.rescore_profile(tenant["id"], profile_id)


# --------------------------------------------------------------------------- opportunités

@router.get("/tenants/{tenant_id}/profiles/{profile_id}/opportunities", response_model=OpportunityList)
async def list_opportunities(
    profile_id: UUID,
    follow_up: FollowUpStatus | None = Query(default=None, alias="status", description="Filtre sur le statut de suivi"),
    decision: Decision | None = Query(default=None),
    min_score: int = Query(default=0, ge=0, le=100),
    include_expired: bool = Query(default=False),
    include_ignored: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant: dict[str, Any] = Depends(tenant_scope),
    service: TenderPulseService = Depends(get_service),
) -> OpportunityList:
    """Opportunités du profil, triées par score décroissant."""
    await _profile_or_404(service, tenant["id"], profile_id)
    now = datetime.now(timezone.utc)
    items, total = await repo.list_opportunities(
        service.pool, tenant["id"], profile_id, now=now, status=follow_up.value if follow_up else None,
        decision=decision.value if decision else None, min_score=min_score, include_expired=include_expired,
        include_ignored=include_ignored, limit=limit, offset=offset,
    )
    counts = await repo.opportunity_counts(service.pool, tenant["id"], profile_id, now)
    return OpportunityList(items=[OpportunityOut(**item) for item in items], total=total, counts=OpportunityCounts(**counts))


@router.get("/tenants/{tenant_id}/opportunities/{opportunity_id}", response_model=OpportunityDetail)
async def get_opportunity(
    opportunity_id: int, tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    opportunity = await repo.get_opportunity(service.pool, tenant["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunité introuvable")
    return opportunity


@router.patch("/tenants/{tenant_id}/opportunities/{opportunity_id}", response_model=OpportunityDetail)
async def update_opportunity_status(
    opportunity_id: int, payload: StatusUpdate, tenant: dict[str, Any] = Depends(tenant_scope),
    service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    """Met à jour le statut de suivi : nouveau, a_etudier, go ou ignore."""
    if not await repo.update_opportunity_status(service.pool, tenant["id"], opportunity_id, payload.status.value):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunité introuvable")
    return await repo.get_opportunity(service.pool, tenant["id"], opportunity_id)


# --------------------------------------------------------------------------- digest

@router.get("/tenants/{tenant_id}/profiles/{profile_id}/digest", response_class=HTMLResponse)
async def get_digest(
    profile_id: UUID,
    since_hours: int = Query(default=24, ge=0, le=720, description="Fenêtre en heures ; 0 = toutes les consultations ouvertes"),
    tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> HTMLResponse:
    """Digest HTML prêt à être envoyé par e-mail (opportunités au-dessus du seuil du profil)."""
    built = await service.build_digest(tenant["id"], profile_id, since_hours or None)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")
    html, subject, count, _ = built
    return HTMLResponse(html, headers={"X-Digest-Count": str(count), "Content-Disposition": 'inline; filename="digest-tenderpulse.html"'})


@router.post("/tenants/{tenant_id}/profiles/{profile_id}/digest/send", response_model=DigestSendOut)
async def send_digest(
    profile_id: UUID, since_hours: int = Query(default=24, ge=0, le=720),
    tenant: dict[str, Any] = Depends(tenant_scope), service: TenderPulseService = Depends(get_service),
) -> dict[str, Any]:
    result = await service.send_digest(tenant["id"], profile_id, since_hours or None)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")
    return result


# --------------------------------------------------------------------------- collecte

@router.post("/collect", response_model=CollectionRunOut, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_admin)])
async def trigger_collection(payload: CollectRequest | None = None, service: TenderPulseService = Depends(get_service)) -> dict[str, Any]:
    """Déclenche une collecte BOAMP en tâche de fond ; suivre l'avancement via GET /api/collect/runs/{id}."""
    body = payload.model_dump() if payload else {}
    try:
        if has_custom_filters(body) or body.get("max_records"):
            filters = filters_from_request(body, service.settings.collect_max_records)
            if not has_custom_filters(body):
                defaults = await service.default_filters()
                filters = defaults.model_copy(update={"max_records": filters.max_records})
        else:
            filters = None
        return await service.start_collection(filters, "manuel")
    except CollectionBusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("/collect/runs", response_model=list[CollectionRunOut], dependencies=[Depends(require_admin)])
async def list_runs(limit: int = Query(default=20, ge=1, le=100), service: TenderPulseService = Depends(get_service)) -> list[dict[str, Any]]:
    return await repo.list_runs(service.pool, limit)


@router.get("/collect/runs/{run_id}", response_model=CollectionRunOut, dependencies=[Depends(require_admin)])
async def get_run(run_id: int, service: TenderPulseService = Depends(get_service)) -> dict[str, Any]:
    run = await repo.get_run(service.pool, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collecte introuvable")
    return run
