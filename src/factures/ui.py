"""Interface web locale (Streamlit) : `uv run factures ui` puis http://localhost:8501.

- 💬 Assistant : l'agent de l'étape 8 (même code, même serveur MCP), avec pour chaque réponse le détail
  des outils appelés, du SQL exécuté et des résultats. Choix du LLM dans la barre latérale.
- 📄 Factures : indicateurs, filtres, liste des factures et détail des lignes (lecture seule de l'entrepôt).
- 🩺 Qualité : factures signalées, quarantaine, erreurs d'extraction, répartition texte / OCR.
"""

import asyncio
from decimal import Decimal

import pandas as pd
import streamlit as st
from mcp import Client

from factures.agent import Agent, Display, load_profile, load_profiles, mcp_server_params
from factures.warehouse import connect

st.set_page_config(page_title="Factures IA", page_icon="🧾", layout="wide")


# --------------------------------------------------------------------------- données (lecture seule)

@st.cache_data(ttl=30, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Une connexion DuckDB en mémoire par requête : aucun verrou, lecture des Parquet à jour."""
    cur = connect().execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def has_view(name: str) -> bool:
    schema, view = name.split(".")
    return bool(len(query("SELECT 1 FROM duckdb_views() WHERE schema_name = ? AND view_name = ?", (schema, view))))


def eur(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{Decimal(str(v)):,.2f} €".replace(",", " ").replace(".", ",")


# --------------------------------------------------------------------------- assistant

class TraceDisplay(Display):
    """Au lieu d'écrire dans le terminal, l'agent enregistre ses étapes pour les afficher dans la page."""

    def __init__(self):
        super().__init__(quiet=True)
        self.steps: list[dict] = []

    def tool_call(self, step, name, args):
        self.steps.append({"step": step, "tool": name, "args": args, "result": None, "error": None})

    def tool_result(self, result, is_error):
        if self.steps:
            self.steps[-1]["error" if is_error else "result"] = result


async def _ask(profile_name: str, history: list[dict], question: str):
    display = TraceDisplay()
    async with Client(mcp_server_params()) as client:
        agent = Agent(client, load_profile(profile_name), display)
        await agent.load_tools()
        if history:
            agent.messages = history
        turn = await agent.ask(question)
        return turn, agent.messages, display.steps


def render_trace(steps: list[dict]) -> None:
    for s in steps:
        args = ", ".join(f"{k}={v!r}" for k, v in s["args"].items())
        st.markdown(f"**🔧 {s['step']}. `{s['tool']}`**({args})")
        if s["error"]:
            st.error(str(s["error"])[:600], icon="↩️")
            continue
        res = s["result"] or {}
        for q in res.get("sql", []):
            st.code(q["query"] + (f"\n-- paramètres : {q['params']}" if q.get("params") else ""), language="sql")
        rows = res.get("rows") or res.get("invoices") or res.get("lines")
        if isinstance(rows, list) and rows:
            st.dataframe(pd.DataFrame(rows).head(20), hide_index=True, width="stretch")
        elif "invoice" in res:
            st.json(res["invoice"], expanded=False)


def page_assistant(profile_name: str) -> None:
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("history", [])
    if not st.session_state.chat:
        st.info("Exemples : « Quel est le montant TTC des factures en retard en 2025 ? » · "
                "« Quel fournisseur a le plus gros montant cumulé ? » · « Détaille la facture A-2025-0010 ».")
    last = len(st.session_state.chat) - 1
    for i, m in enumerate(st.session_state.chat):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("steps"):
                with st.expander(f"Ce qu'a fait l'agent — {len(m['steps'])} appel(s) d'outil · {m['meta']}",
                                 expanded=(i == last)):
                    render_trace(m["steps"])

    # La question en attente est traitée ici, sous l'historique, puis la page est redessinée :
    # la zone de saisie reste ainsi toujours en bas, comme dans une messagerie.
    if pending := st.session_state.pop("pending", None):
        with st.chat_message("user"):
            st.markdown(pending)
        with st.chat_message("assistant"), st.spinner(f"L'agent réfléchit ({profile_name})…"):
            turn, history, steps = asyncio.run(_ask(profile_name, st.session_state.history, pending))
        st.session_state.history = history
        st.session_state.chat += [
            {"role": "user", "content": pending},
            {"role": "assistant", "content": turn.answer, "steps": steps,
             "meta": f"{profile_name} · {turn.seconds:.1f} s"},
        ]
        st.rerun()

    if question := st.chat_input("Posez une question sur les factures…"):
        st.session_state.pending = question
        st.rerun()


# --------------------------------------------------------------------------- factures

def page_invoices() -> None:
    if not has_view("silver.invoices"):
        st.warning("Aucune donnée : lancez `uv run factures run`.")
        return
    k = query("SELECT count(*) n, sum(total_ttc) ttc, count(*) FILTER (status = 'En retard') late, "
              "sum(total_ttc) FILTER (status = 'En retard') late_ttc, count(*) FILTER (quality_status = 'signalee') flagged "
              "FROM silver.invoices").iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Factures", int(k.n))
    c2.metric("TTC total", f"{float(k.ttc) / 1000:,.0f} k€".replace(",", " "), help=eur(k.ttc))
    c3.metric("En retard", int(k.late), f"{float(k.late_ttc or 0) / 1000:,.0f} k€ TTC".replace(",", " "),
              delta_color="off", help=eur(k.late_ttc))
    c4.metric("Signalées (anomalie)", int(k.flagged))

    f1, f2, f3, f4 = st.columns(4)
    suppliers = f1.multiselect("Fournisseur", query("SELECT DISTINCT supplier_name FROM silver.invoices ORDER BY 1").supplier_name)
    statuses = f2.multiselect("Statut", ["Payée", "En attente", "En retard"])
    categories = f3.multiselect("Catégorie", query("SELECT DISTINCT category FROM silver.invoices ORDER BY 1").category)
    years = f4.multiselect("Année", query("SELECT DISTINCT year(issue_date) y FROM silver.invoices ORDER BY 1").y)

    conds, params = [], []
    for col, values in (("supplier_name", suppliers), ("status", statuses), ("category", categories),
                        ("year(issue_date)", years)):
        if values:
            conds.append(f"{col} IN ({', '.join('?' * len(values))})")
            params += list(values)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    df = query(f"SELECT invoice_number, issue_date, due_date, supplier_name, client_name, category, status, "
               f"total_ht, total_tva, total_ttc, quality_status, extraction_method FROM silver.invoices {where} "
               f"ORDER BY issue_date DESC", tuple(params))
    st.caption(f"{len(df)} facture(s) · total TTC {eur(df.total_ttc.sum() if len(df) else 0)}")
    st.dataframe(df, hide_index=True, width="stretch")

    left, right = st.columns([1, 2])
    by_month = query(f"SELECT strftime(issue_date, '%Y-%m') mois, sum(total_ttc)::DOUBLE ttc FROM silver.invoices "
                     f"{where} GROUP BY 1 ORDER BY 1", tuple(params))
    right.bar_chart(by_month, x="mois", y="ttc", y_label="TTC (€)", height=260)
    number = left.selectbox("Détail d'une facture", df.invoice_number if len(df) else [], index=None,
                            placeholder="Choisir un numéro…")
    if number:
        inv = query("SELECT * FROM silver.invoices WHERE invoice_number = ?", (number,)).iloc[0]
        left.markdown(f"**{inv.invoice_number}** — {inv.supplier_name} → {inv.client_name}  \n"
                      f"Émise le {inv.issue_date}, échéance {inv.due_date} · {inv.status}  \n"
                      f"HT {eur(inv.total_ht)} · TVA {eur(inv.total_tva)} · **TTC {eur(inv.total_ttc)}**")
        if inv.quality_status == "signalee":
            left.warning(" · ".join(inv.quality_details))
        left.dataframe(query("SELECT line_no, description, quantity, unit_price_ht, vat_rate, line_total_ht "
                             "FROM silver.invoice_lines WHERE invoice_id = ? ORDER BY line_no", (inv.invoice_id,)),
                       hide_index=True, width="stretch")


# --------------------------------------------------------------------------- qualité

def page_quality() -> None:
    if not has_view("silver.invoices"):
        st.warning("Aucune donnée : lancez `uv run factures run`.")
        return
    st.subheader("Factures signalées")
    st.caption("Gardées dans la silver mais marquées : une anomalie a été détectée, rien n'a été corrigé automatiquement.")
    st.dataframe(query("SELECT invoice_number, supplier_name, total_ht, total_tva, total_ttc, quality_flags, "
                       "quality_details, extraction_method, file_name FROM silver.invoices "
                       "WHERE quality_status = 'signalee'"), hide_index=True, width="stretch")

    st.subheader("Quarantaine (rejets)")
    st.caption("Documents écartés de la silver : champ obligatoire manquant ou illisible, ou doublon.")
    q = query("SELECT file_name, invoice_number, reason_codes, reason_details, duplicate_of FROM silver.quarantine")
    if len(q):
        st.dataframe(q, hide_index=True, width="stretch")
    else:
        st.success("Aucun document en quarantaine.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Extraction (bronze)")
        st.dataframe(query("SELECT extraction_method, count(*) documents, round(avg(ocr_seconds), 1) ocr_s_moyen "
                           "FROM bronze.documents GROUP BY 1 ORDER BY 1"), hide_index=True)
    with c2:
        st.subheader("Erreurs d'extraction")
        if has_view("bronze.extraction_errors"):
            st.dataframe(query("SELECT file_name, stage, error_type, attempts, failed_at, "
                               "doc_id IN (SELECT doc_id FROM bronze.documents) AS rattrape "
                               "FROM bronze.extraction_errors ORDER BY failed_at DESC"), hide_index=True)
        else:
            st.success("Aucune erreur d'extraction journalisée.")


# --------------------------------------------------------------------------- indicateurs (gold)

def page_gold() -> None:
    if not has_view("gold.supplier_balance"):
        st.warning("Couche gold absente : lancez `uv run factures gold`.")
        return
    k = query("SELECT sum(outstanding_ttc) enc, sum(overdue_ttc) echu, sum(status_outdated) outdated, "
              "sum(flagged_count) flagged, sum(flagged_ttc) flagged_ttc, max(as_of) as_of FROM gold.supplier_balance").iloc[0]
    st.caption(f"Factures fournisseurs · arrêté au {k.as_of} · factures signalées exclues des montants")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Encours (reste à payer)", f"{float(k.enc) / 1000:,.0f} k€".replace(",", " "), help=eur(k.enc))
    c2.metric("Dont échu", f"{float(k.echu) / 1000:,.0f} k€".replace(",", " "), help=eur(k.echu))
    c3.metric("Statuts à mettre à jour", int(k.outdated), help="Factures « En attente » dont l'échéance est dépassée")
    c4.metric("Signalées, exclues", int(k.flagged), help=eur(k.flagged_ttc))

    st.subheader("Dépense mensuelle (TTC)")
    m = query("SELECT month AS mois, paid_ttc::DOUBLE AS \"payé\", unpaid_ttc::DOUBLE AS \"à payer\" "
              "FROM gold.monthly_spend ORDER BY month")
    st.bar_chart(m, x="mois", y=["payé", "à payer"], y_label="€ TTC", height=280, stack=True)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Encours par fournisseur")
        st.dataframe(query("SELECT supplier_name AS fournisseur, invoice_count AS factures, invoiced_ttc AS facture_ttc, "
                           "paid_ttc AS paye_ttc, outstanding_ttc AS encours_ttc, overdue_ttc AS echu_ttc, "
                           "avg_payment_terms_days AS delai_moyen_j, status_outdated AS statuts_a_revoir "
                           "FROM gold.supplier_balance ORDER BY encours_ttc DESC"), hide_index=True, width="stretch")
    with right:
        st.subheader("Balance âgée")
        a = query("PIVOT (SELECT supplier_name AS fournisseur, bucket, amount_ttc FROM gold.aging) "
                  "ON bucket USING sum(amount_ttc) ORDER BY fournisseur")
        st.dataframe(a.astype(object).where(a.notna(), "—"), hide_index=True, width="stretch")


# --------------------------------------------------------------------------- mise en page

default, profiles = load_profiles()
with st.sidebar:
    st.title("🧾 Factures IA")
    st.caption("S3 → OCR → bronze → silver → entrepôt → MCP → agent")
    names = list(profiles)
    profile = st.selectbox("LLM de l'assistant", names, index=names.index(default) if default in names else 0,
                           format_func=lambda n: f"{n} — {profiles[n].get('model')}")
    st.caption(profiles[profile].get("description", ""))
    if st.button("Nouvelle conversation", width="stretch"):
        st.session_state.chat, st.session_state.history = [], []
        st.rerun()
    st.divider()
    st.caption("Lecture seule : l'assistant passe par le serveur MCP, les pages par des vues DuckDB.")

tab_chat, tab_inv, tab_gold, tab_q = st.tabs(["💬 Assistant", "📄 Factures", "📈 Indicateurs", "🩺 Qualité"])
with tab_chat:
    page_assistant(profile)
with tab_inv:
    page_invoices()
with tab_gold:
    page_gold()
with tab_q:
    page_quality()
