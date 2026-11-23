"""Étape 7 : serveur MCP — donne à une IA un accès en lecture seule à l'entrepôt des factures.

Outils : list_invoices, invoice_totals, get_invoice, describe_schema, run_sql.

Principes :
- **Transparence** : chaque réponse contient `sql`, la liste des requêtes réellement exécutées avec
  leurs paramètres. L'utilisateur peut les rejouer et vérifier chaque chiffre.
- **Arguments non fiables** : ils viennent d'un LLM. Les filtres sont toujours passés en paramètres
  liés (`?`), jamais concaténés au SQL. Les noms de colonnes (tri, regroupement) viennent d'une liste
  blanche.
- **Lecture seule, en profondeur** pour le SQL libre :
  1. une seule instruction, de type SELECT (analyse par DuckDB lui-même, pas par regex) ;
  2. connexion neuve et jetable à chaque appel : un éventuel effet de bord meurt avec elle ;
  3. bac à sable DuckDB : accès fichiers limité aux dossiers bronze/silver, pas d'extension, pas
     d'ATTACH, configuration verrouillée (`lock_configuration`) ;
  4. plafond de lignes et délai maximal d'exécution.
- **Erreurs exploitables** : une erreur renvoie un message clair *et* un indice (colonnes
  disponibles, valeurs permises…) pour que le LLM corrige son appel au lieu d'abandonner.
"""

import logging
import sys
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from factures import config
from factures.warehouse import VIEWS, connect

log = logging.getLogger("factures.mcp")

STATUSES = ["Payée", "En attente", "En retard"]
CATEGORIES = ["Conseil", "Fournitures", "Informatique", "Maintenance"]
QUALITY = ["valide", "signalee"]
ORDERABLE = ["issue_date", "due_date", "total_ttc", "total_ht", "invoice_number", "supplier_name", "client_name"]
GROUPABLE = {
    "status": "status", "category": "category", "supplier": "supplier_name", "client": "client_name",
    "quality_status": "quality_status", "payment_method": "payment_method",
    "year": "year(issue_date)", "month": "strftime(issue_date, '%Y-%m')",
}
LIST_COLUMNS = ["invoice_number", "issue_date", "due_date", "supplier_name", "client_name", "category", "status",
                "total_ht", "total_tva", "total_ttc", "quality_status"]
MAX_SQL_ROWS = 500
SQL_TIMEOUT_S = 10.0

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

server = MCPServer(
    name="factures",
    instructions=(
        "Accès en lecture seule aux factures fournisseurs de l'entreprise (couche silver, montants en euros). "
        "Préférez list_invoices / invoice_totals / get_invoice ; utilisez describe_schema puis run_sql seulement "
        "pour une question que ces outils ne couvrent pas. Chaque réponse contient le SQL exécuté : citez les "
        "chiffres tels que renvoyés, sans les recalculer ni les inventer. Les factures signalées "
        "(quality_status = 'signalee') ont une anomalie détectée : mentionnez-la si elle concerne la réponse."
    ),
)


# --------------------------------------------------------------------------- utilitaires

def _db() -> duckdb.DuckDBPyConnection:
    """Connexion neuve, en mémoire, bac à sable verrouillé."""
    con = connect(config.DATA_DIR)
    data = config.DATA_DIR.resolve()
    dirs = ", ".join(f"'{(data / d).as_posix()}/'" for d in ("bronze", "silver"))
    con.execute(f"SET allowed_directories = [{dirs}]")
    con.execute("SET enable_external_access = false")
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    con.execute("SET lock_configuration = true")
    return con


