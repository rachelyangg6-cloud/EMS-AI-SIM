"""protocol-graph — build and explore the knowledge graph."""
import argparse
import sys

from ems import graph


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-graph",
        description="Build/query the wiki knowledge graph.",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("rebuild", help="Rebuild system/graph.yaml from page frontmatter")
    sub.add_parser("stats", help="Show node/edge counts")
    p_rel = sub.add_parser("related", help="List neighbors of a slug")
    p_rel.add_argument("slug")
    p_treats = sub.add_parser("treats", help="Protocols that treat a condition")
    p_treats.add_argument("condition")
    p_meds = sub.add_parser("meds", help="Medications administered in a protocol")
    p_meds.add_argument("protocol")
    args = parser.parse_args()

    if args.cmd == "rebuild":
        g = graph.build_graph()
        s = graph.graph_stats(g)
        print(f"rebuilt: {s['nodes']} nodes, {s['edges']} edges", file=sys.stderr)
        return 0

    g = graph.get_or_build_graph()
    if args.cmd == "stats":
        s = graph.graph_stats(g)
        print(f"{s['nodes']} nodes, {s['edges']} edges", file=sys.stderr)
    elif args.cmd == "related":
        print("\n".join(graph.get_related(g, args.slug)))
    elif args.cmd == "treats":
        print("\n".join(graph.what_treats(g, args.condition)))
    elif args.cmd == "meds":
        print("\n".join(graph.what_meds(g, args.protocol)))
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
