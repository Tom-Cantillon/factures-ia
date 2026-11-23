# Étape 9 — Industrialisation

> Objectif : faire tourner la chaîne **en production**, pour **des milliers de factures par mois** et
> **plusieurs utilisateurs**. Ce document fixe des priorités argumentées. La dernière section liste ce qui
> est **déjà implémenté** dans le dépôt.

## 1. Hypothèses de dimensionnement

| Grandeur | Valeur retenue | Origine |
|---|---|---|
| Volume | 5 000 factures / mois, avec un pic en fin de mois (×5 sur 3 jours) | énoncé (« des milliers ») |
| Part de scans | 50 %, 1 à 2 pages | jeu fourni |
| OCR | 7,6 s / page, 4 appels en parallèle → ≈ 2 s / page effectives | mesuré (étape 3) |
| Utilisateurs | 10 à 50 (comptabilité, contrôle de gestion, direction) | hypothèse |
| Fraîcheur attendue | une facture déposée est interrogeable en moins d'une heure | hypothèse métier |

**Ordre de grandeur OCR** : 2 500 à 3 000 pages scannées par mois, soit environ 1 h 30 de calcul à
4 appels en parallèle, et environ 25 min pour le pic d'une journée. **Le volume n'est pas le problème.
Les vrais risques sont la sécurité (données financières, IBAN), la fiabilité (une erreur silencieuse
coûte un paiement) et l'exploitation (savoir quand ça casse).** D'où les priorités ci-dessous.

## 2. Architecture cible

```
                ┌──────────── Hyperfluid ────────────────────────────────────────────────┐
 Fournisseurs   │  S3 factures ──(notification)──► file de messages ──► workers d'ingestion│
 (PDF, e-mail)──┼─►  (WORM)                                       │  conteneurs, N réplicas │
                │                                                 ├─► AI Gateway : OCR (vLLM, autoscaling GPU)
                │                                                 ▼                         │
                │                         S3 default-bronze  (Parquet → Iceberg, append-only)│
                │                                   │ job silver (incrémental, par run_id)  │
                │                         S3 default-silver  + quarantaine ─► file de revue humaine
                │                                   │ (gold : agrégats métier)              │
                │      moteur SQL (DuckDB par processus → Trino si concurrence forte)       │
                │                                   │                                       │
                │   serveur MCP HTTP (lecture seule, OAuth, journal d'audit) ◄── agent / UI web
                │                                   │                         ◄── Claude Desktop, DBeaver (RO)
                │   Supervision : métriques, journaux structurés, traces, alertes          │
                └────────────────────────────────────────────────────────────────────────┘
```

## 3. Priorités, dans l'ordre, et pourquoi

### P1 — Sécurité des accès, des secrets et des données (priorité maximale)

Les factures contiennent des **IBAN**, des SIRET et des montants. Une fuite ou une modification
frauduleuse d'IBAN est le risque n° 1 du domaine, devant la performance.

- **Secrets** : jamais dans l'image ni dans le dépôt (c'est déjà le cas : `.env` est ignoré par Git et
  injecté au démarrage). En production, ils passent par un gestionnaire de secrets (Vault, ou celui de
  la plateforme) avec **rotation** des clés.
- **Moindre privilège, déjà appliqué** : clé S3 en **lecture seule** sur `factures` ; serveur MCP
  **en lecture seule** à quatre niveaux, dont un conteneur au système de fichiers `read_only`. Leçon
  de l'étape 2 : le scope `model:inference` était insuffisant et il a fallu `model:*`. En production,
  on demande à la plateforme un scope limité aux deux modèles utilisés.
- **Authentification du serveur MCP HTTP** : le SDK MCP prend en charge OAuth 2.1 (`token_verifier`).
  Chaque utilisateur s'authentifie, chaque requête SQL est **journalisée avec son auteur** (aujourd'hui,
  le journal existe sans l'identité), et on peut ajouter des filtres par rôle (un acheteur ne voit que
  ses fournisseurs).
- **Injection de prompt** : le texte des factures vient de tiers, donc il n'est pas fiable. Une facture
  pourrait contenir « ignore tes consignes ». Les défenses en place : l'agent ne lit que des **données
  structurées** de la silver, jamais le texte OCR brut, et **aucun outil n'a d'effet de bord** (lecture
  seule). À ne jamais faire : donner à l'agent un outil « payer » ou « modifier l'IBAN ».
