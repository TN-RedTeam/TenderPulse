"""Transformation d'un enregistrement brut de l'API BOAMP en `Tender` normalisé.

Le champ `donnees` contient l'avis complet sous forme JSON, dans un format qui dépend
de la famille de l'avis (eForms européen, FNSimple national, MAPA, formats historiques).
Le parser combine des extracteurs ciblés (CPV, lots, budget) et un aplatissement générique
qui récupère tout le texte rédigé, quel que soit le format.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from backend.collector.models import Lot, Tender
from backend.textutils import normalize, normalize_department, parse_amounts

PARIS = ZoneInfo("Europe/Paris")
MAX_FULL_TEXT_CHARS = 60000

_CPV_RE = re.compile(r"(?<!\d)(\d{8})(?:-\d)?(?!\d)")
_URL_OR_MAIL_RE = re.compile(r"^(https?://|www\.)|^[^\s@]+@[^\s@]+\.[a-z]{2,}$", re.IGNORECASE)
_BUDGET_HINT_RE = re.compile(
    r"(valeur estimee|montant estime|montant previsionnel|estimation|budget|montant maximum|montant total|enveloppe)"
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text_of(value: Any) -> str:
    """Valeur textuelle d'un nœud JSON issu de XML (objet '#text', chaîne ou nombre)."""
    if isinstance(value, dict):
        return _text_of(value.get("#text"))
    if isinstance(value, list):
        return " ".join(t for t in (_text_of(v) for v in value) if t)
    if value is None:
        return ""
    return str(value).strip()


def _load_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _iter_leaves(node: Any, key: str = "") -> Iterator[tuple[str, str]]:
    """Parcours en profondeur : (clé du parent, valeur texte) pour chaque feuille."""
    if isinstance(node, dict):
        for child_key, child in node.items():
            if child_key.startswith("@"):
                continue
            yield from _iter_leaves(child, key if child_key == "#text" else child_key)
    elif isinstance(node, list):
        for child in node:
            yield from _iter_leaves(child, key)
    elif isinstance(node, str):
        yield key, node
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield key, str(node)


def _is_prose(value: str) -> bool:
    value = value.strip()
    if len(value) < 8 or " " not in value:
        return False
    if _URL_OR_MAIL_RE.search(value):
        return False
    return any(ch.isalpha() for ch in value)


def _collect_prose(node: Any, limit: int = MAX_FULL_TEXT_CHARS) -> list[str]:
    """Tous les textes rédigés d'un sous-arbre, dédoublonnés, dans l'ordre du document."""
    seen: set[str] = set()
    parts: list[str] = []
    size = 0
    for _, value in _iter_leaves(node):
        value = re.sub(r"\s+", " ", value).strip()
        if not _is_prose(value):
            continue
        fingerprint = normalize(value)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        parts.append(value)
        size += len(value) + 1
        if size >= limit:
            break
    return parts


def _collect_cpv(node: Any, under_cpv_key: bool = False) -> list[str]:
    """Codes CPV : nœuds eForms `@listName=cpv` et toute clé contenant 'cpv' (formats nationaux)."""
    found: list[str] = []
    if isinstance(node, dict):
        if str(node.get("@listName", "")).lower() == "cpv":
            found.extend(_CPV_RE.findall(_text_of(node)))
        for key, child in node.items():
            if key.startswith("@"):
                continue
            found.extend(_collect_cpv(child, under_cpv_key or "cpv" in key.lower()))
    elif isinstance(node, list):
        for child in node:
            found.extend(_collect_cpv(child, under_cpv_key))
    elif under_cpv_key and isinstance(node, (str, int)):
        found.extend(_CPV_RE.findall(str(node)))
    return list(dict.fromkeys(found))


def _to_float(raw: Any) -> float | None:
    text = _text_of(raw).replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _find_key(node: Any, wanted: str) -> Iterator[Any]:
    """Toutes les valeurs associées à une clé (comparaison insensible à la casse, sans préfixe XML)."""
    if isinstance(node, dict):
        for key, child in node.items():
            if key.split(":")[-1].lower() == wanted:
                yield child
            yield from _find_key(child, wanted)
    elif isinstance(node, list):
        for child in node:
            yield from _find_key(child, wanted)


def _eforms_amount(project: Any) -> float | None:
    """Montant estimé d'un bloc `cac:ProcurementProject` eForms."""
    total = project.get("cac:RequestedTenderTotal") if isinstance(project, dict) else None
    if not total:
        return None
    for key in ("estimatedoverallcontractamount", "frameworkmaximumamount"):
        for candidate in _find_key(total, key):
            amount = _to_float(candidate)
            if amount:
                return amount
    return None


def _parse_eforms(notice: dict[str, Any]) -> tuple[list[Lot], float | None]:
    lots: list[Lot] = []
    for raw_lot in _as_list(notice.get("cac:ProcurementProjectLot")):
        if not isinstance(raw_lot, dict):
            continue
        project = raw_lot.get("cac:ProcurementProject") or {}
        numero = _text_of(project.get("cbc:ID")) or _text_of(raw_lot.get("cbc:ID"))
        lots.append(
            Lot(
                numero=numero,
                intitule=_text_of(project.get("cbc:Name")),
                description=_text_of(project.get("cbc:Description")),
                cpv_codes=_collect_cpv(project),
                budget_estime=_eforms_amount(project),
            )
        )
    budget = _eforms_amount(notice.get("cac:ProcurementProject") or {})
    if budget is None:
        lot_amounts = [lot.budget_estime for lot in lots if lot.budget_estime]
        budget = sum(lot_amounts) if lot_amounts else None
    return lots, budget


