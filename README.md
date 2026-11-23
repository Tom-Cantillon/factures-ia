# Factures IA — de la facture scannée à l'agent IA

Chaîne de bout en bout pour extraire les informations de factures fournisseurs (PDF natifs et scannés),
les stocker dans une architecture médaillon et les interroger en langage naturel via un agent IA.

```
 PDF (bucket S3) ──► extraction / OCR ──► bronze ──► silver ──► entrepôt ──► serveur MCP ──► agent IA
```

## Démarrage rapide

```bash
# 1. Installer les dépendances (nécessite uv : https://docs.astral.sh/uv/)
uv sync

# 2. Configurer les secrets (jamais commités)
cp .env.example .env   # puis remplir les identifiants S3, la clé OCR, le LLM

# 3. Récupérer les factures (incrémental : relancer ne retélécharge rien)
uv run factures fetch

# 4. Détecter pour chaque PDF s'il est « texte » ou « image » (OCR nécessaire)
uv run factures detect          # tableau lisible
uv run factures detect --csv    # sortie CSV

# 5. Envoyer une page au modèle d'OCR et afficher le texte reconnu (+ temps de traitement)
uv run factures ocr facture_A-2025-0003_scan.pdf
uv run factures ocr facture_A-2025-0003_scan.pdf --longest-side 1024 --save-image page.png

# 6. Couche bronze : extraire le texte de tous les PDF (OCR seulement pour les scans)
uv run factures bronze --limit 5   # commencer petit
uv run factures bronze             # tout le reste ; relancer n'ajoute rien et ne fait aucun appel OCR
uv run factures silver             # 7. couche silver : parsing, typage, contrôles, quarantaine
uv run factures run                # fetch + bronze + silver + warehouse en une commande

# 9. Entrepôt SQL (vues DuckDB sur les Parquet)
uv run factures warehouse          # génère data/warehouse.duckdb pour DBeaver
uv run factures sql "SELECT status, count(*), sum(total_ttc) FROM silver.invoices GROUP BY 1"
uv run factures status             # résumé landing / bronze / erreurs à retraiter

# 8. Évaluer l'OCR champ par champ (vérité terrain + 3 résolutions + faux scans) → eval/results.md
uv run factures eval --sides 512 768 1540 --synthetic

# Tests
uv run pytest
```