- **RGPD** : noms et adresses de clients personnes physiques. Il faut une durée de conservation, des
  journaux sans données personnelles et des accès tracés.
- **Fraude** : contrôle « l'IBAN d'un fournisseur a changé », envisagé à l'étape 4. Il devient une
  **alerte bloquante** avant tout paiement.

### P2 — Automatisation et fiabilité des traitements

- **Déclenchement par événement** : une notification S3 à chaque nouveau PDF alimente une file de
  messages, que lisent des workers. Un *cron* toutes les 15 minutes est une alternative suffisante au
  départ, car `factures run` est **idempotent**.
- **Le pipeline est déjà conçu pour être relancé sans risque** : identité par SHA-256, bronze
  append-only, écritures atomiques, reprise automatique des échecs. Rejouer un run, ou en lancer deux
  par erreur, n'abîme rien. C'est ce qui rend l'automatisation sûre.
- **Orchestrateur** (Dagster, Prefect ou Airflow) quand les étapes se multiplient (silver, gold,
  évaluation) : dépendances, reprises, historique des runs et *backfills*.
- **Boucle humaine** : la quarantaine et les factures signalées alimentent une **file de revue**. Les
  corrections humaines enrichissent la **vérité terrain**, qui sert de test de non-régression (P4).

### P3 — Montée en charge de l'OCR et du stockage

- **OCR** : le goulot est le GPU. Pistes, dans l'ordre :
  1. réglage du parallélisme (`--workers`) avec respect des limites de débit de la passerelle ;
  2. plusieurs réplicas vLLM derrière la passerelle, avec autoscaling sur la longueur de la file ;
  3. traitement de nuit pour le stock et en continu pour le flux.

  Le coupe-circuit et les reprises sont déjà en place. Ne pas descendre sous 1540 px : l'étape 5
  montre qu'une image plus petite fait perdre la qualité, pour seulement 30 % de vitesse en plus.
- **Stockage** :
  - déplacer bronze et silver vers les buckets S3 de la plateforme (`default-bronze`,
    `default-silver`), qui sont durables et versionnés ;
  - passer à **Apache Iceberg** (ou Delta) : transactions ACID, écrivains concurrents, *time travel*
    pour l'audit (« que disait la silver le 31/03 ? »), partitionnement par mois.
- **Silver incrémentale** : aujourd'hui, elle est recalculée en entier en moins d'une seconde pour
  100 factures. Au-delà d'environ 100 000, on ne traite que les nouveaux `run_id` de la bronze, avec
  une fusion (MERGE) sur `invoice_id`.
- **Calcul SQL** : DuckDB par processus suffit pour quelques dizaines d'utilisateurs, car les lectures
  sont parallèles et sans verrou. Au-delà, ou si plusieurs équipes accèdent aux mêmes données, on
  passe à **Trino** sur Iceberg. Le serveur MCP ne change pas, seule la connexion change.

### P4 — Tests et non-régression des modèles

- **CI** (implémentée) : à chaque push, les 38 tests (pipeline, parseur, contrôles, attaques contre le
  serveur MCP, boucle de l'agent avec un faux LLM) et la construction de l'image Docker.
- **Changer de modèle d'OCR, de résolution ou de version** devient une décision mesurée :
  `factures eval --synthetic` sert de test de non-régression, avec un seuil (par exemple « 100 % de
  factures exactes à 1540 px ») qui bloque le déploiement en dessous. Le générateur de faux scans
  permet d'augmenter l'échantillon sans coût humain.
- **Changer de LLM ou de prompt** : `factures agent-bench`, avec des réponses vérifiées par SQL. Le
  banc a révélé que les petits modèles échouent sur le SQL libre, et qu'un LLM peut répondre à côté
  sans inventer de chiffre (Ministral). D'où :
  - garder des **outils dédiés** pour les questions fréquentes ;
  - router le SQL libre vers un modèle plus grand.
- **Tests de contrat par fournisseur** : une nouvelle mise en page de facture est la première cause
  probable de casse du parseur. On ajoute un PDF exemple et ses valeurs attendues pour chaque nouveau
  fournisseur.

### P5 — Supervision

| À mesurer | Pourquoi | Alerte si… |
|---|---|---|
| Documents en attente, durée d'un run | fraîcheur | une facture n'est pas en silver après 1 h |
| Latence OCR p50 / p95, taux d'erreur, coupe-circuit ouvert | santé du GPU et de la passerelle | coupe-circuit ouvert, p95 > 30 s |
| **Taux de factures signalées ou en quarantaine, par fournisseur** | dérive de qualité (nouvelle mise en page, OCR dégradé) | hausse brutale pour un fournisseur |
| Appels d'outils MCP, erreurs, durée SQL, tokens LLM | usage, coûts, abus | requêtes refusées en série (tentatives d'écriture) |

