"""Tests for the generated Obsidian vault.

The export rewrites frontmatter into shapes the application would reject —
`tags` with slashes, relationship fields holding `[[wikilinks]]` instead of
slugs. That is safe only because it is one way and lands somewhere nothing
reads. The first test in this file is the one that keeps it that way.
"""
import hashlib
import json
import shutil

import pytest
import yaml

from ems import obsidian_export as ox
from ems.cli import obsidian as cli
from ems.frontmatter import read_page
from ems.paths import wiki_dir
from ems.tags import valid_tags


def _page(path, body="\n## Notes\nText.\n", **fm):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.dump(fm, sort_keys=False) + "---\n" + body, encoding="utf-8"
    )


@pytest.fixture
def source(tmp_path):
    wiki = tmp_path / "wiki"
    _page(wiki / "conditions" / "_template.md", type="condition")
    _page(
        wiki / "conditions" / "anaphylaxis.md",
        "\n## Field management\nGive [[epinephrine]].\n",
        type="condition",
        title="Anaphylaxis",
        scope_level="EMT-B",
        age_group=["adult", "pediatric"],
        linked_pages=["epinephrine", "oxygen"],
        status="active",
    )
    _page(
        wiki / "scenarios" / "src19-s01.md",
        "\n## Dispatch\nMan down.\n",          # deliberately no wikilink
        type="scenario",
        source_index=19,
        kind="patient-care",
        tags=["airway and breathing", "EMT well-being"],
        scope_level="EMT-B",
        status="approved",
        labeled_by="ry",
        corrected=True,
        conditions=["asthma"],
        medications=["oxygen"],
    )
    return wiki


@pytest.fixture
def vault(source, tmp_path):
    ox.export(source, tmp_path / "obsidian_wiki")
    return tmp_path / "obsidian_wiki"


def _fm(path):
    return read_page(path)[0]


# ── the safety property ──────────────────────────────────────────────────────

def test_the_source_wiki_is_never_written_to(source, tmp_path):
    """The whole design rests on this. If it fails, nothing else matters."""
    before = {
        p.relative_to(source): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.md"))
    }
    ox.export(source, tmp_path / "obsidian_wiki")
    after = {
        p.relative_to(source): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.md"))
    }
    assert before == after


def test_exporting_onto_the_source_is_refused(source, capsys):
    assert cli.main(["export", "--source", str(source), "--dest", str(source)]) == 2
    assert "refusing" in capsys.readouterr().err


def test_the_real_corpus_is_not_the_destination():
    """A default run must never resolve `dest` to the corpus itself."""
    assert (wiki_dir() / "obsidian_wiki") != wiki_dir()


# ── tags ─────────────────────────────────────────────────────────────────────

def test_no_exported_tag_contains_a_space(vault):
    """The bug this export exists for: Obsidian tags cannot contain spaces."""
    for path in vault.rglob("*.md"):
        for tag in _fm(path).get("tags") or ():
            assert " " not in tag, f"{path.name} has {tag!r}"


def test_topics_become_a_nested_namespace(vault):
    tags = _fm(vault / "scenarios" / "src19-s01.md")["tags"]
    assert "topic/airway-and-breathing" in tags
    assert "topic/emt-well-being" in tags


def test_every_varying_axis_becomes_a_facet(vault):
    tags = set(_fm(vault / "scenarios" / "src19-s01.md")["tags"])
    assert {"kind/patient-care", "status/approved",
            "source/src19", "review/corrected"} <= tags


def test_constant_axes_are_not_tagged(vault):
    """A facet with one value across the corpus is noise, not a filter.

    `scope_level` is EMT-B on all 553 notes, so `scope/emt-b` was a single graph
    node wired to everything, which flattened the layout into a disc. `type`
    only repeated the folder, and `reviewer` had one name on 361 notes — a
    spring pulling every signed call to the same point. None earns a tag.
    """
    tags = set(_fm(vault / "scenarios" / "src19-s01.md")["tags"])
    assert not [t for t in tags if t.startswith(("scope/", "type/", "reviewer/"))]


