"""Jeu d'avis BOAMP simulés, fidèles aux trois formats réels de l'API (eForms, FNSimple, MAPA).

La structure de chaque enregistrement reproduit celle renvoyée par
`boamp-datadila.opendatasoft.com` : champs d'indexation à plat et avis complet sérialisé
en JSON dans le champ `donnees`. Aucune donnée n'est récupérée sur le réseau.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# « Maintenant » figé pour des tests reproductibles.
NOW = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)


def _record(idweb: str, objet: str, acheteur: str, departments: list[str], famille: str, donnees: dict[str, Any],
            *, date_limite: str | None, descripteurs: list[str], type_marche: str = "TRAVAUX",
            dateparution: str = "2026-11-13") -> dict[str, Any]:
    return {
        "idweb": idweb,
        "objet": objet,
        "nomacheteur": acheteur,
        "famille": famille,
        "nature": "APPEL_OFFRE",
        "type_procedure": "OUVERT" if famille == "JOUE" else "PROCEDURE_ADAPTE",
        "procedure_libelle": "Procédure Ouverte" if famille == "JOUE" else "Procédure adaptée",
        "type_marche": [type_marche],
        "code_departement": departments,
        "descripteur_libelle": descripteurs,
        "dateparution": dateparution,
        "datelimitereponse": date_limite,
        "criteres": None,
        "donnees": json.dumps(donnees, ensure_ascii=False),
        "url_avis": f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}",
    }


def _eforms_lot(numero: str, name: str, description: str, cpv: str, amount: int) -> dict[str, Any]:
    return {
        "cbc:ID": {"@schemeName": "Lot", "#text": f"LOT-000{numero}"},
        "cac:TenderingTerms": {
            "cbc:VariantConstraintCode": {"@listName": "permission", "#text": "not-allowed"},
            "cac:AwardingTerms": {"cac:AwardingCriterion": {"cac:SubordinateAwardingCriterion": [
                {"cbc:AwardingCriterionTypeCode": {"@listName": "award-criterion-type", "#text": "price"},
                 "cbc:Description": {"@languageID": "FRA", "#text": "Prix des prestations : 40 %"}},
                {"cbc:AwardingCriterionTypeCode": {"@listName": "award-criterion-type", "#text": "quality"},
                 "cbc:Description": {"@languageID": "FRA", "#text": "Valeur technique de l'offre : 60 %"}},
            ]}},
        },
        "cac:TenderingProcess": {
            "cac:TenderSubmissionDeadlinePeriod": {"cbc:EndDate": "2026-12-15+01:00", "cbc:EndTime": "12:00:00+01:00"},
        },
        "cac:ProcurementProject": {
            "cbc:ID": numero,
            "cbc:Name": {"@languageID": "FRA", "#text": name},
            "cbc:Description": {"@languageID": "FRA", "#text": description},
            "cbc:ProcurementTypeCode": {"@listName": "contract-nature", "#text": "works"},
            "cac:RequestedTenderTotal": {"cbc:EstimatedOverallContractAmount": {"@currencyID": "EUR", "#text": str(amount)}},
            "cac:MainCommodityClassification": {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": cpv}},
        },
    }


# 1. Avis européen (eForms) parfaitement dans la cible du profil de test → attendu « Go ».
RENOVATION_ECOLE = _record(
    "26-200001",
    "Rénovation énergétique du groupe scolaire Jean Jaurès : isolation thermique par l'extérieur et menuiseries",
    "Ville de Villeurbanne", ["69"], "JOUE",
    {"EFORMS": {"ContractNotice": {
        "cac:ProcurementProject": {
            "cbc:ID": "2026-TRV-041",
            "cbc:Name": {"@languageID": "FRA", "#text": "Rénovation énergétique du groupe scolaire Jean Jaurès"},
            "cbc:Description": {"@languageID": "FRA", "#text": (
                "Travaux de rénovation énergétique du groupe scolaire Jean Jaurès comprenant l'isolation thermique "
                "par l'extérieur des façades et le remplacement des menuiseries extérieures. Les travaux sont "
                "réalisés en site occupé, pendant les vacances scolaires. Les entreprises titulaires de la mention "
                "RGE ou équivalent pourront en justifier dans leur candidature.")},
            "cbc:ProcurementTypeCode": {"@listName": "contract-nature", "#text": "works"},
            "cac:RequestedTenderTotal": {"cbc:EstimatedOverallContractAmount": {"@currencyID": "EUR", "#text": "480000"}},
            "cac:MainCommodityClassification": {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "45321000"}},
            "cac:RealizedLocation": {"cac:Address": {"cbc:CountrySubentityCode": {"@listName": "nuts-lvl3", "#text": "FRK26"}}},
        },
        "cac:ProcurementProjectLot": [
            _eforms_lot("1", "Isolation thermique par l'extérieur",
                        "Isolation thermique par l'extérieur de 2 400 m² de façades, enduit de finition.", "45321000", 310000),
            _eforms_lot("2", "Menuiseries extérieures",
                        "Remplacement de 86 menuiseries extérieures en aluminium à rupture de pont thermique.", "45421000", 170000),
        ],
    }}},
    date_limite="2026-12-15T11:00:00+00:00", descripteurs=["Isolation", "Menuiserie"],
)

# 2. Avis national (FNSimple) : chiffre d'affaires minimum exigé supérieur à celui de la PME → éliminatoire.
TOITURE_CA_MINIMUM = _record(
    "26-200002", "Réfection de la toiture et isolation de la salle polyvalente", "Commune de Bron", ["69"], "FNS",
    {"FNSimple": {
        "organisme": {"nomOfficiel": "Commune de Bron", "codeIdentificationNational": "21690029000019", "ville": "Bron", "cp": "69500"},
        "initial": {
            "communication": {"urlProfilAch": "https://marches.example.org/bron", "nomContact": "Service de la commande publique"},
            "procedure": {
                "capaciteExercice": "Lettre de candidature et déclaration du candidat (DC1 et DC2).",
                "capaciteEcoFin": ("Le candidat doit justifier d'un chiffre d'affaires annuel minimum de 5 000 000 euros "
                                   "HT sur les trois derniers exercices."),
                "capaciteTech": "Liste des travaux exécutés au cours des cinq dernières années, appuyée d'attestations de bonne exécution.",
                "dateReceptionOffres": "2026-12-18T12:00:00+01:00",
            },
            "natureMarche": {
                "intitule": "Réfection de la toiture et isolation de la salle polyvalente",
                "codeCPV": {"objetPrincipal": {"classPrincipale": "45261000"}},
                "natureMarche": {"travaux": ""},
                "description": "Dépose de la couverture existante, réfection complète de la toiture et isolation des rampants.",
                "lieuExecution": "(69) Rhône",
                "dureeMois": "6",
                "valeurEstimee": {"@devise": "EUR", "valeur": "650000"},
            },
        },
    }},
    date_limite="2026-12-18T12:00:00+01:00", descripteurs=["Couverture", "Isolation"],
)

# 3. MAPA : délai de réponse trop court (3 jours) pour le profil de test.
COMBLES_DELAI_COURT = _record(
    "26-200003", "Travaux d'isolation des combles de la mairie", "Commune de Vienne", ["38"], "MAPA",
    {"MAPA": {
        "organisme": {"acheteurPublic": "Commune de Vienne", "adr": {"cp": "38200", "ville": "VIENNE"}},
        "initial": {
            "natureMarche": {"travaux": ""},
            "description": {"objet": "Travaux d'isolation des combles de la mairie"},
            "caracteristiques": {"principales": "Isolation par soufflage de 600 m² de combles perdus, résistance thermique R supérieure ou égale à 7."},
            "duree": {"nbMois": "2"},
            "criteres": {"criterePondere": [{"criterePCT": "60", "critere": "Prix des prestations"},
                                            {"criterePCT": "40", "critere": "Valeur technique de l'offre"}]},
            "delais": {"receptionOffres": "2026-11-17T12:00:00"},
            "renseignements": {"rensgComplt": "Montant estimé des travaux : 45 000 euros HT. Les offres sont remises par voie électronique."},
        },
    }},
    date_limite="2026-11-17T12:00:00", descripteurs=["Isolation"],
)

# 4. eForms contenant un mot-clé exclu par le profil (désamiantage) → écarté au pré-filtre.
DESAMIANTAGE_EXCLU = _record(
    "26-200004", "Désamiantage et isolation de l'ancien collège Paul Bert", "Département du Rhône", ["69"], "JOUE",
    {"EFORMS": {"ContractNotice": {
        "cac:ProcurementProject": {
            "cbc:Name": {"@languageID": "FRA", "#text": "Désamiantage et isolation de l'ancien collège Paul Bert"},
            "cbc:Description": {"@languageID": "FRA", "#text": (
                "Travaux de désamiantage des dalles de sol et des conduits, puis isolation des planchers bas. "
                "Le titulaire doit être titulaire de la certification amiante sous-section 3.")},
            "cac:MainCommodityClassification": {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "45262660"}},
        },
    }}},
    date_limite="2026-12-20T11:00:00+00:00", descripteurs=["Amiante (désamiantage)"],
)

# 5. FNSimple hors zone d'intervention (Bouches-du-Rhône) → écarté au pré-filtre.
GYMNASE_HORS_ZONE = _record(
    "26-200005", "Isolation thermique du gymnase municipal", "Commune d'Aubagne", ["13"], "FNS",
    {"FNSimple": {"initial": {
        "procedure": {"capaciteEcoFin": "Déclaration du candidat (DC2).", "dateReceptionOffres": "2026-12-22T16:00:00+01:00"},
        "natureMarche": {
            "intitule": "Isolation thermique du gymnase municipal",
            "codeCPV": {"objetPrincipal": {"classPrincipale": "45321000"}},
            "description": "Isolation thermique par l'extérieur du gymnase municipal et reprise des bardages.",
            "lieuExecution": "(13) Bouches-du-Rhône",
        },
    }}},
    date_limite="2026-12-22T16:00:00+01:00", descripteurs=["Isolation"],
)

# 6. MAPA sans rapport avec le métier (fournitures alimentaires) → écarté au pré-filtre.
DENREES_HORS_METIER = _record(
    "26-200006", "Fourniture de denrées alimentaires pour la restauration scolaire", "Commune de Meyzieu", ["69"], "MAPA",
    {"MAPA": {"initial": {
        "natureMarche": {"fournitures": ""},
        "description": {"objet": "Fourniture de denrées alimentaires pour la restauration scolaire"},
        "caracteristiques": {"principales": "Accord-cadre à bons de commande pour la fourniture de produits frais et d'épicerie."},
        "delais": {"receptionOffres": "2026-12-10T12:00:00"},
    }}},
    date_limite="2026-12-10T12:00:00", descripteurs=["Denrées alimentaires"], type_marche="FOURNITURES",
)

# 7. FNSimple exigeant une certification non détenue (ISO 14001 obligatoire) et alloti.
MENUISERIES_ISO = _record(
    "26-200007", "Remplacement des menuiseries extérieures de l'école maternelle des Tilleuls",
    "Communauté d'agglomération du bassin de Bourg-en-Bresse", ["01"], "FNS",
    {"FNSimple": {"initial": {
        "procedure": {
            "capaciteEcoFin": "Déclaration concernant le chiffre d'affaires global des trois derniers exercices.",
            "capaciteTech": "La certification ISO 14001 est obligatoire et devra être jointe à la candidature.",
            "dateReceptionOffres": "2026-12-12T12:00:00+01:00",
        },
        "natureMarche": {
            "intitule": "Remplacement des menuiseries extérieures de l'école maternelle des Tilleuls",
            "codeCPV": {"objetPrincipal": {"classPrincipale": "45421000"}},
            "description": "Dépose et remplacement de 40 menuiseries extérieures bois par des menuiseries mixtes bois-aluminium.",
            "lieuExecution": "(01) Ain",
            "valeurEstimee": {"@devise": "EUR", "valeur": "120000"},
            "lotsMarche": {"oui": ""},
        },
        "lots": {"lot": [
            {"description": "Menuiseries extérieures bois-aluminium", "codeCPV": {"objetPrincipal": {"classPrincipale": "45421100"}},
             "lieuExecutionLivraison": "(01) Ain"},
            {"description": "Occultations et stores", "codeCPV": {"objetPrincipal": {"classPrincipale": "45421140"}},
             "lieuExecutionLivraison": "(01) Ain"},
        ]},
    }}},
    date_limite="2026-12-12T12:00:00+01:00", descripteurs=["Menuiserie"],
)

ALL_RECORDS: list[dict[str, Any]] = [
    RENOVATION_ECOLE, TOITURE_CA_MINIMUM, COMBLES_DELAI_COURT, DESAMIANTAGE_EXCLU,
    GYMNASE_HORS_ZONE, DENREES_HORS_METIER, MENUISERIES_ISO,
]

# Profil de la PME de test : entreprise de rénovation énergétique en région lyonnaise.
PROFILE_DATA: dict[str, Any] = {
    "name": "Isol'Rhône Rénovation",
    "description": "PME de 18 salariés spécialisée en isolation thermique, menuiseries extérieures et couverture.",
    "skills": ["isolation thermique par l'extérieur", "menuiseries extérieures", "couverture"],
    "keywords_include": ["isolation", "menuiserie", "rénovation énergétique", "toiture"],
    "keywords_exclude": ["désamiantage", "démolition"],
    "cpv_codes": ["45321000", "454210"],
    "departments": ["69", "38", "01"],
    "certifications": ["Qualibat 7131", "RGE"],
    "annual_revenue_eur": 2400000,
    "min_contract_eur": 20000,
    "max_contract_eur": 800000,
    "min_response_days": 10,
    "eliminatory_criteria": ["visite obligatoire"],
    "alert_threshold": 60,
    "digest_email": "direction@isolrhone.example",
}
