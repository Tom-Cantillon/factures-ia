"""Tests de l'étape 6 : entrepôt = vues DuckDB sur Parquet, sans copie ni verrou bloquant."""

import shutil
from decimal import Decimal

import duckdb

from factures.silver import build
from factures.warehouse import build_file, connect
from test_step4 import _bronze, native, ocr


def _data_dir(tmp_path):
    data = tmp_path / "data"
    bronze = _bronze(tmp_path, [native("A-1"), ocr("A-2", ttc="99 999,99 €")])
    shutil.move(str(bronze), data / "bronze")
    build(data / "bronze", data / "silver")
    return data


def test_connect_exposes_silver_in_sql(tmp_path):
    con = connect(_data_dir(tmp_path))
    rows = con.execute("SELECT invoice_number, total_ttc FROM silver.invoices ORDER BY 1").fetchall()
    assert rows == [("A-1", Decimal("1440.60")), ("A-2", Decimal("99999.99"))]
    n_lines = con.execute("SELECT count(*) FROM silver.invoice_lines l JOIN silver.invoices i USING (invoice_id)").fetchone()
    assert n_lines == (4,)
    # Table pas encore produite (aucune erreur d'extraction) : pas de vue, pas de plantage.
    assert "extraction_errors" not in {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}


def test_warehouse_file_holds_views_only(tmp_path):
    data = _data_dir(tmp_path)
    build_file(data / "warehouse.duckdb", data)
    with duckdb.connect(str(data / "warehouse.duckdb"), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM duckdb_tables() WHERE NOT internal").fetchone() == (0,)
        views = {r[0] for r in con.execute("SELECT schema_name || '.' || view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
        assert {"silver.invoices", "silver.invoice_lines", "silver.quarantine", "bronze.documents"} <= views
        assert con.execute("SELECT comment FROM duckdb_views() WHERE view_name = 'invoices'").fetchone()[0]
        assert con.execute("SELECT count(*) FROM silver.invoices").fetchone() == (2,)


def test_locked_file_does_not_block_programs(tmp_path):
    data = _data_dir(tmp_path)
    build_file(data / "warehouse.duckdb", data)
    with duckdb.connect(str(data / "warehouse.duckdb")):  # un outil graphique garde le fichier ouvert
        assert connect(data).execute("SELECT count(*) FROM silver.invoices").fetchone() == (2,)
