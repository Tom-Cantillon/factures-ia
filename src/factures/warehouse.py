"""Étape 6 : l'entrepôt — rendre bronze et silver interrogeables en SQL, sans copier les données.

Séparation stockage / calcul :
- **stockage** : les fichiers Parquet de data/bronze et data/silver, seul et unique exemplaire ;
- **calcul** : DuckDB, qui lit ces fichiers à la demande. L'entrepôt ne contient que des **vues**
  (`CREATE VIEW … AS SELECT * FROM read_parquet(…)`), jamais de données.

Deux façons d'y accéder, pour que l'une ne bloque jamais l'autre :
- les **programmes** (CLI, serveur MCP, agent) appellent `connect()` : une base DuckDB *en mémoire*,
  propre au processus, dans laquelle on recrée les vues. Aucun fichier partagé, donc aucun verrou :
  autant de lecteurs simultanés qu'on veut ;
- les **outils graphiques** (DBeaver) ouvrent `data/warehouse.duckdb`, généré par
  `factures warehouse`. Un fichier DuckDB ouvert en écriture est verrouillé par son processus ;
  si DBeaver le verrouille, seuls les autres clients de *ce fichier* sont gênés, pas le pipeline.

Chemins : les vues pointent vers DATA_DIR, résolu **au moment de la connexion** (connect) ou de la
génération du fichier (warehouse). Rien n'est figé dans le dépôt : sur une autre machine ou dans un
conteneur (DATA_DIR=/data), on régénère et les références restent valides.
"""

from pathlib import Path

import duckdb

from factures import config

# schéma.vue → (dossier Parquet relatif à DATA_DIR, description, {colonne: description})
VIEWS: dict[str, tuple[str, str, dict[str, str]]] = {
    "bronze.documents": (
        "bronze/documents",
        "Texte brut extrait de chaque PDF (append-only, une ligne par extraction), avec sa traçabilité.",
        {
            "doc_id": "SHA-256 du PDF : identifiant du document",
            "extraction_method": "pdf_text (couche texte native), ocr ou mixte",
            "text": "Texte brut extrait (markdown pour l'OCR)",
            "ocr_params": "Paramètres exacts de l'appel OCR (JSON)",
            "run_id": "Exécution du pipeline qui a produit la ligne",
        },
    ),
    "bronze.extraction_errors": (
        "bronze/extraction_errors",
        "Journal des échecs d'extraction (OCR indisponible, PDF illisible). Un document en échec est retenté au run suivant.",
        {"stage": "pdf ou ocr", "attempts": "Nombre de tentatives avant abandon"},
    ),
    "silver.invoices": (
        "silver/invoices",
        "Factures fournisseurs propres et typées, une ligne par facture. Montants en euros (DECIMAL).",
        {
            "invoice_id": "Clé unique : SIRET fournisseur / numéro de facture",
            "invoice_number": "Numéro de facture tel qu'imprimé (ex. A-2025-0001)",
            "issue_date": "Date d'émission",
            "due_date": "Date d'échéance de paiement",
            "supplier_name": "Fournisseur (émetteur de la facture)",
            "client_name": "Client facturé",
            "category": "Catégorie : Conseil, Fournitures, Maintenance, Informatique",
            "status": "Statut de paiement : Payée, En attente, En retard",
            "payment_method": "Carte bancaire, Chèque, Prélèvement SEPA, Virement bancaire",
            "total_ht": "Total hors taxes (EUR)",
            "total_tva": "Total TVA (EUR)",
            "total_ttc": "Total toutes taxes comprises (EUR)",
            "quality_status": "valide, ou signalee si une anomalie a été détectée (voir quality_flags)",
            "quality_flags": "Codes des anomalies détectées (ex. TTC_INCOHERENT)",
            "quality_details": "Explication lisible de chaque anomalie",
            "doc_id": "Lien vers bronze.documents",
            "extraction_method": "pdf_text ou ocr",
        },
    ),
    "silver.invoice_lines": (
        "silver/invoice_lines",
        "Lignes de facture (articles / prestations). Jointure : invoice_lines.invoice_id = invoices.invoice_id.",
        {
            "line_no": "Position de la ligne dans la facture (1, 2, …)",
            "quantity": "Quantité",
            "unit_price_ht": "Prix unitaire HT (EUR)",
            "vat_rate": "Taux de TVA en % (ex. 20.00)",
            "line_total_ht": "Total HT de la ligne (EUR)",
        },
    ),
    "silver.quarantine": (
        "silver/quarantine",
        "Documents rejetés (non comptés dans silver.invoices) avec le motif du rejet.",
        {
            "reason_codes": "CHAMP_MANQUANT, FORMAT_INVALIDE ou DOUBLON",
            "reason_details": "Explication lisible du rejet",
            "duplicate_of": "Pour un doublon : doc_id de la facture retenue",
        },
    ),
}


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def view_statements(data_dir: Path = config.DATA_DIR) -> tuple[list[str], list[str]]:
    """Instructions SQL créant schémas, vues et commentaires. Retourne (instructions, vues ignorées)."""
    stmts = ["CREATE SCHEMA IF NOT EXISTS bronze", "CREATE SCHEMA IF NOT EXISTS silver"]
    skipped = []
    for name, (rel, desc, cols) in VIEWS.items():
        folder = (data_dir / rel).resolve()
        if not any(folder.glob("*.parquet")):
            skipped.append(name)  # table pas encore produite : la vue apparaîtra au prochain build
            continue
        stmts.append(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({_sql_str(str(folder / '*.parquet'))})")
        stmts.append(f"COMMENT ON VIEW {name} IS {_sql_str(desc)}")
        stmts += [f"COMMENT ON COLUMN {name}.{c} IS {_sql_str(d)}" for c, d in cols.items()]
    return stmts, skipped


def connect(data_dir: Path = config.DATA_DIR) -> duckdb.DuckDBPyConnection:
    """Connexion DuckDB en mémoire, propre à l'appelant, avec les vues bronze / silver."""
    con = duckdb.connect(":memory:")
    for stmt in view_statements(data_dir)[0]:
        con.execute(stmt)
    return con


def build_file(path: Path = config.DATA_DIR / "warehouse.duckdb", data_dir: Path = config.DATA_DIR) -> list[str]:
    """Génère le fichier DuckDB pour les outils graphiques (vues seulement, quelques Ko)."""
    stmts, skipped = view_statements(data_dir)
    tmp = path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        for stmt in stmts:
            con.execute(stmt)
    tmp.replace(path)  # bascule atomique ; échoue proprement si l'ancien fichier est verrouillé sous Windows
    return skipped
