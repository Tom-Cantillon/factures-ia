"""Étape 4 : couche silver — factures propres, typées et contrôlées, avec quarantaine.

La silver est **dérivée** de la bronze : elle est entièrement recalculée à chaque build (déterministe,
rapide, sans appel OCR). Si le parseur ou les règles changent, on relance `factures silver`.

Deux niveaux de sévérité :
- **rejet** → table `quarantine` (la facture n'entre pas dans `invoices`) : document inexploitable
  (identifiant, date ou montant TTC manquant / illisible) ou **doublon** d'une facture déjà retenue ;
- **signalement** → la facture entre dans `invoices` avec `quality_status = 'signalee'` et la liste
  des anomalies (`quality_flags`) : montants incohérents, SIRET/IBAN invalides, échéance avant
  émission… Elle existe bel et bien ; on ne la perd pas et on ne la « corrige » pas : un humain tranche.

Tables (data/silver/<table>/data.parquet) : invoices, invoice_lines, quarantine.
"""

import logging
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from factures import config
from factures.bronze import DOCUMENTS, _has_files, _table_glob
from factures.parser import PARSER_VERSION, parse_amount, parse_date, parse_invoice, parse_rate

log = logging.getLogger(__name__)

MONEY = pa.decimal128(14, 2)
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")

KNOWN_STATUS = {"Payée", "En attente", "En retard"}
KNOWN_CATEGORY = {"Conseil", "Fournitures", "Maintenance", "Informatique"}
KNOWN_PAYMENT = {"Carte bancaire", "Prélèvement SEPA", "Virement bancaire", "Chèque"}

INVOICES_SCHEMA = pa.schema([
    ("invoice_id", pa.string()),            # clé métier : SIRET fournisseur / numéro de facture
    ("invoice_number", pa.string()),
    ("issue_date", pa.date32()),
    ("due_date", pa.date32()),
    ("supplier_name", pa.string()),
    ("supplier_address", pa.string()),
    ("supplier_siret", pa.string()),
    ("supplier_vat_number", pa.string()),
    ("client_name", pa.string()),
    ("client_address", pa.string()),
    ("client_siret", pa.string()),
    ("category", pa.string()),
    ("status", pa.string()),
    ("payment_method", pa.string()),
    ("iban", pa.string()),
    ("currency", pa.string()),
    ("total_ht", MONEY),
    ("total_tva", MONEY),
    ("total_ttc", MONEY),
    ("line_count", pa.int32()),
    ("quality_status", pa.string()),        # valide | signalee
    ("quality_flags", pa.list_(pa.string())),
    ("quality_details", pa.list_(pa.string())),
    ("doc_id", pa.string()),                # lien vers bronze.documents
    ("file_name", pa.string()),
    ("s3_uri", pa.string()),
    ("extraction_method", pa.string()),
    ("bronze_run_id", pa.string()),
    ("parser_version", pa.string()),
    ("built_at", pa.timestamp("us", tz="UTC")),
])

LINES_SCHEMA = pa.schema([
    ("invoice_id", pa.string()),
    ("line_no", pa.int32()),
    ("description", pa.string()),
    ("quantity", pa.decimal128(14, 3)),
    ("unit_price_ht", MONEY),
    ("vat_rate", pa.decimal128(5, 2)),
    ("line_total_ht", MONEY),
    ("doc_id", pa.string()),
])

QUARANTINE_SCHEMA = pa.schema([
    ("doc_id", pa.string()),
    ("file_name", pa.string()),
    ("s3_uri", pa.string()),
    ("invoice_number", pa.string()),
    ("reason_codes", pa.list_(pa.string())),
    ("reason_details", pa.list_(pa.string())),
    ("duplicate_of", pa.string()),          # doc_id de la facture retenue, pour un doublon
    ("extraction_method", pa.string()),
    ("bronze_run_id", pa.string()),
    ("parser_version", pa.string()),
    ("quarantined_at", pa.timestamp("us", tz="UTC")),
])


# --------------------------------------------------------------------------- contrôles unitaires

def siret_format_ok(siret: str | None) -> bool:
    """SIRET : 14 chiffres.

    La clé de Luhn n'est PAS exigée : dans le jeu fourni, les SIRET sont fictifs et seuls ~10 % la
    respectent. L'exiger signalerait 100 % des factures et noierait les vraies anomalies.
    """
    return bool(siret) and siret.isdigit() and len(siret) == 14


