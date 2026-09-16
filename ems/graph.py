"""Knowledge graph over canonical wiki pages (Phase 4).

Edges come from the typed relationship fields the page updater already populates
(`RELATIONSHIP_RULES`) plus `[[wikilinks]]`/`linked_pages` as generic `related`
edges. Persisted to `system/graph.yaml`; rebuilt on demand.
"""
from typing import Optional

import yaml

from ems.config import RELATIONSHIP_RULES
from ems.frontmatter import read_page
from ems.markdown import extract_wikilinks
from ems.page_updater import _dir_type, iter_page_paths
from ems.paths import graph_path


def build_graph() -> dict:
    """Scan every page's frontmatter + links into a {nodes, edges} graph."""
    pages = iter_page_paths()
    nodes = {p.stem: read_page(p)[0].get("type", _dir_type(p)) for p in pages}

    edges: set[tuple[str, str, str]] = set()
    for path in pages:
        fm, body = read_page(path)
        slug = path.stem
        ptype = nodes[slug]
        for rule in RELATIONSHIP_RULES:
            if rule["source_type"] != ptype:
                continue
            fwd, rev = rule["edges"]
            for target in fm.get(rule["field"]) or []:
                edges.add((slug, fwd, target))
                edges.add((target, rev, slug))
        for target in (fm.get("linked_pages") or []) + extract_wikilinks(body):
            if target != slug:
                edges.add((slug, "related", target))
        for age in fm.get("age_group") or []:
            nodes.setdefault(age, "age_group")
            edges.add((slug, "applies_to_age", age))
            edges.add((age, "age_applies_to", slug))

    graph = {"nodes": nodes, "edges": [list(e) for e in sorted(edges)]}
    save_graph(graph)
    return graph


def get_or_build_graph() -> dict:
    return load_graph() if graph_path().exists() else build_graph()


# ── traversal ────────────────────────────────────────────────────────────────

def get_related(graph: dict, slug: str) -> list[str]:
    """Neighbor slugs in either direction."""
    out = set()
    for src, _rel, dst in graph["edges"]:
        if src == slug:
            out.add(dst)
        elif dst == slug:
            out.add(src)
    return sorted(out)


def what_treats(graph: dict, condition_slug: str) -> list[str]:
    """Protocols that treat a condition."""
    return sorted(s for s, rel, d in graph["edges"] if rel == "treats" and d == condition_slug)


def what_meds(graph: dict, slug: str) -> list[str]:
    """Medications administered in a protocol."""
    return sorted(d for s, rel, d in graph["edges"] if rel == "administers" and s == slug)


def graph_stats(graph: dict) -> dict:
    return {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])}


# ── persistence ──────────────────────────────────────────────────────────────

def load_graph() -> dict:
    return yaml.safe_load(graph_path().read_text(encoding="utf-8"))


def save_graph(graph: dict) -> None:
    path = graph_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(graph, allow_unicode=True, sort_keys=False), encoding="utf-8")
