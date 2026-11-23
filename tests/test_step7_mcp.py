"""Tests de l'étape 7 : le serveur MCP, appelé par un vrai client MCP sur stdio (sous-processus).

Le serveur tourne sur un jeu de données de test (DATA_DIR temporaire) : chaque outil est appelé et
ses résultats sont vérifiés contre des valeurs connues, puis on tente de modifier les données par
tous les moyens via l'outil SQL libre.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from factures.silver import build
from test_step4 import _bronze, native, ocr

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mcp")
    data = tmp / "data"
    bronze = _bronze(tmp, [native("A-1"), ocr("A-2", ttc="99 999,99 €"), native("B-7").replace("Payée", "En retard")])
    shutil.move(str(bronze), data / "bronze")
    build(data / "bronze", data / "silver")
    return data


def call_all(data_dir: Path, calls: list[tuple[str, dict]]) -> tuple[list[str], list]:
    """Lance le serveur (`python -m factures.mcp_server`) en stdio et enchaîne les appels."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "factures.mcp_server"],
        env={**os.environ, "DATA_DIR": str(data_dir)},
    )

    async def run():
        async with Client(params) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            results = []
            for name, args in calls:
                r = await c.call_tool(name, args)
                text = r.content[0].text if r.content else ""
                results.append((r.is_error, json.loads(text) if not r.is_error else text))
            return names, results

    return asyncio.run(run())


def test_every_tool(data_dir):
    names, res = call_all(data_dir, [
        ("list_invoices", {"order_by": "invoice_number", "descending": False}),
        ("list_invoices", {"status": "En retard"}),
        ("invoice_totals", {}),
        ("invoice_totals", {"group_by": "status"}),
        ("invoice_totals", {"group_by": "supplier_name"}),   # nom de colonne accepté comme synonyme
        ("get_invoice", {"invoice_number": "A-2"}),
        ("describe_schema", {}),
        ("run_sql", {"query": "SELECT count(*) AS n FROM silver.invoice_lines"}),
    ])
    assert set(names) == {"list_invoices", "invoice_totals", "get_invoice", "monthly_spend", "supplier_balance",
                          "describe_schema", "run_sql"}
    assert all(not err for err, _ in res)
    listed, late, totals, by_status, by_supplier, detail, schema, sql = (r for _, r in res)
    assert by_supplier["rows"] == [{"supplier": "Aubry", "invoice_count": 3, "total_ht": "3601.50",
                                    "total_tva": "720.30", "total_ttc": "102881.19"}]

    assert [i["invoice_number"] for i in listed["invoices"]] == ["A-1", "A-2", "B-7"]
    assert late["total_matching"] == 1 and late["invoices"][0]["invoice_number"] == "B-7"
    assert totals["rows"] == [{"invoice_count": 3, "total_ht": "3601.50", "total_tva": "720.30", "total_ttc": "102881.19"}]
    assert {r["status"]: r["invoice_count"] for r in by_status["rows"]} == {"Payée": 2, "En retard": 1}
    assert detail["invoice"]["quality_status"] == "signalee" and detail["invoice"]["quality_flags"] == ["TTC_INCOHERENT"]
    assert [ln["description"] for ln in detail["lines"]] == ["Formation DuckDB", "Audit"]
    assert "silver.invoices" in {v["name"] for v in schema["views"]}
    assert sql["rows"] == [{"n": 6}]

    # Transparence : chaque réponse porte le SQL réellement exécuté, valeurs en paramètres liés.
    for _, r in res:
        assert r["sql"] and all("query" in q and "params" in q for q in r["sql"])
    assert late["sql"][0]["params"] == ["En retard"] and "En retard" not in late["sql"][0]["query"]


ATTACKS = [
    "DROP VIEW silver.invoices",
    "DELETE FROM silver.invoices",
    "CREATE TABLE x AS SELECT 1",
    "COPY (SELECT 1) TO '{silver}/pwn.parquet'",
    "SELECT 1; DROP VIEW silver.invoices",
    "ATTACH '{data}/evil.duckdb'",
    "SET enable_external_access = true",
    "INSTALL httpfs",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('{data}/../.env')",
    "PRAGMA show_tables",
    "CALL pragma_version()",
]


def test_free_sql_cannot_modify_or_escape(data_dir):
    before = sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*"))
    attacks = [a.format(silver=data_dir / "silver", data=data_dir) for a in ATTACKS]
    _, res = call_all(data_dir, [("run_sql", {"query": a}) for a in attacks]
                      + [("list_invoices", {"supplier": "x' OR '1'='1"}),
                         ("invoice_totals", {})])
    for attack, (is_error, msg) in zip(attacks, res[:len(attacks)]):
        assert is_error, f"aurait dû être refusé : {attack}"
    # Injection dans un filtre : traitée comme une simple valeur → aucune facture, pas d'erreur.
    assert res[-2] == (False, res[-2][1]) and res[-2][1]["total_matching"] == 0
    # Les données sont intactes, aucun fichier créé.
    assert res[-1][1]["rows"][0]["invoice_count"] == 3
    assert sorted(p.relative_to(data_dir).as_posix() for p in data_dir.rglob("*")) == before


def test_errors_help_the_llm_correct_itself(data_dir):
    _, res = call_all(data_dir, [
        ("invoice_totals", {"status": "retard"}),
        ("list_invoices", {"date_from": "31/12/2025"}),
        ("get_invoice", {"invoice_number": "A-3"}),
        ("run_sql", {"query": "SELECT montant FROM silver.invoices"}),
    ])
    assert all(err for err, _ in res)
    status, date_, missing, column = (m for _, m in res)
    assert "En retard" in status          # valeurs permises
    assert "AAAA-MM-JJ" in date_         # format attendu
    assert "A-1" in missing or "A-2" in missing  # numéros proches
    assert "describe_schema" in column and "total_ttc" in column  # colonnes candidates
