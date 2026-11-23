"""Tests de l'étape 4 : parseur robuste (natif / OCR), typage, contrôles qualité et quarantaine."""

from datetime import date, datetime, timezone
from decimal import Decimal

import duckdb
import pytest

from factures.bronze import DOCUMENTS, DOCUMENTS_SCHEMA, _write_part
from factures.parser import parse_amount, parse_invoice
from factures.silver import build, iban_ok

NATIVE = """Aubry
96, avenue de Meyer
24403 Boyer
SIRET : 77360260298050
TVA intracom. : FR09773602602
FACTURE
Numéro de facture : {num}
Date d'émission : 10/01/2025
Date d'échéance : 11/03/2025
Catégorie : Conseil
Statut : Payée
Facturé à :
Client : Lombard
86, rue William Bègue
88105 Sainte Matthieu
SIRET client : 20037917087083
Désignation
Qté
Prix unitaire HT
TVA
Total HT
Formation DuckDB
2
100,00 €
20 %
200,00 €
Audit
1
1 000,50 €
20 %
1 000,50 €
Total HT
1 200,50 €
TVA 20 %
240,10 €
Total TVA
240,10 €
Total TTC
{ttc}
Mode de paiement : Chèque
IBAN : FR1578820812191361939909169
"""

OCR = """# FACTURE

**Aubry**
96, avenue de Meyer
24403 Boyer
SIRET : 77360260298050
TVA intracom. : FR09773602602

---

**Numéro de facture** : {num}
**Date d'émission** : 10/01/2025
**Date d'échéance** : 11/03/2025
**Catégorie** : Conseil
**Statut** : Payée

**Facturé à** :
Client : Lombard
86, rue William Bègue
88105 Sainte Matthieu
SIRET client : 20037917087083

<table><thead><tr><th>Désignation</th><th>Qté</th><th>Prix unitaire HT</th><th>TVA</th><th>Total HT</th></tr></thead>
<tbody><tr><td>Formation DuckDB</td><td>2</td><td>100,00 €</td><td>20 %</td><td>200,00 €</td></tr>
<tr><td>Audit</td><td>1</td><td>1 000,50 €</td><td>20 %</td><td>1 000,50 €</td></tr></tbody></table>

{totals}

**Mode de paiement** : Chèque
**IBAN** : FR1578820812191361939909169
"""
TOTALS_LINES = "**Total HT** 1 200,50 €  \n**TVA 20 %** 240,10 €  \n**Total TVA** 240,10 €  \n**Total TTC** {ttc}"
TOTALS_TABLE = ("<table><tbody><tr><td>Total HT</td><td>1 200,50 €</td></tr><tr><td>TVA 20 %</td><td>240,10 €</td></tr>"
                "<tr><td>Total TVA</td><td>240,10 €</td></tr><tr><td>Total TTC</td><td>{ttc}</td></tr></tbody></table>")


def native(num="A-1", ttc="1 440,60 €"):
    return NATIVE.format(num=num, ttc=ttc)


def ocr(num="A-1", ttc="1 440,60 €", table=False):
    return OCR.format(num=num, totals=(TOTALS_TABLE if table else TOTALS_LINES).format(ttc=ttc))


@pytest.mark.parametrize("s, expected", [
    ("1 261,21 €", Decimal("1261.21")), ("1 261,21 €", Decimal("1261.21")), ("1.261,21", Decimal("1261.21")),
    ("1261.21", Decimal("1261.21")), ("12", Decimal("12")), ("abc", None), ("1,2,3", None),
])
def test_parse_amount(s, expected):
    assert parse_amount(s) == expected


@pytest.mark.parametrize("text", [native(), ocr(), ocr(table=True)], ids=["natif", "ocr-lignes", "ocr-tableau"])
def test_parser_gives_same_result_for_native_and_ocr(text):
    p = parse_invoice(text)
    f = p.fields
    assert (f["invoice_number"], f["supplier_name"], f["client_name"]) == ("A-1", "Aubry", "Lombard")
    assert f["client_address"] == "86, rue William Bègue, 88105 Sainte Matthieu"
    assert (f["total_ht"], f["total_tva"], f["total_ttc"]) == ("1 200,50 €", "240,10 €", "1 440,60 €")
    assert [(ln.description, ln.quantity, ln.line_total_ht) for ln in p.lines] == [
        ("Formation DuckDB", Decimal(2), Decimal("200.00")), ("Audit", Decimal(1), Decimal("1000.50"))]
    assert p.problems == []


def test_iban_checksum():
    assert iban_ok("FR1578820812191361939909169")
    assert not iban_ok("FR1578820812191361939909168")  # un chiffre mal lu par l'OCR


def _bronze(tmp_path, texts):
    rows = [{**{k: None for k in DOCUMENTS_SCHEMA.names}, "doc_id": f"{i:064d}", "file_name": f"f{i}.pdf",
             "extraction_method": "ocr", "run_id": "r", "text": t,
             "extracted_at": datetime(2026, 1, 1, i, tzinfo=timezone.utc)} for i, t in enumerate(texts)]
    _write_part(tmp_path / "bronze", DOCUMENTS, rows, DOCUMENTS_SCHEMA, "r", 0)
    return tmp_path / "bronze"


def _q(silver, table, sql):
    duckdb.execute(f"CREATE OR REPLACE VIEW t AS SELECT * FROM read_parquet('{silver / table / 'data.parquet'}')")
    return duckdb.execute(sql).fetchall()


def test_silver_statuses_quarantine_and_types(tmp_path):
    bronze = _bronze(tmp_path, [
        native("A-1"),                          # valide
        ocr("A-2", ttc="99 999,99 €"),          # montants incohérents → signalée
        ocr("A-1"),                             # même facture que A-1 → doublon
        native("").replace("Numéro de facture : \n", ""),  # pas de numéro → rejet
        ocr("A-3", table=True).replace("10/01/2025", "10/13/2025"),  # date d'émission impossible → rejet
    ])
    silver = tmp_path / "silver"
    stats = build(bronze, silver)
    assert stats == {"invoices": 2, "valides": 1, "signalees": 1, "lines": 4, "quarantine": 3}

    rows = _q(silver, "invoices", "SELECT invoice_number, quality_status, quality_flags, issue_date, total_ttc, "
                                  "typeof(total_ttc) FROM t ORDER BY 1")
    assert rows[0] == ("A-1", "valide", [], date(2025, 1, 10), Decimal("1440.60"), "DECIMAL(14,2)")
    assert rows[1][:3] == ("A-2", "signalee", ["TTC_INCOHERENT"])

    rejects = _q(silver, "quarantine", "SELECT file_name, reason_codes, duplicate_of IS NOT NULL FROM t ORDER BY 1")
    assert rejects == [("f2.pdf", ["DOUBLON"], True), ("f3.pdf", ["CHAMP_MANQUANT"], False),
                       ("f4.pdf", ["FORMAT_INVALIDE"], False)]


def test_line_and_vat_inconsistencies_are_flagged(tmp_path):
    text = native("B-1").replace("200,00 €\nAudit", "210,00 €\nAudit").replace("TVA 20 %\n240,10", "TVA 20 %\n250,10")
    build(_bronze(tmp_path, [text]), tmp_path / "silver")
    (flags,) = _q(tmp_path / "silver", "invoices", "SELECT quality_flags FROM t")[0]
    assert {"LIGNE_CALCUL", "SOMME_LIGNES_HT", "TVA_INCOHERENTE"} <= set(flags)