Il faut des journaux structurés (JSON) avec `run_id` et `doc_id` pour remonter d'un chiffre au PDF
source (la traçabilité existe déjà dans les données), des traces de l'agent (outil, SQL, durée,
tokens) et des tableaux de bord (Grafana ou supervision Hyperfluid). L'onglet **Qualité** de
l'interface web en est un premier aperçu.

### P6 — Coûts

- **OCR** : environ 3 000 pages par mois, soit quelques heures de GPU partagé. C'est marginal si le
  GPU est mutualisé, et les PDF natifs (50 %) ne coûtent **rien** grâce à la détection texte / image.
- **LLM** : le poste qui croît avec le nombre d'utilisateurs. Leviers mesurés : un modèle 8–12B suffit
  pour les questions courantes (7/7 au banc), on réserve un modèle plus grand au SQL libre, on met en
  cache les questions fréquentes (les données ne changent qu'à chaque run) et on limite le nombre
  d'étapes par question (8, déjà en place).
- **Stockage** : négligeable (100 factures ≈ 15 Mo de PDF, quelques Mo de Parquet).

## 4. Déjà implémenté dans ce dépôt

| Élément | Fichier | Ce qu'il apporte |
|---|---|---|
| Image Docker unique (non-root, sans secret, données en volume) | `Dockerfile`, `.dockerignore` | même binaire partout : poste, CI, cluster |
| Pile locale « comme en prod » | `compose.yaml` | `pipeline` (tâche ponctuelle), `mcp` (HTTP, **système de fichiers en lecture seule**, données montées `:ro`), `ui` |
| Serveur MCP en HTTP | `MCP_TRANSPORT=http` | un seul serveur partagé par plusieurs utilisateurs et clients |
| Intégration continue | `.github/workflows/ci.yml` | tests et construction de l'image à chaque push |
| Interface web | `factures ui` | plusieurs utilisateurs dans un navigateur, sans terminal ; supervision de la qualité |
| Configuration par l'environnement | `.env`, `DATA_DIR`, `LLM_PROFILE`, `OLLAMA_HOST_URL` | 12-factor : même code en local, en conteneur ou en production |
| Idempotence, reprises, coupe-circuit, écritures atomiques | `bronze.py`, `silver.py` | automatisation sans risque |
| Bancs d'évaluation OCR et agent | `factures eval`, `factures agent-bench` | non-régression mesurée lors d'un changement de modèle |

Vérifié :
- `docker compose run --rm pipeline` exécute le pipeline complet en conteneur (incrémental : 0 appel OCR) ;
- `docker compose up mcp` sert le MCP en HTTP sur `localhost:8000`, appelé par un client MCP : bonne
  réponse, et `COPY` refusé ;
- l'interface tourne sur `localhost:8502`.

Constat à la mise en conteneur : `data/warehouse.duckdb` généré dans le conteneur pointe vers
`/data/...`, donc il est inutilisable par DBeaver sur la machine. C'est la question de l'étape 6, qui
confirme le choix de **régénérer** ce fichier là où on le consulte (`factures warehouse`) plutôt que
de le partager. L'image pèse **2,4 Go** (pyarrow, PyMuPDF, Streamlit). En production, on la scinde en
deux images, ingestion d'un côté, MCP et interface de l'autre.

## 5. Feuille de route proposée

| Phase | Durée | Contenu |
|---|---|---|
| 1. Socle | 2 semaines | secrets dans un gestionnaire, auth OAuth sur le MCP, cron d'ingestion en conteneur, alertes de base (run en échec, coupe-circuit) |
| 2. Données | 3 semaines | Parquet → Iceberg sur S3 Hyperfluid, silver incrémentale, couche gold, tests de contrat par fournisseur |
| 3. Échelle et qualité | continu | file de messages et workers, autoscaling OCR, file de revue humaine reliée à la vérité terrain, tableaux de bord qualité par fournisseur, routage des LLM par difficulté |