def _parse_national(root: Any) -> tuple[list[Lot], float | None]:
    """Formats nationaux (FNSimple, MAPA, formats historiques) : lots et valeur estimée."""
    lots: list[Lot] = []
    for container in _find_key(root, "lot"):
        for index, raw_lot in enumerate(_as_list(container), start=1):
            if not isinstance(raw_lot, dict):
                continue
            intitule = _text_of(raw_lot.get("intitule")) or _text_of(raw_lot.get("description"))
            prose = _collect_prose(raw_lot, limit=4000)
            description = " ".join(p for p in prose if normalize(p) != normalize(intitule))
            amount = None
            for candidate in _find_key(raw_lot, "valeur"):
                amount = _to_float(candidate)
                if amount:
                    break
            lots.append(
                Lot(
                    numero=_text_of(raw_lot.get("numLot")) or _text_of(raw_lot.get("num")) or str(index),
                    intitule=intitule,
                    description=description,
                    cpv_codes=_collect_cpv(raw_lot),
                    budget_estime=amount,
                )
            )
        if lots:
            break
    budget = None
    for estimated in _find_key(root, "valeurestimee"):
        budget = _to_float(estimated.get("valeur") if isinstance(estimated, dict) else estimated)
        if budget:
            break
    return lots, budget


def extract_budget_from_text(text: str) -> float | None:
    """Repli : montant le plus élevé cité juste après une mention de budget/estimation."""
    norm = normalize(text)
    best: float | None = None
    for hint in _BUDGET_HINT_RE.finditer(norm):
        window = norm[hint.end(): hint.end() + 160]
        for _, amount in parse_amounts(window):
            if amount >= 1000 and (best is None or amount > best):
                best = amount
    return best


def parse_datetime(raw: Any) -> datetime | None:
    """Date ISO de l'API ; une date sans fuseau est interprétée en heure de Paris."""
    text = _text_of(raw)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PARIS)
    return parsed.astimezone(timezone.utc)


def parse_date(raw: Any) -> date | None:
    text = _text_of(raw)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _str_list(raw: Any) -> list[str]:
    return [s for s in (_text_of(v) for v in _as_list(raw)) if s]


def parse_record(record: dict[str, Any]) -> Tender | None:
    """Convertit un enregistrement de l'API en `Tender`. Retourne None sans identifiant `idweb`."""
    idweb = _text_of(record.get("idweb"))
    if not idweb:
        return None

    donnees = _load_json(record.get("donnees"))
    lots: list[Lot] = []
    budget: float | None = None
    if isinstance(donnees, dict) and isinstance(donnees.get("EFORMS"), dict):
        notice = next((v for v in donnees["EFORMS"].values() if isinstance(v, dict)), {})
        lots, budget = _parse_eforms(notice)
    elif donnees:
        lots, budget = _parse_national(donnees)

    objet = re.sub(r"\s+", " ", _text_of(record.get("objet")))
    acheteur = re.sub(r"\s+", " ", _text_of(record.get("nomacheteur")))
    departments = [normalize_department(d) for d in _str_list(record.get("code_departement"))]
    descripteurs = _str_list(record.get("descripteur_libelle"))
    type_marche = _str_list(record.get("type_marche"))
    procedure = _text_of(record.get("procedure_libelle")) or _text_of(record.get("type_procedure"))
    date_limite = parse_datetime(record.get("datelimitereponse"))
    cpv_codes = _collect_cpv(donnees)

    header = [
        f"Objet : {objet}",
        f"Acheteur : {acheteur}",
        f"Procédure : {procedure}" if procedure else "",
        f"Type de marché : {', '.join(type_marche)}" if type_marche else "",
        f"Descripteurs : {', '.join(descripteurs)}" if descripteurs else "",
        f"Départements : {', '.join(departments)}" if departments else "",
        f"Codes CPV : {', '.join(cpv_codes)}" if cpv_codes else "",
        f"Date limite de réponse : {date_limite.astimezone(PARIS):%d/%m/%Y %H:%M}" if date_limite else "",
    ]
    lot_lines = []
    for lot in lots:
        parts = [lot.intitule] if lot.intitule else []
        if lot.description and normalize(lot.description) != normalize(lot.intitule):
            parts.append(lot.description)
        label = " — ".join(parts)
        lot_lines.append(f"Lot {lot.numero} : {label}".strip())
    body = _collect_prose(donnees)
    criteres = _text_of(record.get("criteres"))
    sections = [line for line in header if line]
    if lot_lines:
        sections.append("Lots :")
        sections.extend(lot_lines)
    if criteres:
        sections.append(f"Critères : {criteres}")
    if body:
        sections.append("Texte de l'avis :")
        sections.extend(body)
    full_text = "\n".join(sections)[:MAX_FULL_TEXT_CHARS]

    if budget is None:
        budget = extract_budget_from_text(full_text)

    digest = hashlib.sha256()
    for part in (idweb, objet, acheteur, full_text, str(date_limite), str(budget)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")

    return Tender(
        idweb=idweb,
        objet=objet,
        acheteur=acheteur,
        famille=_text_of(record.get("famille")),
        nature=_text_of(record.get("nature")),
        procedure=procedure,
        type_marche=type_marche,
        departments=departments,
        cpv_codes=cpv_codes,
        descripteurs=descripteurs,
        date_parution=parse_date(record.get("dateparution")),
        date_limite=date_limite,
        budget_estime=budget,
        url_avis=_text_of(record.get("url_avis")) or f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}",
        full_text=full_text,
        lots=lots,
        content_hash=digest.hexdigest(),
    )