def test_the_reviewer_is_still_queryable_even_though_it_is_not_a_tag(vault):
    """Dropping the tag must not drop the data — Dataview still groups by it."""
    assert _fm(vault / "scenarios" / "src19-s01.md")["labeled_by"] == "ry"


def test_a_source_tag_is_not_bare_digits(vault):
    """`source/19` is the one shape Obsidian is fussy about."""
    for tag in _fm(vault / "scenarios" / "src19-s01.md")["tags"]:
        assert not tag.split("/")[-1].isdigit()


def test_every_exported_topic_traces_back_to_the_vocabulary():
    """A topic tag in the vault must be a slugified real tag, not an invention."""
    legal = {ox.slugify(t) for t in valid_tags()}
    for tag in ox.obsidian_tags({"tags": sorted(valid_tags())}):
        assert tag.startswith("topic/")
        assert tag[len("topic/"):] in legal


# ── links ────────────────────────────────────────────────────────────────────

def test_relationship_fields_become_wikilinks(vault):
    fm = _fm(vault / "conditions" / "anaphylaxis.md")
    assert fm["linked_pages"] == ["[[epinephrine]]", "[[oxygen]]"]


def test_the_plain_slugs_survive_for_dataview(vault):
    fm = _fm(vault / "conditions" / "anaphylaxis.md")
    assert fm["linked_pages_slugs"] == ["epinephrine", "oxygen"]


def test_a_body_with_no_link_gains_a_related_line(vault):
    """78 scenarios were graph orphans; their relationships were only in YAML."""
    body = (vault / "scenarios" / "src19-s01.md").read_text()
    assert "## Related" in body
    assert "[[asthma]]" in body and "[[oxygen]]" in body


def test_a_body_that_already_links_is_left_alone(vault):
    body = (vault / "conditions" / "anaphylaxis.md").read_text()
    assert body.count("## Related") == 0


def test_original_fields_are_preserved(vault):
    """Dataview queries the real values; dropping one would lose information."""
    fm = _fm(vault / "conditions" / "anaphylaxis.md")
    assert fm["scope_level"] == "EMT-B"
    assert fm["age_group"] == ["adult", "pediatric"]
    assert fm["aliases"] == ["Anaphylaxis"]


# ── the vault as a whole ─────────────────────────────────────────────────────

def test_templates_are_not_exported(vault):
    assert not (vault / "conditions" / "_template.md").exists()


def test_dashboards_are_written(vault):
    names = {p.stem for p in (vault / "dashboards").glob("*.md")}
    assert {"Start here", "Coverage gaps", "Charts"} <= names


def test_a_second_export_drops_a_page_deleted_upstream(source, tmp_path):
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest)
    assert (dest / "conditions" / "anaphylaxis.md").exists()
    (source / "conditions" / "anaphylaxis.md").unlink()
    ox.export(source, dest)
    assert not (dest / "conditions" / "anaphylaxis.md").exists()


def test_the_users_obsidian_directory_survives_a_rebuild(source, tmp_path):
    """`.obsidian/` holds their plugins and layout. Losing it would be rude."""
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest)
    plugins = dest / ".obsidian" / "community-plugins.json"
    plugins.write_text('["dataview"]', encoding="utf-8")
    tuned = dest / ".obsidian" / "graph.json"
    tuned.write_text('{"mine": true}', encoding="utf-8")

    ox.export(source, dest)

    assert plugins.read_text() == '["dataview"]'
    assert json.loads(tuned.read_text()) == {"mine": True}, "overwrote their graph tuning"


def test_a_graph_config_is_written_when_there_is_none(vault):
    config = json.loads((vault / ".obsidian" / "graph.json").read_text())
    assert "path:conditions" in [g["query"] for g in config["colorGroups"]]


