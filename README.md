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
```

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

- [ ] Étape 1 — Récupération des factures et détection texte / image
- [ ] Étape 2 — Appel du modèle OCR LightOnOCR-3
- [ ] Étape 3 — Couche bronze (incrémentale, traçable)
- [ ] Étape 4 — Couche silver (typage, contrôles qualité, quarantaine)
- [ ] Étape 5 — Évaluation de l'OCR
- [ ] Étape 6 — Entrepôt de données
- [ ] Étape 7 — Serveur MCP
- [ ] Étape 8 — Agent (LLM interchangeable)
- [ ] Étape 9 — Industrialisation
