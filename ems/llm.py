import os
from pathlib import Path
from typing import Optional

from ems.config import ANTHROPIC_MODEL, DEFAULT_EMBEDDING_MODEL


def _load_dotenv(path: Optional[Path] = None) -> None:
    """Read `.env` into the environment for keys that are not already set.

    The repo has gitignored `.env` from the start but nothing ever read it, so
    the only way to run a live call was to put the key on the command line —
    where it lands in shell history and, when an agent is driving, in the
    conversation transcript. A file that is already ignored is the better place
    for a secret.

    Deliberately not `python-dotenv`: this project keeps four runtime
    dependencies and this is nine lines. A real environment variable always
    wins, so `KEY=... command` still overrides the file.
    """
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\'\""))


_load_dotenv()

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

_embedding_model = None

# Generous default — clinical answers/scenarios can be long. Streaming isn't
# needed at these sizes, but leave headroom so output isn't truncated.
_MAX_TOKENS = 8000

#: What a caller with somebody waiting on it should pass for `timeout`.
#:
#: The SDK default is ten minutes: a reasonable wait for a source ingest and an
#: unreasonable one for a persona, because the simulator asks Claude for a line
#: while a trainee is looking at the screen, and a turn that hangs reads as the
#: app being broken. Past this the call raises, `persona.safe_speak` swallows
#: it, and the trainee gets the scenario's own words — a plainer line beats a
#: frozen one. Batch jobs pass nothing and keep the generous default.
INTERACTIVE_TIMEOUT = float(os.environ.get("EMS_LLM_TIMEOUT", "45"))


def call_llm(
    prompt: str,
    system: str = "",
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """Send a prompt to Claude and return the response text.

    Uses the official Anthropic SDK. Credentials resolve from ANTHROPIC_API_KEY
    or an `ant auth login` profile (zero-arg client picks up either).

    Note: Opus 4.8 rejects sampling params (temperature/top_p/top_k) with a 400,
    so none are sent — steer behavior through the prompts instead.
    """
    if anthropic is None:
        raise ImportError("anthropic package required: pip install anthropic")

    # No timeout means the SDK's own generous default, which is what the
    # offline jobs want. See INTERACTIVE_TIMEOUT for the other case.
    client = anthropic.Anthropic() if timeout is None else anthropic.Anthropic(timeout=timeout)
    resolved_model = model or os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL)

    response = client.messages.create(
        model=resolved_model,
        max_tokens=_MAX_TOKENS,
        system=system or anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def get_embedding(text: str, model_name: Optional[str] = None) -> list[float]:
    """Embed text with a local sentence-transformers model. Lazy-loads on first call.

    Embeddings stay local (no API call) — unchanged by the Claude swap.
    """
    global _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers required: pip install sentence-transformers"
        )

    resolved_model = model_name or os.environ.get(
        "EMS_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    )
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(resolved_model)

    return _embedding_model.encode(text).tolist()