def test_the_graph_shows_tags_as_nodes(vault):
    """Without this the graph is page-to-page links and the topics are invisible.

    It is the setting the whole scenario/topic network depends on.
    """
    assert json.loads((vault / ".obsidian" / "graph.json").read_text())["showTags"] is True


def test_reset_graph_overwrites_and_keeps_a_backup(source, tmp_path):
    """The opt-in escape hatch: the GUI is a bad way to enter decimal RGB."""
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest)
    config = dest / ".obsidian" / "graph.json"
    config.write_text('{"repelStrength": 1, "mine": "keep me"}', encoding="utf-8")

    ox.export(source, dest, reset_graph=True)

    written = json.loads(config.read_text())
    assert written["repelStrength"] == 14, "did not apply the tuned value"
    assert written["mine"] == "keep me", "dropped a key it does not manage"
    assert json.loads((dest / ".obsidian" / "graph.json.bak").read_text())["repelStrength"] == 1


def test_reset_graph_is_off_by_default(source, tmp_path):
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest)
    (dest / ".obsidian" / "graph.json").write_text('{"mine": true}', encoding="utf-8")
    ox.export(source, dest)
    assert json.loads((dest / ".obsidian" / "graph.json").read_text()) == {"mine": True}


def test_group_colors_are_the_integers_obsidian_stores(source, tmp_path):
    """The reason this is not done through the GUI at all."""
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest, reset_graph=True)
    groups = json.loads((dest / ".obsidian" / "graph.json").read_text())["colorGroups"]
    calls = next(g for g in groups if g["query"] == "path:scenarios")
    assert calls["color"]["rgb"] == 0x7DA9E0


def test_graph_colors_are_far_enough_apart_to_tell_at_dot_size():
    """The bug this palette replaced: two groups one degree of hue apart.

    A graph node is a few pixels across and carries hue and little else, so
    house-style harmony is the wrong objective here. 20 degrees is the floor.
    """
    import colorsys

    def hue(value: str) -> float:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[0] * 360

    hues = sorted(hue(c) for _, c in ox.GRAPH_GROUPS)
    gaps = [min((b - a) % 360, (a - b) % 360) for a, b in zip(hues, hues[1:] + hues[:1])]
    assert min(gaps) >= 20, f"two groups are {min(gaps):.0f} degrees apart"


def test_the_uncolored_hubs_read_as_absence_of_color():
    """The topic-hub swatch is deliberately neutral, not another hue.

    Hue distance is the wrong measure for it — it sits 3 degrees from the
    scenario blue and is still unmistakable, because what separates it is having
    almost no saturation. Testing it as a sixth hue would force a color onto
    something whose whole meaning is that nothing colored it.
    """
    import colorsys

    for value in ox.LEGEND_EXTRA.values():
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        assert colorsys.rgb_to_hls(r, g, b)[2] < 0.15, f"{value} is a color, not a gray"


def test_dashboards_are_kept_out_of_the_graph(source, tmp_path):
    """They are tooling, not corpus — an island of noise beside the real thing.

    They still exist in the vault; they are only filtered from the graph view.
    """
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest, reset_graph=True)
    config = json.loads((dest / ".obsidian" / "graph.json").read_text())
    assert "-path:dashboards" in config["search"]
    assert "path:dashboards" not in [g["query"] for g in config["colorGroups"]]
    assert (dest / "dashboards" / "Graph.md").exists(), "filtered, not deleted"


def test_a_legend_is_painted_onto_the_graph(source, tmp_path):
    """Obsidian has no legend; the groups are visible only behind the gear."""
    import base64
    import re
    import xml.dom.minidom

    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest, reset_graph=True)
    css = (dest / ".obsidian" / "snippets" / "graph-legend.css").read_text()

    svg = base64.b64decode(re.search(r"base64,([A-Za-z0-9+/=]+)", css).group(1)).decode()
    xml.dom.minidom.parseString(svg)          # malformed SVG renders as nothing
    for _, color in ox.GRAPH_GROUPS:
        assert color in svg, f"{color} is on the graph but not in its legend"
    assert "pointer-events: none" in css, "a legend must not swallow canvas clicks"


