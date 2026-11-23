"""Étape 8 : agent conversationnel en français sur les factures.

- Il n'a accès aux données **que** par le serveur MCP (lancé en sous-processus, protocole stdio) : il
  ne connaît ni DuckDB, ni les fichiers. Ses seuls outils sont ceux que le serveur expose.
- Le LLM est **interchangeable par configuration** (llm_profiles.toml + LLM_PROFILE ou --llm) : tout
  serveur compatible « chat completions » avec appel d'outils convient (AI Gateway Hyperfluid / vLLM,
  Ollama en local…). Aucune ligne de code ne dépend du modèle choisi.
- L'utilisateur **voit** ce que fait l'agent : chaque outil appelé, ses arguments, le SQL réellement
  exécuté et un aperçu du résultat, avant la réponse finale.
- L'historique est conservé d'une question à l'autre (/reset pour repartir de zéro) ; la boucle est
  bornée (max_steps) et l'agent s'arrête proprement (/quit, Ctrl-D, Ctrl-C).
"""

import asyncio
import json
import os
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from mcp import Client, StdioServerParameters
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from factures import config

PROFILES_PATH = config.PROJECT_ROOT / "llm_profiles.toml"
MAX_TOOL_RESULT_CHARS = 12_000

SYSTEM_PROMPT = """Tu es l'assistant comptable de l'entreprise. Tu réponds en français aux questions sur les \
factures fournisseurs, en t'appuyant UNIQUEMENT sur les outils fournis (serveur MCP « factures »).

Règles :
- Tout chiffre (montant, nombre de factures, date) doit provenir d'un résultat d'outil de cette conversation. \
N'invente jamais un chiffre et ne le recalcule pas de tête : pour une somme ou un comptage, appelle invoice_totals.
- Recopie les montants exactement tels que renvoyés, en euros, au format français (ex. 106 886,43 €).
- Choix des outils : invoice_totals pour compter ou additionner ; list_invoices pour lister ou trouver des \
factures ; get_invoice pour le détail d'une facture ; describe_schema puis run_sql seulement si aucun autre \
outil ne convient.
- Si un outil renvoie une erreur, lis le message, corrige tes arguments et réessaie.
- Si les données ne permettent pas de répondre, dis-le simplement.
- Si une facture concernée est « signalee » (anomalie détectée), signale-le dans ta réponse.
- Réponds de façon concise ; termine par une courte ligne « Source : » indiquant l'outil utilisé.
Date du jour : {today}."""


# --------------------------------------------------------------------------- configuration du LLM

@dataclass
class LLMProfile:
    name: str
    base_url: str
    model: str
    api_key: str
    description: str = ""
    temperature: float = 0.0


def load_profiles(path: Path = PROFILES_PATH) -> tuple[str, dict]:
    data = tomllib.loads(path.read_text())
    return data.get("default", ""), data.get("profiles", {})


def load_profile(name: str | None = None, path: Path = PROFILES_PATH) -> LLMProfile:
    """Profil choisi : argument > variable LLM_PROFILE > `default` du fichier."""
    default, profiles = load_profiles(path)
    name = name or os.getenv("LLM_PROFILE") or default
    if name not in profiles:
        raise SystemExit(f"Profil LLM inconnu : {name!r}. Profils disponibles : {', '.join(profiles)}")
    p = profiles[name]
    key = p.get("api_key")
    for env in p.get("api_key_env", []):
        key = key or os.getenv(env)
    if not key:
        raise SystemExit(f"Profil {name} : aucune clé trouvée dans {p.get('api_key_env')} (voir .env.example).")
    return LLMProfile(name=name, base_url=p["base_url"], model=p["model"], api_key=key,
                      description=p.get("description", ""), temperature=p.get("temperature", 0.0))


def mcp_server_params() -> StdioServerParameters:
    """Le serveur MCP du projet, lancé avec le même interpréteur Python (stdio).

    Ses journaux sont réduits aux avertissements : l'agent affiche lui-même le SQL exécuté.
    """
    return StdioServerParameters(command=sys.executable, args=["-m", "factures.mcp_server"],
                                 env={**os.environ, "DATA_DIR": str(config.DATA_DIR), "FACTURES_MCP_LOG": "WARNING"})