def _json(v: Any) -> Any:
    """Valeurs SQL → JSON. Les montants restent des chaînes décimales exactes (pas de flottant)."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return [_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    return v


def _run(con, executed: list, sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]:
    params = params or []
    executed.append({"query": " ".join(sql.split()), "params": [_json(p) for p in params]})
    log.info("SQL %s %s", " ".join(sql.split()), params)
    try:
        cur = con.execute(sql, params)
    except duckdb.Error as exc:
        raise ToolError(f"Erreur SQL : {exc}") from exc
    return [d[0] for d in cur.description], cur.fetchall()


def _rows(cols: list[str], rows: list[tuple]) -> list[dict]:
    return [{c: _json(v) for c, v in zip(cols, r)} for r in rows]


def _parse_date(name: str, value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"{name} = {value!r} n'est pas une date valide. Format attendu : AAAA-MM-JJ (ex. 2025-03-31).") from exc


def _check_choice(name: str, value: str | None, allowed: list[str]) -> None:
    if value is not None and value not in allowed:
        raise ToolError(f"{name} = {value!r} n'existe pas. Valeurs possibles : {', '.join(allowed)}.")


def _where(supplier, client, status, category, quality_status, year, date_from, date_to) -> tuple[str, list]:
    """Clause WHERE paramétrée : les valeurs ne sont jamais insérées dans le texte SQL."""
    _check_choice("status", status, STATUSES)
    _check_choice("category", category, CATEGORIES)
    _check_choice("quality_status", quality_status, QUALITY)
    d_from, d_to = _parse_date("date_from", date_from), _parse_date("date_to", date_to)
    conds, params = [], []
    if supplier:
        conds.append("supplier_name ILIKE '%' || ? || '%'")
        params.append(supplier)
    if client:
        conds.append("client_name ILIKE '%' || ? || '%'")
        params.append(client)
    for col, val in (("status", status), ("category", category), ("quality_status", quality_status)):
        if val:
            conds.append(f"{col} = ?")
            params.append(val)
    if year is not None:
        conds.append("year(issue_date) = ?")
        params.append(year)
    if d_from:
        conds.append("issue_date >= ?")
        params.append(d_from)
    if d_to:
        conds.append("issue_date <= ?")
        params.append(d_to)
    return ("WHERE " + " AND ".join(conds)) if conds else "", params


# Annotations partagées par list_invoices et invoice_totals
Supplier = Annotated[str | None, Field(description="Fournisseur (émetteur), recherche partielle insensible à la casse, ex. 'aubry'")]
Client = Annotated[str | None, Field(description="Client facturé, recherche partielle insensible à la casse, ex. 'mace'")]
Status = Annotated[str | None, Field(description="Statut de paiement exact : 'Payée', 'En attente' ou 'En retard'")]
Category = Annotated[str | None, Field(description="Catégorie exacte : 'Conseil', 'Fournitures', 'Informatique' ou 'Maintenance'")]
Quality = Annotated[str | None, Field(description="'valide' ou 'signalee' (anomalie détectée par les contrôles qualité)")]
Year = Annotated[int | None, Field(description="Année d'émission, ex. 2025")]
DateFrom = Annotated[str | None, Field(description="Émises à partir de cette date incluse, format AAAA-MM-JJ")]
DateTo = Annotated[str | None, Field(description="Émises jusqu'à cette date incluse, format AAAA-MM-JJ")]


# --------------------------------------------------------------------------- outils

@server.tool(annotations=READ_ONLY)
def list_invoices(
    supplier: Supplier = None, client: Client = None, status: Status = None, category: Category = None,
    quality_status: Quality = None, year: Year = None, date_from: DateFrom = None, date_to: DateTo = None,
    order_by: Annotated[Literal["issue_date", "due_date", "total_ttc", "total_ht", "invoice_number", "supplier_name",
                                "client_name"], Field(description="Colonne de tri")] = "issue_date",
    descending: Annotated[bool, Field(description="Tri décroissant")] = True,
    limit: Annotated[int, Field(ge=1, le=200, description="Nombre maximal de factures renvoyées")] = 20,
    offset: Annotated[int, Field(ge=0, description="Pagination : factures à sauter")] = 0,
) -> dict:
    """Liste des factures (une ligne par facture) filtrées par fournisseur, client, statut, catégorie, qualité ou période.

    À utiliser pour « quelles factures… », « montre-moi les factures de… », « la plus grosse facture… ».
    Pour un nombre ou une somme, utilisez plutôt invoice_totals (pas de limite de lignes).
    Renvoie aussi `total_matching`, le nombre total de factures correspondant aux filtres.
    """
    where, params = _where(supplier, client, status, category, quality_status, year, date_from, date_to)
    con, executed = _db(), []
    _, ((total,),) = _run(con, executed, f"SELECT count(*) FROM silver.invoices {where}", params)
    order = f"{order_by} {'DESC' if descending else 'ASC'}, invoice_number"  # order_by validé par Literal
    cols, rows = _run(con, executed,
                      f"SELECT {', '.join(LIST_COLUMNS)} FROM silver.invoices {where} ORDER BY {order} LIMIT ? OFFSET ?",
                      params + [limit, offset])
    return {"total_matching": total, "returned": len(rows), "invoices": _rows(cols, rows), "sql": executed}


@server.tool(annotations=READ_ONLY)
def invoice_totals(
    supplier: Supplier = None, client: Client = None, status: Status = None, category: Category = None,
    quality_status: Quality = None, year: Year = None, date_from: DateFrom = None, date_to: DateTo = None,
    group_by: Annotated[Literal["status", "category", "supplier", "client", "quality_status", "payment_method",
                                "year", "month"] | None,
                        Field(description="Regrouper les totaux par cette dimension (optionnel)")] = None,
) -> dict:
    """Nombre de factures et sommes des montants HT, TVA et TTC (en euros), avec les mêmes filtres que list_invoices.

    À utiliser pour toute question de comptage ou de montant : « combien de factures… »,
    « quel est le montant TTC des factures en retard en 2025 ? », « total par fournisseur ».
    Les montants renvoyés sont exacts (calculés par la base) : citez-les tels quels.
    """
    where, params = _where(supplier, client, status, category, quality_status, year, date_from, date_to)
    dim = GROUPABLE[group_by] if group_by else None
    select = f"{dim} AS {group_by}, " if dim else ""
    sql = (f"SELECT {select}count(*) AS invoice_count, sum(total_ht) AS total_ht, sum(total_tva) AS total_tva, "
           f"sum(total_ttc) AS total_ttc FROM silver.invoices {where}"
           + (f" GROUP BY {dim} ORDER BY {dim}" if dim else ""))
    con, executed = _db(), []
    cols, rows = _run(con, executed, sql, params)
    return {"currency": "EUR", "rows": _rows(cols, rows), "sql": executed}


@server.tool(annotations=READ_ONLY)
def get_invoice(
    invoice_number: Annotated[str, Field(description="Numéro de facture, ex. 'A-2025-0001'")],
) -> dict:
    """Détail complet d'une facture (en-tête, fournisseur, client, montants, contrôles qualité) et toutes ses lignes."""
    con, executed = _db(), []
    cols, rows = _run(con, executed, "SELECT * EXCLUDE (built_at) FROM silver.invoices WHERE invoice_number = ?",
                      [invoice_number.strip()])
    if not rows:
        _, near = _run(con, executed,
                       "SELECT invoice_number FROM silver.invoices ORDER BY jaro_winkler_similarity(invoice_number, ?) "
                       "DESC LIMIT 5", [invoice_number.strip()])
        _, quarantined = _run(con, executed, "SELECT reason_details FROM silver.quarantine WHERE invoice_number = ?",
                              [invoice_number.strip()])
        if quarantined:
            raise ToolError(f"La facture {invoice_number} est en quarantaine (rejetée) : {quarantined[0][0]}")
        raise ToolError(f"Aucune facture {invoice_number!r}. Numéros les plus proches : {', '.join(r[0] for r in near)}.")
    invoice = _rows(cols, rows)[0]
    lcols, lrows = _run(con, executed,
                        "SELECT line_no, description, quantity, unit_price_ht, vat_rate, line_total_ht "
                        "FROM silver.invoice_lines WHERE invoice_id = ? ORDER BY line_no", [invoice["invoice_id"]])
    return {"invoice": invoice, "lines": _rows(lcols, lrows), "sql": executed}