def test_the_legend_box_is_exactly_the_size_of_its_drawing(source, tmp_path):
    """A row was clipped when these came from two different sources.

    The CSS box was sized from the color groups and the SVG drawn from the
    legend rows; dropping a group left the fifth row rendered but cut off.
    """
    import base64
    import re

    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest, reset_graph=True)
    css = (dest / ".obsidian" / "snippets" / "graph-legend.css").read_text()
    svg = base64.b64decode(re.search(r"base64,([A-Za-z0-9+/=]+)", css).group(1)).decode()

    box = (int(re.search(r"width: (\d+)px", css).group(1)),
           int(re.search(r"height: (\d+)px", css).group(1)))
    drawing = (int(re.search(r'width="(\d+)"', svg).group(1)),
               int(re.search(r'height="(\d+)"', svg).group(1)))
    assert box == drawing, f"box {box} clips a drawing of {drawing}"
    assert len(re.findall(r"</text>", svg)) == len(ox.LEGEND_ORDER)


def test_a_fresh_vault_opens_dark(source, tmp_path):
    """Everything here is drawn for a dark ground.

    Obsidian opens light by default, the chart blocks set light text because
    Chart.js otherwise draws near-black, and the legend is a dark panel. A fresh
    vault on the default theme renders charts nobody can read.
    """
    dest = tmp_path / "obsidian_wiki"
    ox.export(source, dest, reset_graph=True)
    assert json.loads((dest / ".obsidian" / "appearance.json").read_text())["theme"] == "obsidian"


def test_an_existing_theme_choice_is_left_alone(source, tmp_path):
    dest = tmp_path / "obsidian_wiki"
    appearance = dest / ".obsidian"
    appearance.mkdir(parents=True)
    (appearance / "appearance.json").write_text('{"theme": "moonstone"}', encoding="utf-8")

    ox.export(source, dest, reset_graph=True)

    settings = json.loads((appearance / "appearance.json").read_text())
    assert settings["theme"] == "moonstone", "overrode a theme the reader picked"


def test_the_legend_is_enabled_without_visiting_settings(source, tmp_path):
    dest = tmp_path / "obsidian_wiki"
    appearance = dest / ".obsidian" / "appearance.json"
    appearance.parent.mkdir(parents=True)
    appearance.write_text('{"theme": "obsidian"}', encoding="utf-8")

    ox.export(source, dest, reset_graph=True)

    settings = json.loads(appearance.read_text())
    assert settings["enabledCssSnippets"] == ["graph-legend"]
    assert settings["theme"] == "obsidian", "clobbered an unrelated setting"


def test_no_group_tries_to_color_a_tag_node():
    """A color group matches notes, never tag nodes — learned twice over.

    With `tag:#topic` first it claimed all 368 notes carrying a topic tag and
    painted every scenario orange; moved last it matched nothing at all. Either
    way it is a setting that does not do what it appears to, so it is gone. The
    hubs keep Obsidian's default color and the legend says so.
    """
    assert not [q for q, _ in ox.GRAPH_GROUPS if q.startswith("tag:")]


def test_the_legend_covers_every_group_and_nothing_invented():
    """The legend is ordered for reading, the groups for matching. Neither may
    drop a category or advertise a color that appears nowhere."""
    assert set(ox.LEGEND_ORDER) == {q for q, _ in ox.GRAPH_GROUPS} | set(ox.LEGEND_EXTRA)


def test_the_export_is_deterministic(source, tmp_path):
    """Same input, same bytes — so a rebuild is never a spurious diff."""
    first, second = tmp_path / "a", tmp_path / "b"
    ox.export(source, first)
    shutil.copytree(first, tmp_path / "snapshot")
    ox.export(source, second)
    for page in sorted(first.rglob("*.md")):
        assert page.read_text() == (second / page.relative_to(first)).read_text()