def clean_answer(text: str) -> str:
    """Retire les jetons de contrôle que certains modèles laissent passer (ex. Gemma : <|channel>thought <channel|>)."""
    import re

    if "<channel|>" in text:          # canal de réflexion de Gemma : seule la partie finale est la réponse
        text = text.split("<channel|>")[-1]
    return re.sub(r"<\|?[a-z_]+\|?>", "", text).strip()


# --------------------------------------------------------------------------- affichage

class Display:
    def __init__(self, console: Console | None = None, quiet: bool = False):
        self.console = console or Console()
        self.quiet = quiet

    def info(self, text: str) -> None:
        if not self.quiet:
            self.console.print(f"[dim]{text}[/dim]")

    def tool_call(self, step: int, name: str, args: dict) -> None:
        if not self.quiet:
            shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
            self.console.print(f"[bold cyan]🔧 Étape {step} — {name}[/bold cyan]([yellow]{shown}[/yellow])")

    def tool_result(self, result: dict | str, is_error: bool) -> None:
        if self.quiet:
            return
        if is_error:
            self.console.print(f"   [red]✗ erreur renvoyée au LLM :[/red] {str(result)[:300]}")
            return
        for q in result.get("sql", []):
            params = f"   -- paramètres : {q['params']}" if q.get("params") else ""
            self.console.print(Syntax(q["query"] + params, "sql", word_wrap=True, background_color="default"),
                               style="dim")
        rows = result.get("rows") or result.get("invoices") or result.get("lines")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            cols = list(rows[0])[:8]
            for c in cols:
                table.add_column(c, overflow="fold")
            for r in rows[:8]:
                table.add_row(*(str(r.get(c)) for c in cols))
            self.console.print(table)
            extra = result.get("total_matching")
            if len(rows) > 8 or extra:
                self.console.print(f"   [dim]{len(rows)} ligne(s) renvoyée(s)"
                                   + (f", {extra} au total" if extra is not None else "") + "[/dim]")
        elif "invoice" in result:
            inv = result["invoice"]
            self.console.print(f"   [dim]facture {inv.get('invoice_number')} — {inv.get('supplier_name')} → "
                               f"{inv.get('client_name')}, TTC {inv.get('total_ttc')} €[/dim]")
        elif "views" in result:
            self.console.print(f"   [dim]{len(result['views'])} vues décrites[/dim]")

    def answer(self, text: str, profile: LLMProfile, seconds: float, steps: int) -> None:
        if self.quiet:
            return
        self.console.print(Panel(Markdown(text or "_(réponse vide)_"), border_style="green",
                                 subtitle=f"{profile.model} · {steps} appel(s) d'outil · {seconds:.1f} s"))


# --------------------------------------------------------------------------- agent

@dataclass
class ToolCall:
    name: str
    args: dict
    is_error: bool
    sql: list = field(default_factory=list)


@dataclass
class Turn:
    question: str
    answer: str
    tool_calls: list[ToolCall]
    seconds: float
    llm_calls: int
    stopped: str = "fin"          # fin | max_steps | erreur_llm


