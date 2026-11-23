"""Étape 8 : les mêmes questions posées à plusieurs LLM, chiffres vérifiés par SQL.

Pour chaque question, la « bonne réponse » est calculée **indépendamment de l'agent** : requête SQL
directe sur l'entrepôt (warehouse.connect), sans passer par le serveur MCP ni par un LLM. Une
réponse est jugée exacte si tous les éléments attendus (montants, comptes, numéros, noms) y figurent.
Les montants sont comparés après normalisation (106 886,43 € = 106886.43).

Les questions sont posées en conversation, dans l'ordre : certaines dépendent de la précédente
(« Et parmi elles… »), ce qui teste aussi la mémoire de l'agent.
"""

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from mcp import Client

from factures import config
from factures.agent import Agent, Display, load_profile, load_profiles, mcp_server_params
from factures.warehouse import connect


@dataclass
class Question:
    text: str
    expected_sql: str          # renvoie UNE ligne : chaque colonne est un élément attendu dans la réponse
    new_conversation: bool = False


QUESTIONS = [
    Question("Quel est le montant TTC des factures en retard en 2025 ?",
             "SELECT sum(total_ttc) FROM silver.invoices WHERE status = 'En retard' AND year(issue_date) = 2025",
             new_conversation=True),
    Question("Combien de factures le fournisseur Aubry nous a-t-il envoyées ?",
             "SELECT count(*) FROM silver.invoices WHERE supplier_name = 'Aubry'", new_conversation=True),
    Question("Et parmi elles, combien sont déjà payées ?",
             "SELECT count(*) FROM silver.invoices WHERE supplier_name = 'Aubry' AND status = 'Payée'"),
    Question("Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?",
             "SELECT sum(total_ht) FROM silver.invoices WHERE category = 'Informatique' AND year(issue_date) = 2026",
             new_conversation=True),
    Question("Quel fournisseur a le plus gros montant TTC cumulé, et combien ?",
             "SELECT supplier_name, sum(total_ttc) s FROM silver.invoices GROUP BY 1 ORDER BY s DESC LIMIT 1",
             new_conversation=True),
    Question("Quels sont le client et le montant TTC de la facture A-2025-0010 ?",
             "SELECT client_name, total_ttc FROM silver.invoices WHERE invoice_number = 'A-2025-0010'",
             new_conversation=True),
    Question("Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.",
             "SELECT string_agg(invoice_number, ', ') FROM silver.invoices WHERE quality_status = 'signalee'",
             new_conversation=True),
    # Questions sans outil dédié : il faut découvrir le schéma et écrire du SQL (run_sql).
    Question("Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?",
             "SELECT description, sum(quantity)::INT q FROM silver.invoice_lines GROUP BY 1 ORDER BY q DESC LIMIT 1",
             new_conversation=True),
    Question("Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.",
             "SELECT round(avg(unit_price_ht), 2) FROM silver.invoice_lines WHERE description = 'Cartouche toner noir'",
             new_conversation=True),
]


def numbers_in(text: str) -> set[Decimal]:
    """Tous les nombres d'un texte en français ou en anglais : '106 886,43 €', '106886.43', '12'."""
    found = set()
    for m in re.finditer(r"\d[\d\s  .,]*\d|\d", text):
        s = re.sub(r"[\s  ]", "", m.group())
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            if len(s.split(",")[-1]) == 3:   # « 229,000 » : milliers ou décimales ? on garde les deux lectures
                for cand in (s.replace(",", ""), s.replace(",", ".")):
                    found.add(Decimal(cand).normalize())
                continue
            s = s.replace(",", ".")
        try:
            found.add(Decimal(s.strip(".")).normalize())
        except InvalidOperation:
            pass
    return found


def contains(answer: str, expected) -> bool:
    if isinstance(expected, (int, float, Decimal)):
        return Decimal(str(expected)).normalize() in numbers_in(answer)  # str() : pas d'artefact binaire du float
    return all(part.strip().lower() in answer.lower() for part in str(expected).split(","))


def expected_values(q: Question) -> list:
    return list(connect().execute(q.expected_sql).fetchone())


async def run_profile(name: str) -> list[dict]:
    profile = load_profile(name)
    display = Display(quiet=True)
    rows = []
    async with Client(mcp_server_params()) as client:
        agent = Agent(client, profile, display)
        await agent.load_tools()
        for q in QUESTIONS:
            if q.new_conversation:
                agent.reset()
            exp = expected_values(q)
            turn = await agent.ask(q.text)
            ok = [contains(turn.answer, e) for e in exp]
            rows.append({
                "profile": name, "question": q.text, "expected": exp, "answer": turn.answer, "exact": all(ok),
                "tools": [c.name + ("✗" if c.is_error else "") for c in turn.tool_calls],
                "seconds": turn.seconds, "stopped": turn.stopped,
            })
            print(f"  [{name}] {'✓' if all(ok) else '✗'} {turn.seconds:5.1f}s {','.join(rows[-1]['tools']) or '-':<40} {q.text[:60]}")
    return rows


def report(results: dict[str, list[dict]]) -> str:
    names = list(results)
    lines = ["# Agent : mêmes questions, plusieurs LLM", "",
             "Commande : `uv run factures agent-bench`. Chiffres attendus calculés par SQL direct sur l'entrepôt.", "",
             "| Question | Attendu (SQL) | " + " | ".join(names) + " |",
             "|---|---|" + "---|" * len(names)]
    for i, q in enumerate(QUESTIONS):
        exp = ", ".join(str(e) for e in results[names[0]][i]["expected"])
        cells = []
        for n in names:
            r = results[n][i]
            cells.append(f"{'✅' if r['exact'] else '❌'} {r['seconds']:.0f} s · {' → '.join(r['tools']) or 'aucun outil'}")
        lines.append(f"| {q.text} | {exp} | " + " | ".join(cells) + " |")
    lines.append("| **Score** | | " + " | ".join(
        f"**{sum(r['exact'] for r in results[n])}/{len(QUESTIONS)}** · {sum(r['seconds'] for r in results[n]):.0f} s"
        for n in names) + " |")
    lines += ["", "✗ après un nom d'outil = appel en erreur (le LLM a dû se corriger).", "", "## Réponses complètes", ""]
    for n in names:
        lines.append(f"### {n}")
        for r in results[n]:
            lines += [f"**{r['question']}** — {'exacte' if r['exact'] else 'INEXACTE'} (attendu : "
                      f"{', '.join(map(str, r['expected']))})", "", "> " + r["answer"].replace("\n", "\n> "), ""]
    return "\n".join(lines)


def main(profiles: list[str] | None = None, out: str = "agent_results.md") -> int:
    profiles = profiles or list(load_profiles()[1])
    results = {}
    for name in profiles:
        print(f"== {name}")
        results[name] = asyncio.run(run_profile(name))
    text = report(results)
    path = Path(out) if Path(out).is_absolute() else config.PROJECT_ROOT / "eval" / out
    path.write_text(text)
    print(f"\n→ {path}")
    return 0