Le projet utilise Python 3.13 (fixé dans `.python-version`, uv l'installe automatiquement).

### Clés Hyperfluid

- **S3** : console → Storage → Buckets → Access keys → *New access key*, bucket `factures`, lecture seule.
  La console fournit les 4 variables `AWS_*` à copier dans `.env`.
- **OCR** : console → AI Gateway → API Keys → *Create API Key*, scope **`model:*`**
  (le scope `model:inference` renvoie une erreur 403 sur les modèles partagés).

## Étape 1 — Récupération et détection

- `factures fetch` liste le bucket et télécharge dans `data/landing/` les PDF absents ou modifiés.
  Un manifeste (`data/landing/_manifest.json`) garde pour chaque fichier son URI S3, son ETag, sa taille,
  son SHA-256 et sa date de téléchargement. Un fichier est « déjà vu » si sa clé **et** son ETag sont connus :
  le nom seul ne suffit pas, un fichier peut être remplacé sous le même nom.
- `factures detect` lit la couche texte de chaque page avec PyMuPDF. Une page est « texte » si elle
  contient au moins 30 caractères alphanumériques, sinon « image ». Le document est « texte », « image »
  ou « mixte ». La décision se fait sur le **contenu**, jamais sur le nom du fichier.
- Résultat sur le jeu fourni : 100 PDF d'une page, **50 texte / 50 image**. Les natifs ont 552 à 718
  caractères, les scans 0 : le seuil n'est pas critique. La détection concorde à 100 % avec les suffixes
  `_texte` / `_scan` des noms, qui ne servent qu'à la vérification.

## Organisation du dépôt

| Dossier | Rôle |
|---|---|
| `src/factures/` | Code du pipeline (ingestion, OCR, bronze, silver, MCP, agent) |
| `data/landing/` | Zone d'arrivée des PDF téléchargés depuis S3 (non versionnée) |
| `data/bronze/` | Données brutes extraites + métadonnées (non versionnée) |
| `data/silver/` | Tables propres, typées, contrôlées + quarantaine (non versionnée) |
| `eval/` | Vérité terrain et évaluation de l'OCR |
| `tests/` | Tests automatisés |
| `docs/` | Rapport et schémas |

## Étape 2 — OCR avec LightOnOCR-3

- `src/factures/ocr.py` définit une interface `OcrEngine` (PNG → texte). Le pipeline ne connaît que
  cette interface. LightOnOCR-3 en est une implémentation, choisie par `OCR_ENGINE` (défaut
  `lightonocr`). Changer de fournisseur revient à ajouter une classe, sans réécrire le reste.
- La requête suit la fiche du modèle : image seule en PNG base64, plus grand côté 1540 px,
  `temperature=0.2`, `top_p=0.9`, `max_tokens=4096`.
- La clé d'API n'existe que dans `.env`, ignoré par Git.
- Sortie : du markdown avec les tableaux en HTML. Environ 6 s par page.
  Détails, mesures et compromis taille / vitesse : [docs/journal_ocr.md](docs/journal_ocr.md).

## Étape 3 — Couche bronze

Stockage : des fichiers **Parquet** sous `data/bronze/<table>/`. C'est un format colonnaire, typé et
lisible directement en SQL par DuckDB (étape 6). Deux tables :

| Table | Contenu |
|---|---|
| `documents` | une ligne par PDF extrait : `doc_id` (SHA-256 du contenu), URI S3, ETag, méthode (`pdf_text` / `ocr` / `mixte`), texte brut par page, moteur / modèle / paramètres OCR, taille d'image, tokens, durées, `run_id`, version du pipeline |
| `extraction_errors` | journal des échecs : document, étape (`pdf` / `ocr`), type et message d'erreur, nombre de tentatives, `run_id` |

- **Déjà vu ?** Un document est identifié par le **SHA-256 de son contenu**, pas par son nom : un
  fichier renommé n'est pas retraité, un fichier remplacé sous le même nom l'est.
- **Append-only** : chaque run écrit de nouveaux fichiers (`<run_id>-NNNN.parquet`, écriture atomique)
  et ne modifie ni ne supprime jamais les anciens. La bronze est la preuve de ce qui a été lu, et
  comment. Si le parseur silver évolue, on la relit sans refaire d'OCR, qui est coûteux et non déterministe.
- **Pannes OCR** : chaque page est tentée 3 fois avec un délai croissant entre les essais. Les erreurs
  non transitoires (authentification, requête invalide) ne sont pas retentées. Après 3 échecs
  consécutifs, un **coupe-circuit** arrête les appels pour le reste du run. Chaque échec est écrit dans
  `extraction_errors`. Le document, absent de `documents`, sera retraité au prochain run.
- **Parallélisme** : 4 appels OCR simultanés par défaut (`--workers`). Les résultats sont écrits par un
  seul thread.

Mesures sur le jeu complet :
- 100 documents, dont 50 OCR, en **1 min 37** avec 4 workers, soit 7,6 s d'OCR en moyenne par scan.
- Deuxième run : 0 extrait, 0 appel OCR.
- Panne simulée (`OCR_BASE_URL` injoignable) : les PDF texte passent, les scans sont journalisés, et le
  run suivant les rattrape.

## Étape 4 — Couche silver

Tables (`data/silver/<table>/data.parquet`), entièrement recalculées depuis la bronze à chaque
`factures silver`. Le calcul est déterministe, prend moins d'une seconde et n'appelle pas l'OCR.
L'écriture passe par un dossier temporaire puis une bascule, si bien qu'un lecteur ne voit jamais
une silver à moitié écrite.

| Table | Contenu |
|---|---|
| `invoices` | une ligne par facture : numéro, dates (`DATE`), fournisseur, client, SIRET, catégorie, statut, paiement, IBAN, totaux HT / TVA / TTC en `DECIMAL(14,2)`, `quality_status`, `quality_flags`, `quality_details`, lien vers la bronze (`doc_id`, fichier, URI S3, méthode, `bronze_run_id`) |
| `invoice_lines` | une ligne par ligne de facture : désignation, quantité, PU HT, taux de TVA, total HT |
| `quarantine` | une ligne par document rejeté : `reason_codes`, `reason_details`, `duplicate_of` |

**Un parseur pour deux formes de texte.** Le texte natif donne une valeur par ligne. L'OCR donne du
markdown, avec des tableaux HTML et des totaux tantôt en lignes `**Total HT** …`, tantôt dans un
tableau. `parser.to_lines` normalise les deux formes en un même flux de lignes (une cellule ou un
« libellé : valeur » par ligne), puis un seul parseur le lit. Sur les 100 factures : 0 champ manquant.

**Montants en `Decimal`, jamais en `float`.** Un flottant binaire ne représente pas 0,10 exactement :
les sommes dérivent et les comparaisons au centime échouent. Les montants sont stockés en
`DECIMAL(14,2)` dans Parquet et dans DuckDB.

**Rejetée ou signalée ?**

| | Effet | Règles |
|---|---|---|
| **Rejet** → `quarantine` | la facture n'entre pas dans `invoices` | `CHAMP_MANQUANT` (numéro, fournisseur, client, date d'émission, TTC), `FORMAT_INVALIDE` (date ou TTC illisible), `DOUBLON` (même SIRET fournisseur + numéro déjà retenu ; la première ingérée est gardée) |
| **Signalement** → `quality_status = 'signalee'` | la facture est gardée, avec la liste des anomalies | `TTC_INCOHERENT` (HT + TVA ≠ TTC), `SOMME_LIGNES_HT`, `LIGNE_CALCUL` (qté × PU ≠ total), `TVA_INCOHERENTE`, `ECHEANCE_AVANT_EMISSION`, `IBAN_INVALIDE` (clé mod 97), `SIRET_INVALIDE` (14 chiffres), `VALEUR_INCONNUE`, `CHAMP_ILLISIBLE`, `LIGNE_ILLISIBLE`, `AUCUNE_LIGNE` |