class Agent:
    def __init__(self, client: Client, profile: LLMProfile, display: Display | None = None, max_steps: int = 8):
        from openai import OpenAI

        self.client = client
        self.display = display or Display()
        self.max_steps = max_steps
        self.tools: list[dict] = []
        self.set_profile(profile)
        self.reset()

    def set_profile(self, profile: LLMProfile) -> None:
        from openai import OpenAI

        self.profile = profile
        self.llm = OpenAI(base_url=profile.base_url, api_key=profile.api_key, timeout=180, max_retries=1)

    def reset(self) -> None:
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]

    async def load_tools(self) -> None:
        """Les outils du serveur MCP, traduits au format « function calling » du LLM."""
        listed = await self.client.list_tools()
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                        "parameters": t.input_schema}} for t in listed.tools]

    async def _call_llm(self):
        return await asyncio.to_thread(
            self.llm.chat.completions.create, model=self.profile.model, messages=self.messages,
            tools=self.tools, temperature=self.profile.temperature,
        )

    async def ask(self, question: str) -> Turn:
        start, calls, n_llm = time.perf_counter(), [], 0
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": question})

        for _ in range(self.max_steps):
            try:
                resp = await self._call_llm()
            except Exception as exc:  # LLM injoignable, clé refusée… : on annule proprement ce tour
                del self.messages[checkpoint:]
                text = f"Le LLM ({self.profile.name}) n'a pas répondu : {type(exc).__name__}: {str(exc)[:200]}"
                self.display.console.print(f"[red]{text}[/red]")
                return Turn(question, text, calls, time.perf_counter() - start, n_llm, "erreur_llm")
            n_llm += 1
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            self.messages.append({
                "role": "assistant", "content": msg.content or "",
                **({"tool_calls": [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                   for c in tool_calls]} if tool_calls else {}),
            })
            if not tool_calls:
                answer = clean_answer(msg.content or "")
                self.messages[-1]["content"] = answer
                turn = Turn(question, answer, calls, time.perf_counter() - start, n_llm)
                self.display.answer(answer, self.profile, turn.seconds, len(calls))
                return turn

            for c in tool_calls:
                content, call = await self._run_tool(len(calls) + 1, c.function.name, c.function.arguments)
                calls.append(call)
                self.messages.append({"role": "tool", "tool_call_id": c.id, "content": content})

        answer = (f"Je m'arrête après {self.max_steps} étapes sans réponse définitive. "
                  "Reformulez ou précisez la question.")
        self.messages.append({"role": "assistant", "content": answer})
        self.display.answer(answer, self.profile, time.perf_counter() - start, len(calls))
        return Turn(question, answer, calls, time.perf_counter() - start, n_llm, "max_steps")

    async def _run_tool(self, step: int, name: str, raw_args: str) -> tuple[str, ToolCall]:
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError("les arguments doivent être un objet JSON")
        except ValueError as exc:
            msg = f"Arguments JSON invalides pour {name} : {exc}. Renvoie un objet JSON valide."
            self.display.tool_call(step, name, {"<brut>": raw_args})
            self.display.tool_result(msg, True)
            return msg, ToolCall(name, {}, True)

        self.display.tool_call(step, name, args)
        r = await self.client.call_tool(name, args)
        text = "\n".join(getattr(b, "text", "") for b in r.content) if r.content else ""
        if r.is_error:
            self.display.tool_result(text, True)
            return text, ToolCall(name, args, True)
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {"raw": text}
        self.display.tool_result(payload, False)
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "\n…[résultat tronqué : affinez les filtres ou réduisez limit]"
        return text, ToolCall(name, args, False, payload.get("sql", []) if isinstance(payload, dict) else [])


# --------------------------------------------------------------------------- interface en ligne de commande

HELP = ("Commandes : /reset (nouvelle conversation) · /llm <profil> (changer de LLM) · /llms (profils) · "
        "/quit (quitter, ou Ctrl-D)")


async def repl(profile: LLMProfile, question: str | None = None, max_steps: int = 8) -> None:
    display = Display()
    async with Client(mcp_server_params()) as client:
        agent = Agent(client, profile, display, max_steps)
        await agent.load_tools()
        display.console.print(Panel.fit(
            f"[bold]Assistant factures[/bold] — LLM : [green]{profile.name}[/green] ({profile.model})\n"
            f"Outils MCP : {', '.join(t['function']['name'] for t in agent.tools)}\n{HELP}",
            border_style="blue"))
        if question:
            display.console.print(f"[bold]» {question}[/bold]")
            await agent.ask(question)
            return
        while True:
            try:
                line = (await asyncio.to_thread(display.console.input, "[bold]» [/bold]")).strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/reset":
                agent.reset()
                display.info("Conversation effacée.")
            elif line == "/llms":
                default, profiles = load_profiles()
                for n, p in profiles.items():
                    display.console.print(f"  {'*' if n == agent.profile.name else ' '} {n:<22} {p.get('description', '')}")
            elif line.startswith("/llm "):
                try:
                    agent.set_profile(load_profile(line.split(maxsplit=1)[1]))
                    display.info(f"LLM : {agent.profile.name} ({agent.profile.model}) — l'historique est conservé.")
                except SystemExit as exc:
                    display.console.print(f"[red]{exc}[/red]")
            elif line.startswith("/"):
                display.info(HELP)
            else:
                await agent.ask(line)
    display.info("Au revoir.")


def main(profile_name: str | None = None, question: str | None = None, max_steps: int = 8) -> int:
    profile = load_profile(profile_name)
    try:
        asyncio.run(repl(profile, question, max_steps))
    except KeyboardInterrupt:
        print("\nInterrompu — connexion MCP fermée.", file=sys.stderr)
    return 0
