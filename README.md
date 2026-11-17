# TenderPulse

Veille automatisée des appels d'offres publics pour PME : TenderPulse collecte chaque jour les avis du
**BOAMP** (API OpenData officielle), les analyse, et calcule pour chaque PME cliente un **score
d'adéquation sur 100**, les **critères éliminatoires**, une **synthèse décisionnelle en 5 lignes**
(Go / À vérifier / No-Go) et un **digest quotidien** prêt à envoyer par e-mail.

## À quoi sert ce dépôt, et quand l'utiliser

**À quoi il sert.** TenderPulse fait la veille des marchés publics à la place de la PME : il collecte les
avis du BOAMP chaque matin, les note selon le métier, la zone, les certifications et le chiffre
d'affaires de l'entreprise, repère les critères éliminatoires et envoie un digest par e-mail.

**Utilisez-le quand :**

- une PME du BTP, de l'industrie ou des services répond à des appels d'offres publics ;
- la veille dépend d'une personne qui n'a pas le temps de lire tous les avis ;
- vous gérez plusieurs clients : chaque PME a sa clé d'API, ses profils et ses opportunités, cloisonnés ;
- vous voulez un argument de prospection concret : le relevé des marchés de la semaine pour un prospect.

**Ne l'utilisez pas quand :**

- le client vise des marchés privés ou des plateformes autres que le BOAMP : seule cette source est lue ;
- il attend une analyse du dossier de consultation : TenderPulse lit l'avis, pas les pièces jointes ;
- l'argument de vente est la confidentialité : les avis sont publics et la collecte passe par Internet.
  L'argument de TenderPulse est le chiffre d'affaires gagné.

**Comment le lancer.** Sans IA (`LLM_PROVIDER=none`), le scoring est entièrement déterministe et suffit
pour démarrer. Avec IA, l'analyse est plus fine ; la note de l'IA reste bornée par les règles. Chez un
client, passez par la box CodeSafe (`LLM-exploits/codesafe-ai-box`).

### Les trois dépôts CodeSafe