On rejette ce qui n'est pas exploitable ou ce qui fausserait les comptes (un doublon compté deux
fois). On signale ce qui est exploitable mais suspect. **Rien n'est corrigé automatiquement** : un
montant « corrigé » par calcul ressemble à une donnée vraie mais n'en est pas une. Il masquerait
l'erreur et pourrait conduire à payer un mauvais montant. La valeur lue est conservée, et un humain
tranche.

Choix lié au jeu de données : la **clé de Luhn des SIRET n'est pas exigée**. Les SIRET du jeu sont
fictifs et seuls 14 % d'entre eux la respectent (11 fournisseurs et 3 clients sur 100 factures).
L'exiger signalerait 100 % des factures et noierait les vraies anomalies. La fonction est fournie
(`siret_luhn_ok`) pour des données réelles. La clé IBAN, elle, est valide sur 100/100 : elle est
gardée, car elle détecte un chiffre mal lu par l'OCR.

**Résultat sur les 100 factures : 99 valides, 1 signalée, 0 en quarantaine, 271 lignes.**
La facture signalée, `V-2025-0001`, porte sur le document lui-même un TTC de 99 999,99 € pour
HT 148,26 € + TVA 29,65 €. C'est vérifié sur l'image : c'est une anomalie du document, pas une
erreur d'OCR.

## Étape 5 — Qualité de l'OCR

Méthode, résultats complets et analyse : [eval/README.md](eval/README.md).

- **Vérité terrain réelle** : 20 scans tirés au sort, répartis entre les 8 fournisseurs, vérifiés à
  la main champ par champ sur l'image (`eval/ground_truth.json`).
- **Vérité terrain synthétique** : les 50 PDF natifs rendus en image puis dégradés comme un scan. Leur
  couche texte donne une vérité exacte, gratuite et indépendante de l'OCR.

| Facture 100 % exacte | 512 px | 768 px | **1540 px** |
|---|---:|---:|---:|
| Scans réels (n = 20) | 0/20 | 18/20 | **20/20** |
| Faux scans (n = 50) | 0/50 | 4/50 | **50/50** |

