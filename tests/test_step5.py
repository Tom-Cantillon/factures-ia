"""Tests de l'étape 5 : comparaison champ par champ et jeu synthétique (sans appel OCR)."""

import pymupdf

from factures.evaluate import FIELDS, compare, degrade, fields_from_text, sample_scans, score
from factures.ocr import render_page
from test_step4 import native, ocr

TRUTH = {
    "invoice_number": "A-1", "issue_date": "2025-01-10", "due_date": "2025-03-11", "supplier_name": "Aubry",
    "supplier_siret": "77360260298050", "supplier_vat_number": "FR09773602602", "client_name": "Lombard",
    "client_siret": "20037917087083", "category": "Conseil", "status": "Payée", "payment_method": "Chèque",
    "iban": "FR1578820812191361939909169", "total_ht": "1200.50", "total_tva": "240.10", "total_ttc": "1440.60",
    "line_count": "2",
    "lines": [
        {"description": "Formation DuckDB", "quantity": "2", "unit_price_ht": "100.00", "vat_rate": "20", "line_total_ht": "200.00"},
        {"description": "Audit", "quantity": "1", "unit_price_ht": "1000.50", "vat_rate": "20", "line_total_ht": "1000.50"},
    ],
}


def test_perfect_prediction_scores_100_percent_for_both_text_shapes():
    for text in (native(), ocr(), ocr(table=True)):
        assert all(compare(fields_from_text(text), TRUTH).values())


def test_one_misread_digit_fails_only_its_field():
    res = compare(fields_from_text(ocr(ttc="1 440,80 €")), TRUTH)
    assert [k for k, ok in res.items() if not ok] == ["total_ttc"]


def test_missing_document_counts_wrong_everywhere_and_score_aggregates():
    r = score("x", {"a.pdf": fields_from_text(native())}, {"a.pdf": TRUTH, "b.pdf": TRUTH}, [1.0, 3.0])
    assert r.n == 2 and r.docs_all_correct == 1 and r.seconds_per_page == 2.0
    assert set(r.per_field) == set(FIELDS) and all(v == 0.5 for v in r.per_field.values())


def test_degrade_is_deterministic_and_changes_the_image(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "FACTURE")
    doc.save(tmp_path / "n.pdf")
    png = render_page(tmp_path / "n.pdf", longest_side=400)
    assert degrade(png, 7) == degrade(png, 7) != png


def test_sample_is_reproducible_and_spread_across_suppliers(tmp_path):
    for name in ["facture_A-1_scan.pdf", "facture_A-2_scan.pdf", "facture_B-1_scan.pdf", "facture_C-1_scan.pdf",
                 "facture_C-2_texte.pdf"]:
        (tmp_path / name).touch()
    s = sample_scans(3, landing_dir=tmp_path)
    assert s == sample_scans(3, landing_dir=tmp_path)
    assert {f.split("_")[1][0] for f in s} == {"A", "B", "C"} and all("_scan" in f for f in s)
