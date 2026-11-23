"""Tests de l'étape 8 : la boucle de l'agent, avec un faux LLM scripté et le vrai serveur MCP (stdio)."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest
from mcp import Client, StdioServerParameters

from factures.agent import Agent, Display, LLMProfile, clean_answer, load_profile
from factures.agent_bench import contains, numbers_in
from test_step7_mcp import data_dir  # noqa: F401 — fixture : petit entrepôt de test

pytestmark = pytest.mark.filterwarnings("ignore")
PROFILE = LLMProfile(name="faux", base_url="http://x", model="faux-llm", api_key="k")


def _call(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=args))


def _resp(content="", calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


class ScriptedLLM:
    """Rejoue des réponses prédéfinies et garde les messages reçus, pour vérifier ce que voit le LLM."""

    def __init__(self, script):
        self.script, self.seen = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.seen.append(json.loads(json.dumps(kw["messages"], default=str)))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def run(data_dir, script, questions, max_steps=8):
    params = StdioServerParameters(command=sys.executable, args=["-m", "factures.mcp_server"],
                                   env={**os.environ, "DATA_DIR": str(data_dir), "FACTURES_MCP_LOG": "WARNING"})

    async def go():
        async with Client(params) as client:
            agent = Agent(client, PROFILE, Display(quiet=True), max_steps)
            agent.llm = ScriptedLLM(script)
            await agent.load_tools()
            turns = [await agent.ask(q) for q in questions]
            return agent, turns

    return asyncio.run(go())


def test_tool_loop_answers_from_mcp_and_keeps_history(data_dir):  # noqa: F811
    agent, (t1, t2) = run(data_dir, [
        _resp(calls=[_call(1, "invoice_totals", '{"status": "en retard"}')]),   # casse libre : acceptée
        _resp("<|channel>thought <channel|>Une facture en retard : 1 440,60 €."),
        _resp("Oui, B-7."),
    ], ["Montant des factures en retard ?", "Laquelle ?"])

    assert [c.name for c in t1.tool_calls] == ["invoice_totals"] and not t1.tool_calls[0].is_error
    assert t1.tool_calls[0].sql[0]["params"] == ["En retard"]          # SQL visible pour l'utilisateur
    assert t1.answer == "Une facture en retard : 1 440,60 €."           # jetons de contrôle retirés
    tool_msg = next(m for m in agent.llm.seen[1] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["rows"][0]["total_ttc"] == "1440.60"  # le LLM reçoit le vrai résultat
    # 2e question : l'historique complet (question 1, appel d'outil, réponse) est renvoyé au LLM.
    assert [m["role"] for m in agent.llm.seen[2]] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert t2.answer == "Oui, B-7." and t2.tool_calls == []


def test_errors_are_returned_to_the_llm_which_can_retry(data_dir):  # noqa: F811
    agent, (turn,) = run(data_dir, [
        _resp(calls=[_call(1, "invoice_totals", '{"status": "retard"}')]),   # valeur invalide
        _resp(calls=[_call(2, "get_invoice", "{pas du json")]),            # JSON invalide
        _resp(calls=[_call(3, "invoice_totals", '{"status": "En retard"}')]),
        _resp("1 facture."),
    ], ["Combien en retard ?"])
    assert [c.is_error for c in turn.tool_calls] == [True, True, False]
    errors = [m["content"] for m in agent.llm.seen[3] if m["role"] == "tool"][:2]
    assert "Valeurs possibles" in errors[0] and "JSON invalide" in errors[1]
    assert turn.answer == "1 facture." and turn.stopped == "fin"


def test_loop_is_bounded_and_llm_failure_rolls_back(data_dir):  # noqa: F811
    loop = [_resp(calls=[_call(i, "describe_schema", "{}")]) for i in range(3)]
    agent, (t1, t2) = run(data_dir, loop + [ConnectionError("LLM injoignable")], ["Boucle ?", "Et là ?"], max_steps=3)
    assert t1.stopped == "max_steps" and len(t1.tool_calls) == 3 and "Je m'arrête" in t1.answer
    assert t2.stopped == "erreur_llm"
    assert agent.messages[-1]["role"] == "assistant" and "Et là ?" not in str(agent.messages)  # tour annulé proprement


def test_profiles_are_chosen_by_configuration(monkeypatch):
    monkeypatch.setenv("OCR_API_KEY", "cle-test")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROFILE", "hyperfluid-granite")
    p = load_profile()
    assert p.model == "granite-4-2-8b" and p.api_key == "cle-test" and "/granite-4-2-8b/" in p.base_url
    assert load_profile("ollama-ministral").base_url == "http://localhost:11434/v1"
    with pytest.raises(SystemExit):
        load_profile("inexistant")


def test_answer_checking_helpers():
    assert clean_answer("<|channel>thought blabla<channel|>Réponse") == "Réponse"
    assert Decimal_set("106 886,43 €") == {"106886.43"}
    assert contains("Le client est Muller pour 22 195,44 €", "Muller") and not contains("rien", "Muller")


def Decimal_set(s):
    return {str(d) for d in numbers_in(s)}


def test_numbers_not_found_in_tool_results_trigger_one_correction(data_dir):  # noqa: F811
    totals = _call(1, "invoice_totals", '{"status": "En retard"}')
    agent, (fixed, still_wrong) = run(data_dir, [
        _resp(calls=[totals]),
        _resp("Il reste 14 440,60 € à payer."),     # chiffre mal recopié (le vrai : 1 440,60 €)
        _resp("Il reste 1 440,60 € à payer."),      # après la demande de correction
        _resp(calls=[_call(2, "invoice_totals", '{"status": "En retard"}')]),
        _resp("Il reste 9 999 € à payer."),
        _resp("Toujours 9 999 €."),                 # n'en démord pas → avertissement visible
    ], ["Combien reste-t-il ?", "Et maintenant ?"])
    assert fixed.answer == "Il reste 1 440,60 € à payer." and fixed.corrected and fixed.ungrounded == []
    correction = agent.llm.seen[2][-1]
    assert correction["role"] == "user" and "14 440,60" in correction["content"]
    assert still_wrong.ungrounded == ["9 999"] and "Vérification automatique" in still_wrong.answer


def test_numbers_from_question_or_arguments_are_allowed():
    from factures.agent import ungrounded_numbers

    assert ungrounded_numbers("En 2025, 12 factures pour 106 886,43 €.",
                              ['{"year": 2025}', '{"rows": [{"invoice_count": 12, "total_ttc": "106886.43"}]}']) == []
    assert ungrounded_numbers("Environ 3 factures.", []) == []   # petits entiers : non contrôlés
    # un arrondi demandé par l'utilisateur est accepté, une valeur inventée non
    assert ungrounded_numbers("Prix moyen : 86,67 €.", ['{"rows": [{"avg": 86.67133333333332}]}']) == []
    assert ungrounded_numbers("Prix moyen : 86,76 €.", ['{"rows": [{"avg": 86.67133333333332}]}']) == ["86,76"]