Champs fragiles : les longues suites de chiffres (IBAN, SIRET, n° de TVA), les noms propres et la
structure du tableau. Champs robustes : le vocabulaire fermé et le total TTC. Les contrôles silver
signalent ou rejettent 85 % des factures mal lues à 768 px.

## Étape 6 — Entrepôt de données

**Stockage** : les fichiers Parquet de `data/bronze` et `data/silver`, en un seul exemplaire.
**Calcul** : DuckDB, qui lit ces fichiers à la demande. L'entrepôt ne contient que des **vues**
(`bronze.documents`, `bronze.extraction_errors`, `silver.invoices`, `silver.invoice_lines`,
`silver.quarantine`), commentées table par table et colonne par colonne. Aucune donnée n'est copiée.

Pourquoi DuckDB : c'est un moteur analytique en colonnes, embarqué (pas de serveur à opérer),
qui lit Parquet nativement, avec un typage `DECIMAL` / `DATE` exact. Il a un pilote DBeaver officiel
et une API Python. À plus grande échelle, la même architecture passe sur S3 (DuckDB `httpfs`, voire
Trino ou Spark) sans changer les fichiers.

**Accès concurrents.** Un fichier `.duckdb` ouvert en écriture est verrouillé par son processus. Si
tous les programmes partageaient ce fichier, il suffirait que DBeaver le garde ouvert pour bloquer
le pipeline, le serveur MCP et l'agent. D'où deux accès séparés :
- les **programmes** utilisent `warehouse.connect()` : une base **en mémoire**, propre au
  processus, où les vues sont recréées au démarrage. Il n'y a aucun fichier partagé, donc aucun
  verrou, et les lecteurs simultanés sont illimités. Parquet est immuable, et la silver est
  remplacée par bascule de dossier : un lecteur ne voit jamais de fichier à moitié écrit ;
- **DBeaver** ouvre `data/warehouse.duckdb`, généré par `factures warehouse` (environ 270 Ko de
  vues, aucune donnée). Vérifié : pendant qu'un processus tient ce fichier en écriture,
  `factures sql` et `factures silver` fonctionnent normalement.

**Chemins valides partout.** Les vues pointent vers `DATA_DIR` résolu à la connexion (programmes) ou
à la génération (fichier DBeaver). Rien n'est figé dans le dépôt : sur une autre machine ou dans un
conteneur (`DATA_DIR=/data`), on relance `factures warehouse` et les références restent valides.

### Consulter l'entrepôt avec DBeaver

1. `uv run factures warehouse`
2. Dans DBeaver : *Nouvelle connexion* → **DuckDB** (DBeaver télécharge le pilote au premier usage).
3. *Path* : le chemin absolu de `data/warehouse.duckdb`, affiché par la commande.
4. Recommandé : dans *Driver properties*, `access_mode = READ_ONLY`. Plusieurs DBeaver peuvent alors
   ouvrir le fichier en même temps, et `factures warehouse` peut le régénérer.
5. Les schémas `bronze` et `silver` apparaissent, avec les commentaires des vues et des colonnes.

## Étape 7 — Serveur MCP

`src/factures/mcp_server.py`, lancé par `uv run factures-mcp` (transport stdio). Il est écrit avec le
SDK MCP officiel en Python (`mcp` 2.x, classe `MCPServer`).

| Outil | Rôle |
|---|---|
| `list_invoices` | factures filtrées par fournisseur, client, statut, catégorie, qualité, année ou période ; tri et pagination |
| `invoice_totals` | nombre de factures et sommes HT / TVA / TTC avec les mêmes filtres, regroupement optionnel (statut, fournisseur, mois…) |
| `get_invoice` | détail d'une facture et de ses lignes |
| `describe_schema` | vues, colonnes, types, descriptions et valeurs possibles |
| `run_sql` | requête SQL libre, **lecture seule** |

**Transparence.** Chaque réponse contient `sql` : les requêtes réellement exécutées et leurs paramètres.

