"""Couche gold (bonus) : indicateurs métier calculés depuis la silver.

Ce sont des factures **fournisseurs** : on parle donc de dépenses (achats) et d'encours à payer.

Tables (data/gold/<table>/data.parquet), recalculées entièrement à chaque `factures gold` :
- monthly_spend       dépense mensuelle (par mois d'émission) : nombre, HT, TVA, TTC, dont payé / à payer
- supplier_balance    par fournisseur : total facturé, payé, encours, dont échu, délai de paiement moyen
- aging               balance âgée de l'encours : par fournisseur et tranche de retard à la date d'arrêté

Choix :
- **Factures signalées exclues des montants** : leur montant est douteux (ex. TTC ≠ HT + TVA). Elles
  sont comptées à part (`flagged_count`, `flagged_ttc`) pour que rien ne disparaisse sans le dire.
- **Le retard se calcule sur l'échéance, pas seulement sur le statut imprimé** : une facture non payée
  dont l'échéance est passée est échue, même si la facture dit « En attente ». Ces cas sont comptés
  dans `status_outdated` (statut à mettre à jour).
- Date d'arrêté (`as_of`) : aujourd'hui par défaut, stockée dans chaque table pour la traçabilité.
"""

import shutil
from datetime import date
from pathlib import Path

from factures import config
from factures.warehouse import connect

GOLD_SQL = {
    "monthly_spend": """
        SELECT strftime(issue_date, '%Y-%m')                                        AS month,
               count(*) FILTER (quality_status = 'valide')                          AS invoice_count,
               coalesce(sum(total_ht)  FILTER (quality_status = 'valide'), 0)       AS total_ht,
               coalesce(sum(total_tva) FILTER (quality_status = 'valide'), 0)       AS total_tva,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide'), 0)       AS total_ttc,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide' AND status = 'Payée'), 0)  AS paid_ttc,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide' AND status <> 'Payée'), 0) AS unpaid_ttc,
               count(*) FILTER (quality_status = 'signalee')                        AS flagged_count,
               coalesce(sum(total_ttc) FILTER (quality_status = 'signalee'), 0)     AS flagged_ttc,
               $as_of::DATE                                                         AS as_of
        FROM silver.invoices GROUP BY 1 ORDER BY 1""",
    "supplier_balance": """
        SELECT supplier_name,
               count(*) FILTER (quality_status = 'valide')                                          AS invoice_count,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide'), 0)                       AS invoiced_ttc,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide' AND status = 'Payée'), 0)  AS paid_ttc,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide' AND status <> 'Payée'), 0) AS outstanding_ttc,
               coalesce(sum(total_ttc) FILTER (quality_status = 'valide' AND status <> 'Payée'
                                                AND due_date < $as_of::DATE), 0)                    AS overdue_ttc,
               count(*) FILTER (quality_status = 'valide' AND status <> 'Payée' AND due_date < $as_of::DATE) AS overdue_count,
               min(due_date) FILTER (status <> 'Payée')                                             AS oldest_unpaid_due_date,
               round(avg(due_date - issue_date), 1)                                                 AS avg_payment_terms_days,
               count(*) FILTER (status = 'En attente' AND due_date < $as_of::DATE)                  AS status_outdated,
               count(*) FILTER (quality_status = 'signalee')                                        AS flagged_count,
               coalesce(sum(total_ttc) FILTER (quality_status = 'signalee'), 0)                     AS flagged_ttc,
               $as_of::DATE                                                                         AS as_of
        FROM silver.invoices GROUP BY 1 ORDER BY outstanding_ttc DESC, supplier_name""",
    "aging": """
        WITH unpaid AS (
            SELECT supplier_name, total_ttc, $as_of::DATE - due_date AS days_past_due
            FROM silver.invoices WHERE status <> 'Payée' AND quality_status = 'valide')
        SELECT supplier_name,
               CASE WHEN days_past_due <= 0  THEN '0. non échu'
                    WHEN days_past_due <= 30 THEN '1. 1-30 j'
                    WHEN days_past_due <= 60 THEN '2. 31-60 j'
                    WHEN days_past_due <= 90 THEN '3. 61-90 j'
                    ELSE '4. > 90 j' END                AS bucket,
               count(*)                                  AS invoice_count,
               sum(total_ttc)                            AS amount_ttc,
               max(days_past_due)                        AS max_days_past_due,
               $as_of::DATE                              AS as_of
        FROM unpaid GROUP BY 1, 2 ORDER BY 1, 2""",
}


def build(data_dir: Path = config.DATA_DIR, as_of: date | None = None) -> dict[str, int]:
    """Recalcule les tables gold depuis la silver (écriture dans un dossier temporaire puis bascule)."""
    as_of = as_of or date.today()
    con = connect(data_dir)
    gold_dir = data_dir / "gold"
    tmp = data_dir / "gold.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    counts = {}
    for name, sql in GOLD_SQL.items():
        (tmp / name).mkdir(parents=True)
        out = (tmp / name / "data.parquet").as_posix()
        con.execute(f"COPY ({sql}) TO '{out}' (FORMAT parquet)", {"as_of": as_of})
        counts[name] = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    old = data_dir / "gold.old"
    shutil.rmtree(old, ignore_errors=True)
    if gold_dir.exists():
        gold_dir.rename(old)
    tmp.rename(gold_dir)
    shutil.rmtree(old, ignore_errors=True)
    return counts
