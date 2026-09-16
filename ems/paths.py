import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def get_wiki_root() -> Path:
    env = os.environ.get("EMS_WIKI_ENV", "DEV").upper()
    if env == "PROD":
        base = os.environ.get("EMS_WIKI_PROD_PATH")
        if not base:
            raise EnvironmentError(
                "EMS_WIKI_PROD_PATH must be set when EMS_WIKI_ENV=PROD"
            )
        return Path(base)
    return REPO_ROOT


def raw_dir() -> Path:
    return get_wiki_root() / "raw"


def wiki_dir() -> Path:
    return get_wiki_root() / "wiki"


def system_dir() -> Path:
    return get_wiki_root() / "system"


def vocabulary_path() -> Path:
    return system_dir() / "source-vocabulary.json"


def embeddings_path() -> Path:
    return system_dir() / "embeddings.json"


def graph_path() -> Path:
    return system_dir() / "graph.yaml"


def scenarios_dir() -> Path:
    return wiki_dir() / "scenarios"


def db_path() -> Path:
    """The simulator's SQLite file — practice history, not wiki content."""
    override = os.environ.get("EMS_DB_PATH")
    return Path(override) if override else get_wiki_root() / "var" / "ems.db"


def wiki_subdir(page_type: str) -> Path:
    from ems.config import TYPE_TO_DIR
    subdir = TYPE_TO_DIR.get(page_type)
    if not subdir:
        raise ValueError(f"Unknown page type: {page_type!r}")
    return wiki_dir() / subdir
