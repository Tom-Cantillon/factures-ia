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
uv run factures run                # fetch + bronze en une commande
uv run factures status             # résumé landing / bronze / erreurs à retraiter

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

## Avancement

- [x] Étape 1 — Récupération des factures et détection texte / image
- [x] Étape 2 — Appel du modèle OCR LightOnOCR-3
- [x] Étape 3 — Couche bronze (incrémentale, traçable)
- [ ] Étape 4 — Couche silver (typage, contrôles qualité, quarantaine)
- [ ] Étape 5 — Évaluation de l'OCR
- [ ] Étape 6 — Entrepôt de données
- [ ] Étape 7 — Serveur MCP
- [ ] Étape 8 — Agent (LLM interchangeable)
- [ ] Étape 9 — Industrialisation
