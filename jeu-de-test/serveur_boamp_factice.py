#!/usr/bin/env python3
"""serveur_boamp_factice.py — sert les avis du jeu de test à la place de l'API du BOAMP.

    python3 jeu-de-test/serveur_boamp_factice.py             (port 8099)

TenderPulse interroge alors ce serveur au lieu du vrai BOAMP si son `.env` contient :
    BOAMP_BASE_URL=http://host.docker.internal:8099

Le serveur reproduit la seule route utilisée par la collecte (pagination par `offset` et `limit`) :
    GET /api/explore/v2.1/catalog/datasets/boamp/records -> {"total_count": N, "results": [...]}

Les avis sont datés par rapport au 20/11/2026. À chaque réponse, toutes leurs dates sont décalées
du nombre de jours écoulés depuis : une date limite « dans 30 jours » le reste, quel que soit le jour
où vous testez. Bibliothèque standard uniquement.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ICI = Path(__file__).resolve().parent
REFERENCE = date(2026, 11, 20)
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def charger(dossier: Path) -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(dossier.glob("*.json"))]


def _decaler_valeur(valeur: Any, jours: int) -> Any:
    if isinstance(valeur, str):
        trouve = _DATE.match(valeur)
        if trouve:
            nouvelle = date.fromisoformat(trouve.group(1)) + timedelta(days=jours)
            return nouvelle.isoformat() + valeur[10:]
        return valeur
    if isinstance(valeur, dict):
        return {cle: _decaler_valeur(v, jours) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_decaler_valeur(v, jours) for v in valeur]
    return valeur


def decaler(avis: dict, jours: int) -> dict:
    """Décale toutes les dates d'un avis, y compris dans l'avis complet sérialisé (`donnees`)."""
    decale = _decaler_valeur({k: v for k, v in avis.items() if k != "donnees"}, jours)
    decale["donnees"] = json.dumps(_decaler_valeur(json.loads(avis["donnees"]), jours), ensure_ascii=False)
    return decale


def ecart_avec_reference(aujourdhui: date | None = None) -> int:
    return ((aujourdhui or datetime.now(timezone.utc).date()) - REFERENCE).days


def page(avis: list[dict], offset: int, limite: int, jours: int) -> dict:
    return {"total_count": len(avis), "results": [decaler(a, jours) for a in avis[offset: offset + limite]]}


def creer_gestionnaire(avis: list[dict]):
    class Gestionnaire(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if not url.path.endswith("/records"):
                self.send_error(404)
                return
            parametres = parse_qs(url.query)
            corps = json.dumps(page(avis, int(parametres.get("offset", ["0"])[0]), int(parametres.get("limit", ["100"])[0]),
                                    ecart_avec_reference()), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

    return Gestionnaire


def main() -> None:
    parseur = argparse.ArgumentParser(description="Serveur BOAMP factice pour le jeu de test de TenderPulse.")
    parseur.add_argument("--port", type=int, default=8099)
    parseur.add_argument("--hote", default="0.0.0.0", help="0.0.0.0 pour être joignable depuis les conteneurs Docker")
    args = parseur.parse_args()
    avis = charger(ICI / "avis")
    serveur = ThreadingHTTPServer((args.hote, args.port), creer_gestionnaire(avis))
    print(f"BOAMP factice : {len(avis)} avis sur le port {args.port}, dates décalées de {ecart_avec_reference()} jour(s). "
          "Ctrl+C pour arrêter.", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