def siret_luhn_ok(siret: str | None) -> bool:
    """Clé de Luhn d'un SIRET réel (non utilisée sur le jeu fictif, voir siret_format_ok)."""
    if not siret_format_ok(siret):
        return False
    total = 0
    for i, ch in enumerate(reversed(siret)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def iban_ok(iban: str | None) -> bool:
    """IBAN : clé de contrôle modulo 97 (ISO 13616)."""
    if not iban:
        return False
    s = iban.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s.isalnum():
        return False
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def _money(d: Decimal | None) -> Decimal | None:
    return None if d is None else d.quantize(CENT, rounding=ROUND_HALF_UP)


def _eq(a: Decimal | None, b: Decimal | None, tol: Decimal = TOLERANCE) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


# --------------------------------------------------------------------------- construction

def _check(doc: dict) -> tuple[dict | None, list[dict], dict | None]:
    """Parse + contrôle un document bronze. Retourne (facture, lignes, rejet)."""
    p = parse_invoice(doc["text"])
    f = p.fields
    rejects, flags = [], []

    def reject(code, detail):
        rejects.append((code, detail))

    def flag(code, detail):
        flags.append((code, detail))

    issue, due = parse_date(f.get("issue_date")), parse_date(f.get("due_date"))
    ht, tva, ttc = (parse_amount(f.get(k)) for k in ("total_ht", "total_tva", "total_ttc"))

    # --- rejets : sans ces champs, la facture n'est ni identifiable ni exploitable
    for key in ("invoice_number", "supplier_name", "client_name"):
        if not f.get(key):
            reject("CHAMP_MANQUANT", f"{key} absent")
    if not f.get("issue_date"):
        reject("CHAMP_MANQUANT", "issue_date absent")
    elif issue is None:
        reject("FORMAT_INVALIDE", f"issue_date illisible : {f['issue_date']!r}")
    if not f.get("total_ttc"):
        reject("CHAMP_MANQUANT", "total_ttc absent")
    elif ttc is None:
        reject("FORMAT_INVALIDE", f"total_ttc illisible : {f['total_ttc']!r}")

    # --- signalements : la facture est gardée, mais marquée
    for key, val in (("due_date", due), ("total_ht", ht), ("total_tva", tva)):
        if val is None:
            flag("CHAMP_ILLISIBLE", f"{key} absent ou illisible : {f.get(key)!r}")
    for problem in p.problems:
        flag("LIGNE_ILLISIBLE", problem)
    if not p.lines:
        flag("AUCUNE_LIGNE", "aucune ligne de facture lue")

    for ln in p.lines:
        if None not in (ln.quantity, ln.unit_price_ht, ln.line_total_ht) and not _eq(
            _money(ln.quantity * ln.unit_price_ht), ln.line_total_ht
        ):
            flag("LIGNE_CALCUL", f"ligne {ln.line_no} : {ln.quantity} × {ln.unit_price_ht} ≠ {ln.line_total_ht}")

    line_totals = [ln.line_total_ht for ln in p.lines]
    if p.lines and None not in line_totals and ht is not None:
        s = sum(line_totals, Decimal(0))
        if not _eq(s, ht):
            flag("SOMME_LIGNES_HT", f"somme des lignes {s} ≠ total HT {ht}")

    # TVA : par taux (base des lignes × taux) puis total
    vat_by_rate = {parse_rate(k.removeprefix("TVA ")): parse_amount(v) for k, v in p.vat_breakdown.items()}
    base_by_rate = defaultdict(Decimal)
    for ln in p.lines:
        if ln.vat_rate is not None and ln.line_total_ht is not None:
            base_by_rate[ln.vat_rate] += ln.line_total_ht
    for rate, base in base_by_rate.items():
        expected = _money(base * rate / 100)
        if rate in vat_by_rate and not _eq(vat_by_rate[rate], expected):
            flag("TVA_INCOHERENTE", f"TVA {rate} % : {vat_by_rate[rate]} ≠ {base} × {rate} % = {expected}")
    if vat_by_rate and tva is not None and None not in vat_by_rate.values():
        s = sum(vat_by_rate.values(), Decimal(0))
        if not _eq(s, tva):
            flag("TVA_INCOHERENTE", f"somme TVA par taux {s} ≠ total TVA {tva}")
    if None not in (ht, tva, ttc) and not _eq(ht + tva, ttc):
        flag("TTC_INCOHERENT", f"HT {ht} + TVA {tva} = {ht + tva} ≠ TTC {ttc}")

    if issue and due and due < issue:
        flag("ECHEANCE_AVANT_EMISSION", f"échéance {due} < émission {issue}")
    if not siret_format_ok(f.get("supplier_siret")):
        flag("SIRET_INVALIDE", f"SIRET fournisseur {f.get('supplier_siret')!r}")
    if not siret_format_ok(f.get("client_siret")):
        flag("SIRET_INVALIDE", f"SIRET client {f.get('client_siret')!r}")
    if not iban_ok(f.get("iban")):
        flag("IBAN_INVALIDE", f"IBAN {f.get('iban')!r}")
    for key, ref in (("status", KNOWN_STATUS), ("category", KNOWN_CATEGORY), ("payment_method", KNOWN_PAYMENT)):
        if f.get(key) not in ref:
            flag("VALEUR_INCONNUE", f"{key} = {f.get(key)!r}")

    now = datetime.now(timezone.utc)
    common = {
        "doc_id": doc["doc_id"], "file_name": doc["file_name"], "s3_uri": doc["s3_uri"],
        "extraction_method": doc["extraction_method"], "bronze_run_id": doc["run_id"],
        "parser_version": PARSER_VERSION,
    }
    if rejects:
        return None, [], {
            **common, "invoice_number": f.get("invoice_number"),
            "reason_codes": sorted({c for c, _ in rejects}), "reason_details": [d for _, d in rejects],
            "duplicate_of": None, "quarantined_at": now,
        }

    invoice_id = f"{f.get('supplier_siret') or f['supplier_name']}/{f['invoice_number']}"
    invoice = {
        "invoice_id": invoice_id, "invoice_number": f["invoice_number"],
        "issue_date": issue, "due_date": due,
        **{k: f.get(k) for k in ("supplier_name", "supplier_address", "supplier_siret", "supplier_vat_number",
                                 "client_name", "client_address", "client_siret", "category", "status",
                                 "payment_method", "iban")},
        "currency": "EUR",
        "total_ht": _money(ht), "total_tva": _money(tva), "total_ttc": _money(ttc),
        "line_count": len(p.lines),
        "quality_status": "signalee" if flags else "valide",
        "quality_flags": sorted({c for c, _ in flags}),
        "quality_details": [d for _, d in flags],
        **common, "built_at": now,
    }
    lines = [{
        "invoice_id": invoice_id, "line_no": ln.line_no, "description": ln.description,
        "quantity": ln.quantity, "unit_price_ht": _money(ln.unit_price_ht), "vat_rate": ln.vat_rate,
        "line_total_ht": _money(ln.line_total_ht), "doc_id": doc["doc_id"],
    } for ln in p.lines]
    return invoice, lines, None


def load_bronze(bronze_dir: Path) -> list[dict]:
    """Dernière extraction de chaque document (une ré-extraction en bronze remplace la précédente ici)."""
    if not _has_files(bronze_dir, DOCUMENTS):
        return []
    rel = duckdb.execute(
        """
        SELECT doc_id, file_name, s3_uri, extraction_method, run_id, text, extracted_at
        FROM read_parquet(?)
        QUALIFY row_number() OVER (PARTITION BY doc_id ORDER BY extracted_at DESC) = 1
        ORDER BY extracted_at, file_name
        """,
        [_table_glob(bronze_dir, DOCUMENTS)],
    )
    cols = [c[0] for c in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def build(bronze_dir: Path = config.BRONZE_DIR, silver_dir: Path = config.SILVER_DIR) -> dict:
    invoices, lines, quarantine = [], [], []
    kept: dict[str, str] = {}  # invoice_id → doc_id retenu

    for doc in load_bronze(bronze_dir):
        inv, inv_lines, rej = _check(doc)
        if rej:
            quarantine.append(rej)
            continue
        # Doublon : même facture (fournisseur + numéro) déjà retenue depuis un autre document.
        # On garde la première ingérée ; la suivante part en quarantaine avec un renvoi vers elle.
        if inv["invoice_id"] in kept:
            quarantine.append({
                "doc_id": inv["doc_id"], "file_name": inv["file_name"], "s3_uri": inv["s3_uri"],
                "invoice_number": inv["invoice_number"], "reason_codes": ["DOUBLON"],
                "reason_details": [f"facture {inv['invoice_id']} déjà présente (document {kept[inv['invoice_id']][:12]})"],
                "duplicate_of": kept[inv["invoice_id"]], "extraction_method": inv["extraction_method"],
                "bronze_run_id": inv["bronze_run_id"], "parser_version": PARSER_VERSION,
                "quarantined_at": inv["built_at"],
            })
            continue
        kept[inv["invoice_id"]] = inv["doc_id"]
        invoices.append(inv)
        lines.extend(inv_lines)

    # Écriture dans un dossier temporaire puis bascule : les lecteurs ne voient jamais une silver à moitié écrite.
    tmp = silver_dir.with_name(silver_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    for name, rows, schema in (("invoices", invoices, INVOICES_SCHEMA), ("invoice_lines", lines, LINES_SCHEMA),
                               ("quarantine", quarantine, QUARANTINE_SCHEMA)):
        (tmp / name).mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp / name / "data.parquet")
    old = silver_dir.with_name(silver_dir.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if silver_dir.exists():
        silver_dir.rename(old)
    tmp.rename(silver_dir)
    shutil.rmtree(old, ignore_errors=True)

    return {
        "invoices": len(invoices),
        "valides": sum(i["quality_status"] == "valide" for i in invoices),
        "signalees": sum(i["quality_status"] == "signalee" for i in invoices),
        "lines": len(lines),
        "quarantine": len(quarantine),
    }
