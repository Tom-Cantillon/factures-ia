"""Tests de l'étape 3 : couche bronze incrémentale, traçable et tolérante aux pannes d'OCR."""

import duckdb
import pymupdf

from factures.bronze import DOCUMENTS, ERRORS, ingest
from factures.ocr import OcrResult


def _text_pdf(path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "FACTURE N° T-1 Total TTC 100,00 EUR Client Test SARL")
    doc.save(path)


def _scan_pdf(path, label):
    src = pymupdf.open()
    src.new_page().insert_text((72, 72), f"FACTURE {label}")
    pix = src[0].get_pixmap(dpi=50)
    doc = pymupdf.open()
    doc.new_page().insert_image(doc[0].rect, pixmap=pix)
    doc.save(path)


def _landing(tmp_path):
    landing = tmp_path / "landing"
    landing.mkdir()
    _text_pdf(landing / "t1.pdf")
    _scan_pdf(landing / "s1.pdf", "S1")
    _scan_pdf(landing / "s2.pdf", "S2")
    return landing


class FakeEngine:
    name, model = "fake", "fake-1"

    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, 0

    def ocr_png(self, png):
        self.calls += 1
        if self.fail:
            raise ConnectionError("service OCR injoignable")
        return OcrResult(text="# FACTURE (ocr)", engine=self.name, model=self.model, seconds=0.01,
                         params={"temperature": 0.2}, usage={"prompt_tokens": 5, "completion_tokens": 2})


def _count(bronze, table):
    return duckdb.execute("SELECT count(*) FROM read_parquet(?)", [str(bronze / table / "*.parquet")]).fetchone()[0]


def test_second_run_adds_nothing_and_calls_no_ocr(tmp_path):
    landing, bronze = _landing(tmp_path), tmp_path / "bronze"
    engine = FakeEngine()

    first = ingest(lambda: engine, landing, bronze, workers=1, backoff=0)
    assert len(first.extracted) == 3 and engine.calls == 2  # seuls les 2 scans passent par l'OCR

    second = ingest(lambda: engine, landing, bronze, workers=1, backoff=0)
    assert second.extracted == [] and second.already_done == 3
    assert engine.calls == 2 and _count(bronze, DOCUMENTS) == 3


def test_traceability_columns(tmp_path):
    landing, bronze = _landing(tmp_path), tmp_path / "bronze"
    ingest(lambda: FakeEngine(), landing, bronze, workers=1, backoff=0)
    rows = duckdb.execute(
        "SELECT file_name, extraction_method, ocr_engine, ocr_params, length(doc_id), run_id IS NOT NULL "
        "FROM read_parquet(?) ORDER BY file_name", [str(bronze / DOCUMENTS / "*.parquet")]
    ).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("s1.pdf", "ocr", "fake"), ("s2.pdf", "ocr", "fake"), ("t1.pdf", "pdf_text", None)
    ]
    assert all(r[4] == 64 and r[5] for r in rows)  # SHA-256 + run_id présents
    assert rows[0][3] == '{"temperature": 0.2}'


def test_ocr_outage_is_logged_and_retried_later(tmp_path):
    landing, bronze = _landing(tmp_path), tmp_path / "bronze"

    down = FakeEngine(fail=True)
    res = ingest(lambda: down, landing, bronze, workers=1, backoff=0)
    assert res.extracted == ["t1.pdf"] and sorted(res.failed) == ["s1.pdf", "s2.pdf"]
    # Coupe-circuit : 3 échecs consécutifs sur s1, puis s2 n'est même pas tenté.
    assert down.calls == 3
    errors = duckdb.execute(
        "SELECT file_name, error_type, attempts FROM read_parquet(?) ORDER BY file_name",
        [str(bronze / ERRORS / "*.parquet")],
    ).fetchall()
    assert errors == [("s1.pdf", "ConnectionError", 3), ("s2.pdf", "Skipped", 0)]

    up = FakeEngine()
    res = ingest(lambda: up, landing, bronze, workers=1, backoff=0)
    assert sorted(res.extracted) == ["s1.pdf", "s2.pdf"] and up.calls == 2
    assert _count(bronze, DOCUMENTS) == 3 and _count(bronze, ERRORS) == 2  # le journal d'erreurs est conservé