@server.tool(annotations=READ_ONLY)
def describe_schema() -> dict:
    """Schéma de l'entrepôt : vues interrogeables, colonnes, types, descriptions et valeurs possibles.

    À appeler avant d'écrire une requête pour run_sql.
    """
    con, executed = _db(), []
    _, views = _run(con, executed,
                    "SELECT schema_name || '.' || view_name, comment FROM duckdb_views() WHERE NOT internal ORDER BY 1")
    _, columns = _run(con, executed,
                      "SELECT schema_name || '.' || table_name, column_name, data_type, comment FROM duckdb_columns() "
                      "WHERE schema_name IN ('bronze', 'silver') ORDER BY 1, column_index")
    by_view: dict[str, list] = {}
    for view, col, typ, comment in columns:
        by_view.setdefault(view, []).append({"column": col, "type": typ, **({"description": comment} if comment else {})})
    return {
        "views": [{"name": v, "description": c, "columns": by_view.get(v, [])} for v, c in views],
        "values": {"status": STATUSES, "category": CATEGORIES, "quality_status": QUALITY},
        "notes": [
            "Montants en euros, type DECIMAL(14,2).",
            "Jointure lignes ↔ factures : silver.invoice_lines.invoice_id = silver.invoices.invoice_id.",
            "silver.invoices ne contient pas les documents en quarantaine (silver.quarantine).",
            "run_sql n'accepte qu'une requête SELECT.",
        ],
        "sql": executed,
    }