| Dépôt | À quoi il sert | À utiliser quand |
|---|---|---|
| [`docflow-local`](https://github.com/TN-RedTeam/docflow-local) | Lire des factures et des documents de transport en PDF, contrôler les calculs, faire valider par un humain, exporter | une PME ressaisit des documents à la main et ne veut rien envoyer en ligne |
| [`TenderPulse`](https://github.com/TN-RedTeam/TenderPulse) | Collecter chaque jour les appels d'offres publics et les noter selon le profil d'une PME | une PME répond à des marchés publics et fait sa veille à la main |
| [`LLM-exploits`](https://github.com/TN-RedTeam/LLM-exploits) | Sécuriser, auditer et vendre : la box qui réunit les applications, l'outil d'audit, l'offre commerciale, et FreightGuard | vous installez chez un client, vous prouvez la sécurité, ou vous préparez un rendez-vous commercial |

## Architecture

```
                 ┌──────────────────────────── backend (FastAPI, Python 3.11+) ────────────────────────────┐
 API OpenData    │  collector/            scoring/                        api/                             │
 BOAMP ─────────►│  client httpx async ─► pré-filtre (mots-clés, CPV, ─►  REST multi-tenant (X-API-Key)    │──► frontend
 (opendatasoft)  │  pagination, retry,    départements, date limite)      digest HTML · SMTP facultatif    │    React 18 / TS
                 │  rate-limit, dédup     règles éliminatoires            planificateur quotidien          │    Vite / Tailwind
                 │  parser eForms /       grille de notation /100                    │                     │    (nginx)
                 │  FNSimple / MAPA       LLM (OpenAI-compatible | Ollama) ──────────┼─────────────────────┘
                 └───────────────────────────────────────────────────────────────────┼
                                                                         PostgreSQL 16 (tenants, company_profiles,
                                                                         tenders, tender_scores, collection_runs)
```

| Dossier | Rôle |
|---|---|
| `backend/collector/` | Client asynchrone de l'API BOAMP (`client.py`), filtres (`models.py`), parser des avis eForms / FNSimple / MAPA vers un modèle unique (`parser.py`). |
| `backend/scoring/` | `CompanyProfile`, pré-filtre, détection des critères éliminatoires, grille de notation, client LLM, pipeline hybride. |
| `backend/api/` | Schéma SQL (`init.sql`), endpoints REST, digest HTML, envoi SMTP, orchestration et planificateur. |
| `frontend/` | Tableau de bord : opportunités triées par score, panneau de détail, formulaire de profil. |
| `tests/` | Suite `pytest` avec un jeu d'avis BOAMP simulés (aucun accès réseau). |

### Comment un avis est noté

1. **Pré-filtre** (instantané, sans LLM) : un avis est écarté si sa date limite est passée, s'il contient un
   mot-clé exclu, s'il est hors des départements du profil, ou s'il ne correspond à aucun mot-clé, compétence
   ou code CPV. Seuls les avis retenus sont notés et stockés.
2. **Règles éliminatoires** (déterministes) : chiffre d'affaires minimum exigé supérieur à celui de la PME,
   certification exigée non détenue (Qualibat, Qualifelec, RGE, ISO 9001/14001/27001/45001, MASE, HDS…),
   zone hors périmètre, délai de réponse trop court, budget hors capacité, expressions éliminatoires du profil.
   Une exigence assortie de « ou équivalent » est classée *à vérifier* plutôt que *bloquante*.
3. **Grille sur 100** : adéquation métier (40), zone (15), capacité financière (15), certifications (15),
   délai (15), chaque note étant justifiée.
4. **LLM (facultatif)** : il re-note les critères qui demandent une lecture du texte (métier, capacité,
   certifications), ajoute les critères éliminatoires que les règles n'ont pas vus et rédige la synthèse.
   La zone et le délai restent calculés. Le LLM **ne peut pas lever un critère bloquant** ni transformer seul
   un avis en « Go ». En cas de panne ou de JSON invalide, l'analyse déterministe est utilisée.
5. **Décision** : critère bloquant → No-Go (score plafonné à 35) ; score ≥ 70, aucun point à vérifier et
   adéquation métier ≥ 60 % → Go ; score ≥ 45 → À vérifier ; sinon No-Go.

## Lancement avec Docker

Prérequis : Docker et Docker Compose v2.

```bash
cp .env.example .env
# Éditer .env : définir au minimum ADMIN_API_KEY (ex. `openssl rand -hex 32`)
docker compose up --build -d
```

- Interface : <http://localhost:8080> — se connecter avec la valeur de `ADMIN_API_KEY`.
- API et documentation interactive : <http://localhost:8000/docs>.

Premiers pas dans l'interface : **+ Client** (la clé d'API du client s'affiche une seule fois) → remplir le
profil de la PME → **Lancer une collecte**. Ensuite, la collecte tourne seule chaque jour à 6 h 30 (heure de
Paris), configurable par `COLLECT_HOUR` / `COLLECT_MINUTE`.

```bash
docker compose logs -f backend   # suivre la collecte
docker compose down              # arrêter (les données restent dans le volume pgdata)
```

### Activer l'analyse par LLM

Par défaut `LLM_PROVIDER=none` : le scoring est entièrement déterministe, gratuit et sans clé. Pour l'analyse
fine, dans `.env` :

```bash
# API compatible OpenAI (OpenAI, Mistral, OpenRouter, vLLM…)
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-votre-cle
LLM_MODEL=gpt-4o-mini

# ou Ollama sur la machine hôte
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=llama3.1
```

`LLM_MAX_PER_RUN` plafonne le nombre d'appels par collecte ; au-delà, les avis sont notés par les règles.

### Envoyer le digest par e-mail

Renseigner `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, puis `DIGEST_AUTO_SEND=true`
pour un envoi automatique après chaque collecte quotidienne. Sans SMTP, le digest reste accessible en HTML
(bouton « Aperçu du digest » ou endpoint ci-dessous).

## Jeu de test

Le dossier [`jeu-de-test/`](jeu-de-test/) contient le profil d'un grossiste et treize avis de marché
fictifs aux trois formats du BOAMP, avec la note et la décision attendues pour chacun, et un serveur
BOAMP factice pour les collecter chez vous. Voir son [README](jeu-de-test/README.md).

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/pytest
```

Les 50 tests unitaires n'utilisent ni réseau ni base de données : l'API BOAMP et le LLM sont simulés par des
transports `httpx` factices, à partir d'avis reproduisant les trois formats réels (`tests/boamp_fixtures.py`).
Ils prouvent le pré-filtrage, le calcul du score, la détection des critères éliminatoires (dont le chiffre
d'affaires minimum exigé) et la génération du digest HTML.

Le test d'intégration de l'API (parcours multi-tenant complet) a besoin d'un PostgreSQL ; il est ignoré sinon :

```bash
docker compose up -d db
docker compose exec db createdb -U tenderpulse tenderpulse_test
docker compose run --rm -v "$PWD":/src -w /src \
  -e TEST_DATABASE_URL=postgresql://tenderpulse:tenderpulse@db:5432/tenderpulse_test \
  backend sh -c "pip install --user -q -r backend/requirements-dev.txt && python -m pytest"
```

Attention : ce test vide les tables de la base désignée par `TEST_DATABASE_URL`.

## Développement sans Docker

```bash
# Backend (PostgreSQL 16 accessible ; le schéma est appliqué au démarrage)
export DATABASE_URL=postgresql://tenderpulse:tenderpulse@localhost:5432/tenderpulse
export ADMIN_API_KEY=dev-admin-key
.venv/bin/uvicorn backend.api.main:app --reload --port 8000

# Frontend (relaie /api vers localhost:8000)
cd frontend && npm install && npm run dev      # http://localhost:5173
```

## API REST

Authentification par en-tête `X-API-Key` : la clé d'administration (opérateur, accès à tous les clients) ou
la clé d'un client, qui ne donne accès qu'à ses propres données.

| Méthode | Chemin | Description |
|---|---|---|
| GET | `/api/health` | État du service, prochaine collecte planifiée |
| GET | `/api/me` | Rôle et client associés à la clé |
| GET / POST | `/api/tenants` | Lister / créer un client (admin) |
| POST | `/api/tenants/{id}/rotate-key` | Régénérer la clé d'un client (admin) |
| DELETE | `/api/tenants/{id}` | Supprimer un client et ses données (admin) |
| GET / POST | `/api/tenants/{id}/profiles` | Lister / créer un profil |
| GET / PUT / DELETE | `/api/tenants/{id}/profiles/{pid}` | Lire / modifier / supprimer un profil |
| POST | `/api/tenants/{id}/profiles/{pid}/rescore` | Ré-analyser les avis ouverts pour ce profil |
| GET | `/api/tenants/{id}/profiles/{pid}/opportunities` | Opportunités triées par score (`status`, `decision`, `min_score`, `include_expired`, `include_ignored`, `limit`, `offset`) |
| GET | `/api/tenants/{id}/opportunities/{oid}` | Détail d'une opportunité, texte complet de l'avis inclus |
| PATCH | `/api/tenants/{id}/opportunities/{oid}` | Statut de suivi : `nouveau`, `a_etudier`, `go`, `ignore` |
| GET | `/api/tenants/{id}/profiles/{pid}/digest?since_hours=24` | Digest HTML (0 = toutes les consultations ouvertes) |
| POST | `/api/tenants/{id}/profiles/{pid}/digest/send` | Envoyer le digest par SMTP |
| POST | `/api/collect` | Déclencher une collecte (admin) ; filtres facultatifs `cpv_codes`, `departments`, `keywords`, `date_from`, `date_to` |
| GET | `/api/collect/runs`, `/api/collect/runs/{id}` | Historique et suivi des collectes (admin) |

Exemple :

```bash
curl -X POST http://localhost:8000/api/collect -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"departments": ["69", "38"], "keywords": ["isolation"], "date_from": "2026-11-01"}'
```

## Limites connues

- **Source** : seul le BOAMP est collecté. Les marchés publiés uniquement sur les profils acheteurs ou au
  JOUE (TED) sans reprise au BOAMP ne sont pas couverts.
- **Avis, pas DCE** : l'analyse porte sur le texte de l'avis. Le règlement de consultation et le CCTP, qui
  contiennent souvent les exigences détaillées, ne sont pas téléchargés. Le score est une aide au tri, pas
  une décision.
- **Sans LLM**, l'adéquation métier repose sur les mots-clés et codes CPV : un avis de maîtrise d'œuvre
  contenant « rénovation énergétique » ressort pour une entreprise de travaux. Le LLM corrige ce type de cas.
- **Départements** : le champ `code_departement` du BOAMP mêle lieu d'exécution et zones de publication ;
  un avis peut donc être rattaché à plus de départements que son lieu d'exécution réel.
- **Certifications** : la comparaison se fait par famille (un « Qualibat 7131 » détenu couvre toute mention
  Qualibat) ; le numéro de qualification exact est à vérifier.
- **Déploiement** : le planificateur tourne dans le processus de l'API, qui doit rester à un seul worker.
  Le frontend conserve la clé d'API dans le `localStorage` du navigateur : servir l'application en HTTPS.
