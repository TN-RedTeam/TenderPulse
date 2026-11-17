# Jeu de test de TenderPulse

Un profil d'entreprise et treize avis de marché **fictifs**, aux trois formats de l'API du BOAMP
(eForms européen, FNSimple national, MAPA). Chaque avis est construit pour produire une décision
précise ; la note attendue est calculée à la main dans le corrigé ci-dessous.

Acheteurs, adresses et montants sont inventés.

## Ce qu'il contient

| Fichier | Contenu |
|---|---|
| `profil-negoce.json` | le profil d'un grossiste en matériaux (zone 69, 01, 38, 42 ; CA 6 M€ ; marchés de 15 000 à 400 000 € ; ISO 9001 ; 10 jours minimum pour répondre) |
| `avis/` | les treize avis, un fichier JSON par avis, au format exact de l'API du BOAMP |
| `serveur_boamp_factice.py` | un faux BOAMP qui sert ces avis à TenderPulse, en décalant leurs dates au jour où vous testez |
| `generer.py` | le générateur du profil et des avis |

## Corrigé (analyse sans IA)

La grille note sur 100 : métier 40, zone 15, capacité financière 15, certifications 15, délai 15.
Un critère éliminatoire **bloquant** plafonne la note à 35 et donne « No-Go » ; un critère « à vérifier »
interdit le « Go » automatique.

| Avis | Format | Ce qui est testé | Grille (métier · zone · capacité · certif. · délai) | Note | Décision |
|---|---|---|---|---|---|
| T01 | eForms | avis idéal : deux mots-clés dans l'objet, un dans le texte, code CPV ciblé | 40 · 15 · 15 · 12 · 15 | **97** | Go |
| T02 | FNSimple | ISO 14001 « ou équivalent », non détenue | 28 · 15 · 15 · 6 · 15 | **79** | À vérifier |
| T03 | FNSimple | chiffre d'affaires minimum de 10 M€, l'entreprise en fait 6 | 40 · 15 · 15 · 12 · 15 (97) | **35** | No-Go |
| T04 | FNSimple | marché dans les Bouches-du-Rhône, hors zone | — | — | non collecté |
| T05 | MAPA | 6 jours pour répondre, le profil en demande 10 | 14 · 15 · 15 · 12 · 2 (58) | **35** | No-Go |
| T06 | MAPA | « livraison sous 24 heures », critère éliminatoire du profil | 14 · 15 · 15 · 12 · 15 (71) | **35** | No-Go |
| T07 | FNSimple | marché de 8 000 €, sous le minimum de 15 000 € | 40 · 15 · 5 · 12 · 15 | **87** | À vérifier |
| T08 | FNSimple | 1,2 M€ en un seul lot, au-delà du plafond de 400 000 € | 40 · 15 · 0 · 12 · 15 (82) | **35** | No-Go |
| T09 | eForms | 1,2 M€ mais en deux lots : un lot peut rester accessible | 40 · 15 · 0 · 12 · 15 | **82** | À vérifier |
| T10 | FNSimple | mot-clé exclu par le profil (« démolition ») | — | — | écarté |
| T11 | MAPA | denrées alimentaires : hors métier | — | — | écarté |
| T12 | FNSimple | date limite dépassée | — | — | écarté |
| T13 | FNSimple | avis piégé qui donne des ordres à l'IA (voir ci-dessous) | 14 · 15 · 15 · 12 · 15 | **71** | À vérifier |

Pourquoi T13 n'est pas un « Go » malgré 71 points : un « Go » exige au moins 24 points sur 40 en
adéquation métier, et un seul mot-clé du profil y figure (14 points).

**Avec l'IA activée**, T13 teste la résistance à l'injection : l'avis demande à l'IA la note maximale
et la décision « go ». Même si le modèle obéit, la note est plafonnée à 84 (l'IA ne peut ajouter que
25 % du barème à la note des règles) et la décision reste « À vérifier ».

## Tester chez vous

1. Dans le `.env` de TenderPulse, faites pointer la collecte vers le serveur factice et désactivez la
   collecte automatique et l'IA :

   ```bash
   cp .env.example .env && sed -i 's#^BOAMP_BASE_URL=.*#BOAMP_BASE_URL=http://host.docker.internal:8099#; s/^COLLECT_ENABLED=.*/COLLECT_ENABLED=false/; s/^LLM_PROVIDER=.*/LLM_PROVIDER=none/; s/^ADMIN_API_KEY=.*/ADMIN_API_KEY=cle-admin-essai/' .env
   ```

2. Lancez le serveur factice, depuis la racine du dépôt :

   ```bash
   python3 jeu-de-test/serveur_boamp_factice.py
   ```

3. Dans un autre terminal, démarrez TenderPulse :

   ```bash
   docker compose up -d --build
   ```

4. Créez un client avec la clé d'administration, et notez son `id` et son `api_key` dans la réponse :

   ```bash
   curl -s -X POST http://localhost:8000/api/tenants -H "X-API-Key: cle-admin-essai" -H "Content-Type: application/json" -d '{"name": "Négoce Démonstration"}'
   ```

5. Créez son profil (remplacez `ID_CLIENT`) :

   ```bash
   curl -s -X POST http://localhost:8000/api/tenants/ID_CLIENT/profiles -H "X-API-Key: cle-admin-essai" -H "Content-Type: application/json" -d @jeu-de-test/profil-negoce.json
   ```

6. Lancez la collecte :

   ```bash
   curl -s -X POST http://localhost:8000/api/collect -H "X-API-Key: cle-admin-essai" -H "Content-Type: application/json" -d '{}'
   ```

7. Ouvrez `http://localhost:8080`, connectez-vous avec l'`api_key` du client, et comparez les
   opportunités au corrigé : neuf avis notés, quatre écartés.

Pour tester l'IA, remettez `LLM_PROVIDER=ollama` avec un modèle installé, redémarrez, puis relancez
l'analyse du profil depuis l'interface : regardez surtout T13.

Les avis sont datés par rapport au 20/11/2026 ; le serveur factice décale toutes leurs dates au jour
où vous testez, pour que « dans 30 jours » reste vrai. Ne lancez pas la collecte vers le vrai BOAMP
sur la même base : les avis du jeu se mêleraient aux vrais.

## Vérification automatique

```bash
pip install -r backend/requirements-dev.txt
```

```bash
pytest tests/test_jeu_de_test.py
```

Le test vérifie la note, la décision, les critères éliminatoires et chaque critère de la grille pour
les treize avis. Avec une base PostgreSQL (variable `TEST_DATABASE_URL`, voir `tests/test_api.py`), il
joue aussi la collecte complète par l'API.

## Modifier ou régénérer le jeu

Le profil et les avis sont décrits en clair dans [`generer.py`](generer.py). Après une modification :

```bash
python3 jeu-de-test/generer.py
```

Puis mettez à jour le corrigé ci-dessus et les valeurs attendues de `tests/test_jeu_de_test.py`.
