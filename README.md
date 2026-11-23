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

## Avancement

- [x] Étape 1 — Récupération des factures et détection texte / image
- [ ] Étape 2 — Appel du modèle OCR LightOnOCR-3
- [ ] Étape 3 — Couche bronze (incrémentale, traçable)
- [ ] Étape 4 — Couche silver (typage, contrôles qualité, quarantaine)
- [ ] Étape 5 — Évaluation de l'OCR
- [ ] Étape 6 — Entrepôt de données
- [ ] Étape 7 — Serveur MCP
- [ ] Étape 8 — Agent (LLM interchangeable)
- [ ] Étape 9 — Industrialisation
