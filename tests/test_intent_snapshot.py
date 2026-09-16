"""The intent table's blast radius, made visible.

`classify` is global: every intent's patterns run against every line, and no
intent is scoped to the source that introduced it. So adding an intent
re-classifies all 33 sources at once, and narrowing one can stop matching lines
in a source nobody was editing. Three real examples are in the docstring of
`ems.cli.intent_snapshot`; none of them failed a test when they happened.

They did not fail because the guard next door,
`test_every_intent_a_rubric_can_produce_has_a_hint`, is existential — it asks
whether *some* approved line produces an intent. That stays true while
individual lines gain and lose it. This test is the per-line complement: it
pins what each line classifies to, so a change has to be looked at.

A failure here is not necessarily a bug. Most drift is improvement — 11 lines
correctly gained `distal-csm-check` in one pass. The point is that somebody
reads the diff and says which it is.
"""

from ems.cli.intent_snapshot import SNAPSHOT, render


def test_the_snapshot_matches_the_corpus():
    recorded = SNAPSHOT.read_text().splitlines()
    current = render().splitlines()

    if recorded == current:
        return

    was = {row.split("  ", 1)[0]: row for row in recorded if not row.startswith("#") and row}
    now = {row.split("  ", 1)[0]: row for row in current if not row.startswith("#") and row}

    changed = [(was[k], now[k]) for k in sorted(was.keys() & now.keys()) if was[k] != now[k]]
    added = [now[k] for k in sorted(now.keys() - was.keys())]
    removed = [was[k] for k in sorted(was.keys() - now.keys())]

    report = ["intent classification drifted from the checked-in snapshot.", ""]
    for before, after in changed[:40]:
        report += [f"  - {before}", f"  + {after}"]
    if len(changed) > 40:
        report.append(f"  … and {len(changed) - 40} more changed lines")
    for row in added[:15]:
        report.append(f"  new line: {row}")
    for row in removed[:15]:
        report.append(f"  gone:     {row}")
    report += [
        "",
        f"{len(changed)} changed, {len(added)} added, {len(removed)} removed.",
        "Read the diff. If every change is intended, run:",
        "    python -m ems.cli.intent_snapshot --update",
    ]
    raise AssertionError("\n".join(report))
