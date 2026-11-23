"""Tests de la couche gold (bonus) : indicateurs justes, cohérents avec la silver, exposés par le MCP."""

import shutil
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from factures.gold import build as build_gold
from factures.silver import build as build_silver
from test_step4 import _bronze, native, ocr
from test_step7_mcp import call_all

AS_OF = date(2026, 1, 1)


@pytest.fixture
def data_dir(tmp_path):
    data = tmp_path / "data"
    bronze = _bronze(tmp_path, [
        native("A-1"),                                        # Payée, 1 440,60 €
        ocr("A-2", ttc="99 999,99 €"),                        # signalée : exclue des montants
        native("B-7").replace("Payée", "En retard"),          # échue
        native("C-1").replace("Payée", "En attente"),         # « En attente » mais échéance dépassée
    ])
    shutil.move(str(bronze), data / "bronze")
    build_silver(data / "bronze", data / "silver")
    build_gold(data, as_of=AS_OF)
    return data


def rows(data, table, sql="SELECT * FROM t"):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{data / 'gold' / table / 'data.parquet'}')")
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def test_monthly_spend_excludes_flagged_but_reports_them(data_dir):
    (m,) = rows(data_dir, "monthly_spend")
    assert m["month"] == "2025-01" and m["invoice_count"] == 3
    assert m["total_ttc"] == Decimal("4321.80")                 # 3 × 1 440,60
    assert (m["paid_ttc"], m["unpaid_ttc"]) == (Decimal("1440.60"), Decimal("2881.20"))
    assert (m["flagged_count"], m["flagged_ttc"]) == (1, Decimal("99999.99"))
    assert m["as_of"] == AS_OF


def test_supplier_balance_uses_due_dates_not_only_status(data_dir):
    (s,) = rows(data_dir, "supplier_balance")
    assert s["supplier_name"] == "Aubry" and s["invoiced_ttc"] == Decimal("4321.80")
    assert s["outstanding_ttc"] == Decimal("2881.20")           # En retard + En attente
    assert s["overdue_ttc"] == Decimal("2881.20")               # les deux sont échues au 01/01/2026
    assert s["status_outdated"] == 1                             # « En attente » à mettre à jour
    assert s["avg_payment_terms_days"] == 60


def test_gold_is_consistent_with_silver(data_dir):
    silver_ttc = duckdb.execute(
        f"SELECT sum(total_ttc) FROM read_parquet('{data_dir / 'silver' / 'invoices' / 'data.parquet'}')").fetchone()[0]
    (m,) = rows(data_dir, "monthly_spend")
    assert m["total_ttc"] + m["flagged_ttc"] == silver_ttc
    aging = rows(data_dir, "aging")
    assert [(a["bucket"], a["amount_ttc"]) for a in aging] == [("4. > 90 j", Decimal("2881.20"))]
    assert sum(a["amount_ttc"] for a in aging) == rows(data_dir, "supplier_balance")[0]["outstanding_ttc"]


def test_gold_mcp_tools(data_dir):
    _, res = call_all(data_dir, [("supplier_balance", {"supplier": "aub"}), ("monthly_spend", {"year": 2025})])
    (err1, balance), (err2, spend) = res
    assert not err1 and not err2
    assert balance["rows"][0]["outstanding_ttc"] == "2881.20" and balance["aging"][0]["bucket"] == "4. > 90 j"
    assert balance["sql"][-1]["params"] == ["aub"]               # transparence + paramètres liés
    assert spend["rows"][0]["flagged_count"] == 1


def test_gold_tools_explain_when_gold_is_missing(data_dir):
    shutil.rmtree(data_dir / "gold")
    _, ((is_error, msg),) = call_all(data_dir, [("monthly_spend", {})])
    assert is_error and "factures gold" in msg
