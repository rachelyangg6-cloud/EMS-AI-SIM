"""protocol-embed — build/refresh the local section-level vector index."""
import argparse
import sys

from ems import embeddings


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-embed",
        description="Build the local vector index over canonical wiki pages.",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild from scratch")
    parser.add_argument("--stats", action="store_true", help="Show index stats and exit")
    args = parser.parse_args()

    if args.stats:
        s = embeddings.index_stats()
        print(f"model={s['model']} sections={s['sections']} pages={s['pages']}", file=sys.stderr)
        return 0

    print("building embedding index (local model) ...", file=sys.stderr)
    index = embeddings.build_embedding_index(force=args.force)
    print(f"  {len(index['sections'])} sections embedded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
