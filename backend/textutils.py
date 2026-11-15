"""Outils de normalisation de texte et d'extraction de montants (français)."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_WS_RE = re.compile(r"\s+")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", " ": " ", " ": " ", " ": " "})


def normalize(text: str | None) -> str:
    """Minuscule, sans accents, apostrophes et espaces unifiés."""
    if not text:
        return ""
    text = text.translate(_APOSTROPHES)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS_RE.sub(" ", stripped.lower()).strip()


@lru_cache(maxsize=4096)
def _keyword_pattern(keyword_norm: str) -> re.Pattern[str]:
    tokens = [re.escape(tok) for tok in keyword_norm.split(" ") if tok]
    # Tolère les pluriels simples sur chaque mot et les séparateurs variables.
    body = r"[\s\-']+".join(tok + r"(?:s|x|es)?" for tok in tokens)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


def keyword_in(keyword: str, normalized_text: str) -> bool:
    """Teste la présence d'un mot-clé (mot entier, pluriel toléré) dans un texte déjà normalisé."""
    kw = normalize(keyword)
    if not kw:
        return False
    return _keyword_pattern(kw).search(normalized_text) is not None


def find_keywords(keywords: list[str], normalized_text: str) -> list[str]:
    """Retourne les mots-clés présents, sans doublon, dans l'ordre fourni."""
    found: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        key = normalize(kw)
        if key and key not in seen and keyword_in(kw, normalized_text):
            seen.add(key)
            found.append(kw.strip())
    return found


def clean_list(values: list[str] | None) -> list[str]:
    """Nettoie une liste de libellés : espaces, vides et doublons (insensible à la casse/accents)."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _WS_RE.sub(" ", str(value)).strip()
        key = normalize(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def normalize_department(code: str) -> str:
    """'1' -> '01', '2a' -> '2A', '974' -> '974'."""
    code = str(code).strip().upper()
    if code.isdigit() and len(code) == 1:
        return "0" + code
    return code


def cpv_matches(profile_codes: list[str], tender_codes: list[str]) -> list[str]:
    """Codes CPV de l'avis couverts par un préfixe CPV du profil (zéros de fin ignorés)."""
    prefixes = []
    for code in profile_codes:
        digits = re.sub(r"\D", "", code)[:8]
        stem = digits.rstrip("0")
        if len(stem) >= 2:
            prefixes.append(stem)
        elif digits:
            prefixes.append(digits[:2])
    matched = []
    for code in tender_codes:
        digits = re.sub(r"\D", "", code)[:8]
        if digits and any(digits.startswith(p) for p in prefixes) and digits not in matched:
            matched.append(digits)
    return matched


_AMOUNT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:[ .]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>millions? d'euros|millions? d'eur|millions?|meur|m€|md€|keur|k€|k euros|euros?|eur|€)"
    r"(?![a-z0-9])"
)


def _to_number(raw: str) -> float:
    raw = raw.strip()
    if re.fullmatch(r"\d{1,3}(?:[ .]\d{3})+(?:,\d+)?", raw):
        raw = raw.replace(" ", "").replace(".", "")
    return float(raw.replace(" ", "").replace(",", "."))


def parse_amounts(normalized_text: str) -> list[tuple[int, float]]:
    """Extrait (position, montant en euros) de tous les montants d'un texte normalisé."""
    results: list[tuple[int, float]] = []
    for match in _AMOUNT_RE.finditer(normalized_text):
        try:
            value = _to_number(match.group("num"))
        except ValueError:
            continue
        unit = match.group("unit")
        if unit.startswith("million") or unit in {"meur", "m€"}:
            value *= 1_000_000
        elif unit == "md€":
            value *= 1_000_000_000
        elif unit in {"keur", "k€", "k euros"}:
            value *= 1_000
        results.append((match.start(), value))
    return results


def format_eur(amount: float | None) -> str:
    if amount is None:
        return "non précisé"
    return f"{amount:,.0f}".replace(",", " ") + " €"