@server.tool(annotations=READ_ONLY)
def run_sql(
    query: Annotated[str, Field(description="Une seule requête SELECT (DuckDB) sur les vues bronze.* / silver.*")],
    max_rows: Annotated[int, Field(ge=1, le=MAX_SQL_ROWS, description="Nombre maximal de lignes renvoyées")] = 100,
) -> dict:
    """Exécute une requête SQL libre, en LECTURE SEULE, pour les questions que les autres outils ne couvrent pas.

    Une seule instruction SELECT (WITH … SELECT accepté). Toute écriture (INSERT, UPDATE, DELETE, CREATE,
    DROP, COPY, ATTACH, SET…) est refusée. Appelez describe_schema d'abord pour connaître les colonnes.
    """
    con = _db()
    try:
        statements = con.extract_statements(query)
    except duckdb.Error as exc:
        raise ToolError(f"Requête invalide : {exc}. Astuce : appelez describe_schema pour les noms exacts.") from exc
    if len(statements) != 1:
        raise ToolError(f"Une seule instruction est autorisée ({len(statements)} reçues).")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise ToolError(f"Refusé : seule une requête SELECT est autorisée (reçu : {statements[0].type.name}). "
                        "Ce serveur est en lecture seule.")

    executed = [{"query": " ".join(query.split()), "params": []}]
    log.info("SQL libre %s", " ".join(query.split()))
    timer = threading.Timer(SQL_TIMEOUT_S, con.interrupt)  # délai maximal d'exécution
    timer.start()
    try:
        cur = con.execute(query)
        rows = cur.fetchmany(max_rows + 1)
    except duckdb.InterruptException as exc:
        raise ToolError(f"Requête interrompue après {SQL_TIMEOUT_S:.0f} s : simplifiez-la ou filtrez davantage.") from exc
    except duckdb.PermissionException as exc:
        raise ToolError(f"Refusé par le bac à sable (lecture seule, fichiers hors entrepôt interdits) : {exc}") from exc
    except duckdb.Error as exc:
        hint = ""
        if isinstance(exc, (duckdb.CatalogException, duckdb.BinderException)):
            hint = (" Vues disponibles : " + ", ".join(VIEWS) +
                    ". Appelez describe_schema pour les colonnes exactes.")
        raise ToolError(f"Erreur SQL : {exc}.{hint}") from exc
    finally:
        timer.cancel()
    cols = [d[0] for d in cur.description]
    return {
        "columns": cols,
        "rows": _rows(cols, rows[:max_rows]),
        "truncated": len(rows) > max_rows,
        "sql": executed,
    }


def main() -> None:
    # Protocole stdio : stdout est réservé aux messages MCP, les journaux vont sur stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    server.run("stdio")


if __name__ == "__main__":
    main()