**Choix des outils par le LLM.** Chaque description dit *quand* utiliser l'outil, avec des exemples
de questions (« combien… », « quel montant… » → `invoice_totals`). Elle précise les valeurs exactes
attendues (`'En retard'`), les formats (`AAAA-MM-JJ`) et l'unité (EUR). Des outils dédiés aux
questions courantes évitent que le LLM écrive du SQL, plus lent et plus risqué. `run_sql` reste le
dernier recours.

**Sécurité (un argument d'outil vient d'un LLM, donc d'une source non fiable).**
- Les filtres sont passés en **paramètres liés** (`?`), jamais concaténés au SQL. Les colonnes de tri
  et de regroupement sont choisies dans une liste fermée (`Literal`), et les valeurs énumérées sont
  validées.
- `run_sql` applique quatre barrières :
  1. une seule instruction, de type `SELECT`, selon l'analyseur de DuckDB lui-même ;
  2. une connexion neuve et jetable à chaque appel ;
  3. le bac à sable DuckDB : fichiers limités à `bronze/` et `silver/`, pas d'extension, pas
     d'`ATTACH`, configuration verrouillée ;
  4. un plafond de 500 lignes et 10 s d'exécution.
- Pourquoi la barrière 1 est nécessaire : un essai a montré que le bac à sable seul laissait passer
  `COPY … TO 'data/silver/x.parquet'`.

**Erreurs.** Une erreur renvoie `is_error` avec un message et un **indice** pour que le LLM se
corrige : valeurs permises, format de date, numéros de facture proches, colonnes candidates, ou
« appelez describe_schema ».

**Tests** (`tests/test_step7_mcp.py`) : un vrai client MCP lance le serveur en stdio sur un jeu de
données de test. Le test appelle chaque outil et vérifie ses résultats, puis tente 12 attaques par
`run_sql` (`DROP`, `DELETE`, `COPY` vers silver, `ATTACH`, `SET`, `INSTALL`, lecture de
`/etc/passwd` et de `.env`, double requête…). Toutes sont refusées, et aucun fichier n'est créé ni
modifié.

### Brancher le serveur

- **Claude Code** : `.mcp.json` à la racine du dépôt déclare le serveur `factures`. Lancer `claude`
  dans le dossier du projet, accepter le serveur, puis poser une question, par exemple « Quel est le
  montant TTC des factures en retard en 2025 ? ».
- **Claude Desktop** : dans `~/Library/Application Support/Claude/claude_desktop_config.json` :
  ```json
  { "mcpServers": { "factures": {
      "command": "uv",
      "args": ["run", "--directory", "/chemin/absolu/vers/factures-ia", "factures-mcp"] } } }
  ```

## Étape 8 — Agent

```bash
uv run factures agent                                   # conversation (LLM par défaut : Gemma sur l'AI Gateway)
uv run factures agent --llm ollama-ministral            # même agent, LLM local
uv run factures agent -q "Quel est le montant TTC des factures en retard en 2025 ?"
uv run factures agent-bench                             # mêmes questions sur tous les LLM → eval/agent_results.md
```

- **Uniquement les outils MCP.** L'agent lance le serveur MCP en sous-processus (stdio) et ne
  connaît que ses 5 outils : il n'a accès ni à DuckDB ni aux fichiers.
- **LLM interchangeable par configuration.** `llm_profiles.toml` déclare les profils (URL, modèle,
  variable d'environnement de la clé). On choisit avec `--llm`, avec `LLM_PROFILE` dans `.env`, ou
  pendant la conversation avec `/llm <profil>`. Tous parlent l'API « chat completions » avec appel
  d'outils, standard de fait (vLLM, Ollama, LM Studio, OpenAI, Mistral…). Ajouter un LLM revient à
  ajouter un bloc dans le fichier, sans toucher au code. Profils fournis : `hyperfluid-gemma`
  (défaut), `hyperfluid-granite`, `hyperfluid-nemotron` (AI Gateway Hyperfluid, même clé que
  l'OCR), et `ollama-ministral` (local).
- **Transparence.** Pour chaque étape, l'agent affiche l'outil appelé, ses arguments, le SQL exécuté
  avec ses paramètres et un aperçu du résultat, puis la réponse avec le modèle, le nombre d'appels et
  la durée.
- **Robustesse.** L'historique est conservé entre les questions (`/reset` pour l'effacer). La boucle
  est limitée à 8 appels au LLM par question. Les erreurs d'outil et le JSON invalide sont renvoyés
  au LLM pour qu'il se corrige. Si le LLM est injoignable, le tour est annulé proprement. On sort
  avec `/quit`, Ctrl-D ou Ctrl-C (la connexion MCP est fermée). Les jetons de contrôle laissés par
  certains modèles (`<|channel>thought…` de Gemma) sont retirés.
- **Ne pas inventer de chiffres.** Le prompt système impose que tout chiffre vienne d'un résultat
  d'outil, recopié tel quel, et interdit de calculer de tête. Le serveur fait les calculs en SQL
  (`invoice_totals`) et renvoie des montants exacts. La réponse cite sa source.

### Mêmes questions, quatre LLM — chiffres vérifiés par SQL ([détail](eval/agent_results.md))

Neuf questions, dont une qui fait appel à la mémoire de la conversation (« Et parmi elles… ») et
deux sans outil dédié, qui obligent le modèle à écrire son propre SQL. La bonne réponse est calculée
par une requête SQL directe sur l'entrepôt, indépendamment de l'agent.

| | Gemma 4 12B (hébergé) | Granite 4.2 8B (hébergé) | Nemotron Bolt E4B (hébergé) | Ministral 3 8B (local, Ollama) |
|---|---:|---:|---:|---:|
| 7 questions couvertes par un outil | 7/7 | 7/7 | 7/7 | 7/7 |
| 2 questions demandant du SQL libre | 2/2 | 2/2 | 0/2 (refus) | 0/2 (hors sujet) |
| Temps total (9 questions) | 26 s | 28 s | 14 s | 92 s |

Observations :
- **Avec des outils dédiés, même un petit modèle suffit.** Les 4 modèles ont tout juste sur les
  7 questions courantes, mémoire de conversation comprise. Les outils métier, des descriptions
  précises et des filtres tolérants (`en retard` est accepté pour `En retard`) déplacent la
  difficulté du LLM vers le serveur.
- **Le SQL libre sépare les modèles.** Gemma et Granite enchaînent correctement `describe_schema`,
  puis `run_sql` avec agrégation sur `invoice_lines`. Nemotron, le plus petit, ne pense pas à
  `run_sql` et répond honnêtement qu'aucun outil ne convient. Ministral répond à une autre question
  (factures au lieu d'articles, « toner noir » pris pour un fournisseur). C'est le cas le plus
  dangereux : la réponse a l'air sérieuse. **Aucun modèle n'a inventé de chiffre.**
- **Vitesse.** Le modèle local, sur le Mac, est environ 4 à 15 fois plus lent selon les questions
  (de 6 à 146 s observés). La latence grandit avec l'historique de la conversation. Les modèles
  hébergés sur GPU répondent en 1 à 5 s.
- **Fiabilité de l'infrastructure.** Pendant un passage, la passerelle a renvoyé des erreurs de
  connexion. L'agent les a affichées et a annulé le tour, sans planter. Un second passage complet a
  donné les résultats ci-dessus.
- **Vérifier le vérificateur.** Le premier correcteur automatique comptait faux « 229,000 unités »
  (quantité `DECIMAL(14,3)` lue comme 229 000) et comparait un flottant à un décimal. Les réponses de
  l'agent étaient justes : c'est le contrôle qui a été corrigé.

## Avancement

- [x] Étape 1 — Récupération des factures et détection texte / image
- [x] Étape 2 — Appel du modèle OCR LightOnOCR-3
- [x] Étape 3 — Couche bronze (incrémentale, traçable)
- [x] Étape 4 — Couche silver (typage, contrôles qualité, quarantaine)
- [x] Étape 5 — Évaluation de l'OCR
- [x] Étape 6 — Entrepôt de données
- [x] Étape 7 — Serveur MCP
- [x] Étape 8 — Agent (LLM interchangeable)
- [ ] Étape 9 — Industrialisation
