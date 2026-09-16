"""Suite-wide guardrails.

The one thing here is that the tests never talk to Anthropic. That used to be
true by accident — the LLM layer was opt-in, so nothing reached it unless a test
asked — and it stopped being true when personas and the narrative debrief became
the default. On a machine with an `.env`, every call the API tests start would
otherwise become a live, billed, non-deterministic request.

A test that wants model output injects its own fake, as several already do. This
only closes the door on the real client.
"""
import pytest


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError(
            "a test tried to call Anthropic; inject a fake llm= instead"
        )

    # At each import site, because the sim modules bind `call_llm` at import
    # time. `safe_speak` swallowing this is the fallback being exercised.
    for module in ("ems.sim.persona", "ems.sim.debrief", "ems.sim.generate",
                   "ems.sim.reskin"):
        monkeypatch.setattr(f"{module}.call_llm", refuse, raising=False)
        monkeypatch.setattr(f"{module}._llm", refuse, raising=False)

    # And at the boundary itself, for anything that reaches `call_llm` by
    # another route. Not `ems.llm.call_llm`, which is a unit under test in
    # test_phase1 and supplies its own SDK double inside a narrower `patch`.
    monkeypatch.setattr("ems.llm.anthropic.Anthropic", refuse, raising=False)
