"""Find a call by what it is about, rather than by its filename.

The setup form has one box for picking a specific call, and until now it took a
scenario id and nothing else — so "hypoxia" was a 404 and the only way to
practice a topic was to already know that `src19-s02` was the one you wanted.
Nobody knows that. The corpus does know it: 248 approved scenarios carry 54
condition slugs and 23 topic tags between them, and `hypoxia` alone is on 26.

Matching is tiered rather than scored, because a tie between "a scenario whose
condition IS hypoxia" and "a scenario whose dispatch happens to say hypoxic"
should not be a tie. The best tier that matches anything wins outright and the
weaker ones are discarded, so asking for a condition by name never deals you a
call that merely mentions it.
"""

import difflib
import re
from pathlib import Path

from ems.frontmatter import read_page
from ems.markdown import get_section


def normalize(text: str) -> str:
    """Lowercase, hyphens and underscores to spaces, whitespace collapsed.

    This is what makes the `chest-pain` slug and a typed "Chest Pain" the same
    string, which is the whole trick: the vocabulary is kebab-case and nobody
    types kebab-case.
    """
    return re.sub(r"[\s_-]+", " ", text.strip().lower())


def vocabulary(paths: list[Path]) -> list[str]:
    """Every condition and tag in the pool, normalized — what you may ask for."""
    found: set[str] = set()
    for path in paths:
        frontmatter, _ = read_page(path)
        for key in ("conditions", "tags"):
            for term in frontmatter.get(key) or ():
                found.add(normalize(str(term)))
    return sorted(found)


def _tier(query: str, frontmatter: dict, body: str) -> int:
    """How well this scenario answers `query`. 0 is no match, 3 is best."""
    conditions = {normalize(str(c)) for c in frontmatter.get("conditions") or ()}
    tags = {normalize(str(t)) for t in frontmatter.get("tags") or ()}

    if query in conditions:
        return 3
    # Substring so "chest pain" finds `chest-pain-cardiac` and "seizure" finds
    # `febrile-seizure` — a trainee asking for a topic means the family of it.
    if query in tags or any(query in term for term in conditions | tags):
        return 2

    # Last resort, and deliberately the strictest test: every word has to be
    # there. A single shared word ("the", "with") is not what the call is about.
    dispatch = normalize(get_section(body, "Dispatch") or "")
    if dispatch and all(word in dispatch for word in query.split()):
        return 1
    return 0


def match(query: str, paths: list[Path]) -> list[Path]:
    """Scenarios that are about `query`, best tier only. Empty means no match."""
    query = normalize(query)
    if not query:
        return []

    tiers: dict[int, list[Path]] = {}
    for path in paths:
        tier = _tier(query, *read_page(path))
        if tier:
            tiers.setdefault(tier, []).append(path)
    return tiers[max(tiers)] if tiers else []


def suggest(query: str, paths: list[Path], limit: int = 5) -> list[str]:
    """Topics close to one that matched nothing, for the error message.

    A 404 saying only "no such topic" leaves the trainee guessing at a
    vocabulary they cannot see; one that says "did you mean hypoglycemia" is the
    difference between a dead end and a second try.
    """
    terms = vocabulary(paths)
    query = normalize(query)
    close = difflib.get_close_matches(query, terms, n=limit, cutoff=0.6)
    # Substring hits are obvious to a human and often missed by edit distance:
    # "chest" is not close to "chest pain" by ratio, but it is clearly the ask.
    partial = [t for t in terms if query in t and t not in close]
    return (close + partial)[:limit]
