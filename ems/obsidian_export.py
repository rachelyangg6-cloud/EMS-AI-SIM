"""Export `wiki/` as an Obsidian vault at `obsidian_wiki/`.

**One way, always.** `wiki/` is the source of truth and the only thing the web
app and the Python read. This writes a derived copy shaped for Obsidian, and
nothing ever reads it back. That is what makes it safe to rewrite frontmatter
here in ways the application would reject.

Three things the corpus does that Obsidian cannot use as-is:

1. **Topic tags contain spaces.** `airway and breathing` is not a legal Obsidian
   tag, so the tag pane, `tag:` search and graph coloring all silently do
   nothing for the most useful axis in the corpus. Worse, `tags` is a reserved
   property: editing a note through Obsidian's own Properties UI could rewrite
   the field, and `ems.tags.valid_tags()` validates against those exact strings.
   Exporting rather than editing in place is what keeps that from ever mattering.

2. **`linked_pages` holds bare slugs**, which Obsidian sees as strings, not
   links — 639 edges invisible to the graph. The typed relationship fields
   (`conditions`, `medications`, …) have the same problem.

3. **78 scenarios carry no `[[wikilink]]` at all**, so they sit in the graph as
   orphans. Promoting their relationship fields to links connects every one of
   them to the clinical pages it is about.

The vault's own `.obsidian/` directory is never deleted — it holds installed
plugins and workspace layout, which are the user's, not ours.
"""

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Optional

import yaml

from ems.frontmatter import read_page
from ems.paths import get_wiki_root, wiki_dir

#: Content directories that are regenerated wholesale on each export. Anything
#: else in the vault — `.obsidian/`, notes the user wrote — is left alone.
CONTENT_DIRS = ("conditions", "procedures", "medications", "protocols", "scenarios")

#: Frontmatter fields naming other pages by slug. Each becomes `[[slug]]` so the
#: graph and backlinks can see it.
LINK_FIELDS = (
    "linked_pages",
    "conditions",
    "procedures",
    "medications",
    "protocols",
    "treats_conditions",
    "contraindicated_conditions",
    "used_in_protocols",
)

#: Frontmatter field → tag namespace. Each value becomes `namespace/slugified`,
#: so Obsidian's tag pane becomes a browsable tree instead of a flat list and
#: one click filters the graph to a topic, a source or a kind.
#: `scope_level` and `type` are deliberately absent. Every note in the corpus is
#: EMT-B, so `scope/emt-b` was one tag node wired to all 553 — a hub carrying no
#: information that pulled the whole graph into a featureless disc. `type` said
#: the same thing as the folder a note is already in. A facet whose value never
#: varies is noise in the tag pane as much as in the graph.
TAG_FACETS = {
    "tags": "topic",
    "kind": "kind",
    "status": "status",
    "age_group": "age",
}


def slugify(value: str) -> str:
    """`EMT well-being` → `emt-well-being`. Obsidian tags allow no spaces."""
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", str(value).lower())).strip("-")


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def obsidian_tags(fm: dict) -> list[str]:
    """Every axis of a page, as a nested tag."""
    tags: list[str] = []
    for field, namespace in TAG_FACETS.items():
        for value in _as_list(fm.get(field)):
            slug = slugify(value)
            if slug:
                tags.append(f"{namespace}/{slug}")

    source_index = fm.get("source_index")
    if isinstance(source_index, int):
        # `source/src19`, not `source/19`: a tag whose last segment is bare
        # digits is the one shape Obsidian is fussy about.
        tags.append(f"source/src{source_index}")

    # The drafts an EMT changed rather than passed — 89 of them, so this is a
    # filter that actually narrows something.
    if fm.get("corrected") is True:
        tags.append("review/corrected")

    # No `reviewer/` tag, deliberately. There is one reviewer today, so it was a
    # node tied to 361 others: a spring pulling every signed call toward the same
    # point, which is the opposite of what the layout should show. `labeled_by`
    # is still in the frontmatter, so Dataview can group by it whenever there is
    # more than one name to group.

    return sorted(dict.fromkeys(tags))


def rewrite_frontmatter(fm: dict) -> dict:
    """The source frontmatter, re-shaped for Obsidian.

    Every original field is preserved — Dataview queries the raw values, and
    losing one would make the vault less useful than the corpus. Only `tags` is
    replaced, and the link fields gain wikilink form alongside a `*_slugs` copy
    so a query can still get at the plain slug.
    """
    out = dict(fm)

    for field in LINK_FIELDS:
        slugs = [str(v) for v in _as_list(fm.get(field)) if v]
        if not slugs:
            continue
        out[f"{field}_slugs"] = slugs
        out[field] = [f"[[{s}]]" for s in slugs]

    out["tags"] = obsidian_tags(fm)

    # Link by the name a person would say, not only by the slug.
    title = fm.get("title")
    if title:
        out["aliases"] = [str(title)]

    return out


def _related_line(fm: dict) -> str:
    """Links for a page whose body has none, so it is not a graph orphan."""
    seen: list[str] = []
    for field in LINK_FIELDS:
        for slug in (str(v) for v in _as_list(fm.get(field)) if v):
            if slug not in seen:
                seen.append(slug)
    return " ".join(f"[[{s}]]" for s in seen)


def convert(path: Path) -> str:
    """One source page as its Obsidian text."""
    fm, body = read_page(path)
    out = rewrite_frontmatter(fm)

    # A page with no inline link is invisible in the graph. Its relationships
    # are already in the frontmatter, so give the body the same links rather
    # than inventing any.
    if "[[" not in body:
        related = _related_line(fm)
        if related:
            body = f"{body.rstrip()}\n\n## Related\n{related}\n"

    front = yaml.dump(out, allow_unicode=True, default_flow_style=False, sort_keys=False)
    # Same rule as `frontmatter.write_frontmatter`: the body already brings its
    # own leading newline when it came out of a file that had frontmatter, and
    # adding another opens a blank line the source did not have.
    separator = "" if body.startswith("\n") else "\n"
    return f"---\n{front}---{separator}{body}"


def export(
    source: Optional[Path] = None,
    dest: Optional[Path] = None,
    reset_graph: bool = False,
) -> dict:
    """Write the vault. Returns counts, for the caller to report."""
    source = source or wiki_dir()
    dest = dest or get_wiki_root() / "obsidian_wiki"
    dest.mkdir(parents=True, exist_ok=True)

    written = 0
    by_dir: dict[str, int] = {}
    for name in CONTENT_DIRS:
        src_dir = source / name
        if not src_dir.is_dir():
            continue
        out_dir = dest / name
        # Replace the content wholesale so a page deleted upstream disappears
        # here too — but only these directories, never `.obsidian/`.
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)

        count = 0
        for page in sorted(src_dir.rglob("*.md")):
            if page.name == "_template.md":
                continue
            target = out_dir / page.relative_to(src_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(convert(page), encoding="utf-8")
            count += 1
        by_dir[name] = count
        written += count

    dashboards = write_dashboards(dest)
    graph = write_graph_config(dest, force=reset_graph)
    write_graph_legend(dest, force=reset_graph)
    return {"written": written, "by_dir": by_dir, "dashboards": dashboards,
            "graph": graph, "dest": str(dest)}


#: Dataview notes generated into the vault. They are the reason to open it in
#: Obsidian rather than a text editor: the corpus cannot answer "what is
#: missing" from any one file, only across all of them.
DASHBOARDS = {
    "Corpus overview": """## Vetted calls per source

```dataview
TABLE length(rows) AS calls
FROM "scenarios"
WHERE status = "approved"
GROUP BY source_index
SORT source_index
```

## Library pages by type

```dataview
TABLE length(rows) AS pages
FROM "conditions" OR "procedures" OR "medications" OR "protocols"
GROUP BY type
```

## What a case is built to teach

```dataview
TABLE length(rows) AS calls
FROM "scenarios"
WHERE status = "approved"
GROUP BY kind
SORT length(rows) DESC
```
""",
    "Coverage gaps": """The questions no single file can answer.

## Conditions nothing links to

A page nothing points at is a page no call and no other page reaches.

```dataview
LIST
FROM "conditions"
WHERE length(file.inlinks) = 0
SORT file.name
```

## Sources with no vetted call

```dataview
TABLE length(rows) AS drafts
FROM "scenarios"
WHERE status != "approved"
GROUP BY source_index
SORT source_index
```

## Calls still waiting on a reviewer

```dataview
TABLE source_index, kind, status
FROM "scenarios"
WHERE status = "pending"
SORT source_index
```

## Calls with no difficulty set

These cannot be dealt by the Basic/Intermediate/Expert draw at all.

```dataview
TABLE source_index
FROM "scenarios"
WHERE status = "approved" AND !difficulty
SORT source_index
```

## Patient-care calls with no clinical links

A bedside call that names no condition, procedure or medication is unreachable
from the pages it is about — and is an orphan in the graph. A provider-safety or
documentation call having none is expected; a patient-care one is a gap.

```dataview
TABLE source_index, file.link AS call
FROM "scenarios"
WHERE status = "approved" AND kind = "patient-care"
  AND length(conditions) = 0 AND length(procedures) = 0 AND length(medications) = 0
SORT source_index
```
""",
    "Review quality": """Where the generator is weakest, according to the EMT who fixed it.

## Rejected drafts, and why

```dataview
TABLE source_index, correction_note
FROM "scenarios"
WHERE status = "rejected" AND correction_note
SORT source_index DESC
```

## Approved, but corrected on the way through

```dataview
TABLE source_index, tags AS topics, correction_note
FROM "scenarios"
WHERE corrected = true
SORT source_index DESC
```

## Correction rate by topic

A topic that is corrected often is one the corpus finds hard.

```dataview
TABLE length(rows) AS calls, length(filter(rows, (r) => r.corrected)) AS corrected
FROM "scenarios"
WHERE status = "approved"
GROUP BY tags
SORT length(rows) DESC
```
""",
    "Charts": """Needs the **Dataview** and **Obsidian Charts** community plugins,
and Dataview's **Enable JavaScript Queries** setting turned on — without that
last one the tables elsewhere render fine and every chart here stays blank.

These are drawn **dark on purpose**. The Features page puts each chart on a dark
well, on the same argument the vitals monitor makes in `styles.css`: a data
display is read, not filled in, and a measurement on cream reads as a form
field. The palette matches that well (`--screen`, `#0b0f14`), so an exported PNG
drops in with no visible seam.

Chart.js draws its text and grid in near-black by default, which is invisible on
dark. Every block below sets them explicitly — that is the whole reason these
are not the plugin's defaults.

**Each chart has its own Save PNG button underneath it.** Save, then move the
file into `frontend/public/features/` and pass `src="/features/<name>.png"` to
the matching `ChartSlot` in `frontend/src/components/Features.tsx`.

## Topic coverage across the corpus

```dataviewjs
const INK='#e8e4da', MUTE='#8fa3bd', GRID='#33415a', CLAY='#cc785c'
const counts = {}
for (const p of dv.pages('"scenarios"').where(p => p.status == "approved"))
  for (const t of (p.tags ?? [])) {
    const s = String(t)
    if (s.startsWith("topic/")) counts[s.slice(6)] = (counts[s.slice(6)] ?? 0) + 1
  }
const rows = Object.entries(counts).sort((a, b) => b[1] - a[1])
await window.renderChart({
  type: 'radar',
  data: { labels: rows.map(r => r[0]), datasets: [{
    label: 'Vetted calls', data: rows.map(r => r[1]),
    borderColor: CLAY, backgroundColor: 'rgba(204,120,92,0.22)',
    pointBackgroundColor: CLAY, borderWidth: 2,
  }]},
  options: {
    plugins: { legend: { labels: { color: INK } } },
    scales: { r: {
      grid: { color: GRID }, angleLines: { color: GRID },
      pointLabels: { color: MUTE, font: { size: 10 } },
      // Chart.js paints a white box behind radial ticks; on dark that reads as a bug.
      ticks: { color: MUTE, backdropColor: 'transparent' },
    }},
  },
}, this.container)
// The canvas is transparent, so paint the screen color in before exporting —
// otherwise the page shows through the PNG wherever the chart is not drawn.
await new Promise(r => setTimeout(r, 120))
const canvas = this.container.querySelector('canvas')
if (canvas) {
  const save = this.container.createEl('button', { text: 'Save PNG' })
  save.style.marginTop = '10px'
  save.onclick = () => {
    const out = document.createElement('canvas')
    out.width = canvas.width
    out.height = canvas.height
    const ctx = out.getContext('2d')
    ctx.fillStyle = '#0b0f14'
    ctx.fillRect(0, 0, out.width, out.height)
    ctx.drawImage(canvas, 0, 0)
    const a = document.createElement('a')
    a.download = 'topic-coverage.png'
    a.href = out.toDataURL('image/png')
    a.click()
  }
}
```

## Vetted calls per source

```dataviewjs
const INK='#e8e4da', MUTE='#8fa3bd', GRID='#33415a', CLAY='#cc785c'
const counts = {}
for (const p of dv.pages('"scenarios"').where(p => p.status == "approved" && p.source_index))
  counts[p.source_index] = (counts[p.source_index] ?? 0) + 1
const rows = Object.entries(counts).sort((a, b) => Number(a[0]) - Number(b[0]))
await window.renderChart({
  type: 'bar',
  data: { labels: rows.map(r => 'ch' + r[0]), datasets: [{
    label: 'Vetted calls', data: rows.map(r => r[1]), backgroundColor: CLAY,
  }]},
  options: {
    plugins: { legend: { labels: { color: INK } } },
    scales: {
      x: { ticks: { color: MUTE, font: { size: 9 } }, grid: { display: false } },
      y: { ticks: { color: MUTE, precision: 0 }, grid: { color: GRID }, beginAtZero: true },
    },
  },
}, this.container)
// The canvas is transparent, so paint the screen color in before exporting —
// otherwise the page shows through the PNG wherever the chart is not drawn.
await new Promise(r => setTimeout(r, 120))
const canvas = this.container.querySelector('canvas')
if (canvas) {
  const save = this.container.createEl('button', { text: 'Save PNG' })
  save.style.marginTop = '10px'
  save.onclick = () => {
    const out = document.createElement('canvas')
    out.width = canvas.width
    out.height = canvas.height
    const ctx = out.getContext('2d')
    ctx.fillStyle = '#0b0f14'
    ctx.fillRect(0, 0, out.width, out.height)
    ctx.drawImage(canvas, 0, 0)
    const a = document.createElement('a')
    a.download = 'source-coverage.png'
    a.href = out.toDataURL('image/png')
    a.click()
  }
}
```

## What a case is built to teach

```dataviewjs
const INK='#e8e4da', SCREEN='#0b0f14'
const SERIES = ['#cc785c','#5b8266','#a8621b','#7a93a8','#9c6b9e','#6b6b63','#b3382f']
const counts = {}
for (const p of dv.pages('"scenarios"').where(p => p.status == "approved"))
  counts[p.kind ?? "unspecified"] = (counts[p.kind ?? "unspecified"] ?? 0) + 1
const rows = Object.entries(counts).sort((a, b) => b[1] - a[1])
await window.renderChart({
  type: 'doughnut',
  data: { labels: rows.map(r => r[0]), datasets: [{
    data: rows.map(r => r[1]), backgroundColor: SERIES,
    borderColor: SCREEN, borderWidth: 2,
  }]},
  options: { plugins: { legend: { position: 'right', labels: { color: INK, boxWidth: 12 } } } },
}, this.container)
// The canvas is transparent, so paint the screen color in before exporting —
// otherwise the page shows through the PNG wherever the chart is not drawn.
await new Promise(r => setTimeout(r, 120))
const canvas = this.container.querySelector('canvas')
if (canvas) {
  const save = this.container.createEl('button', { text: 'Save PNG' })
  save.style.marginTop = '10px'
  save.onclick = () => {
    const out = document.createElement('canvas')
    out.width = canvas.width
    out.height = canvas.height
    const ctx = out.getContext('2d')
    ctx.fillStyle = '#0b0f14'
    ctx.fillRect(0, 0, out.width, out.height)
    ctx.drawImage(canvas, 0, 0)
    const a = document.createElement('a')
    a.download = 'case-kinds.png'
    a.href = out.toDataURL('image/png')
    a.click()
  }
}
```

One segment is over 80% of this chart. If it reads as a single ring, switch
`type` to `'bar'` and add `indexAxis: 'y'` to the options — the long tail is the
point, and a doughnut hides it.

## The whole library

```dataviewjs
const INK='#e8e4da', SCREEN='#0b0f14'
const SERIES = ['#cc785c','#5b8266','#a8621b','#7a93a8','#9c6b9e']
const counts = {}
for (const p of dv.pages()) {
  const folder = p.file.folder.split("/")[0]
  if (folder && folder !== "dashboards") counts[folder] = (counts[folder] ?? 0) + 1
}
const rows = Object.entries(counts).sort((a, b) => b[1] - a[1])
await window.renderChart({
  type: 'polarArea',
  data: { labels: rows.map(r => r[0]), datasets: [{
    data: rows.map(r => r[1]), backgroundColor: SERIES, borderColor: SCREEN, borderWidth: 2,
  }]},
  options: {
    plugins: { legend: { position: 'right', labels: { color: INK, boxWidth: 12 } } },
    scales: { r: { grid: { color: '#33415a' }, ticks: { color: '#8fa3bd', backdropColor: 'transparent' } } },
  },
}, this.container)
// The canvas is transparent, so paint the screen color in before exporting —
// otherwise the page shows through the PNG wherever the chart is not drawn.
await new Promise(r => setTimeout(r, 120))
const canvas = this.container.querySelector('canvas')
if (canvas) {
  const save = this.container.createEl('button', { text: 'Save PNG' })
  save.style.marginTop = '10px'
  save.onclick = () => {
    const out = document.createElement('canvas')
    out.width = canvas.width
    out.height = canvas.height
    const ctx = out.getContext('2d')
    ctx.fillStyle = '#0b0f14'
    ctx.fillRect(0, 0, out.width, out.height)
    ctx.drawImage(canvas, 0, 0)
    const a = document.createElement('a')
    a.download = 'library.png'
    a.href = out.toDataURL('image/png')
    a.click()
  }
}
```

If a Save PNG button does not appear, the chart itself did not render — check
the two plugin settings at the top of this note. `Cmd+Shift+4` on a Retina
screen is a fine fallback for a static figure.
""",
    "Graph": """The corpus as a network: every call wired to the topics it teaches.

Turning tags into nodes is what makes this worth looking at. Without it the
graph is 553 notes linked page-to-page; with it, each topic becomes a hub and
you can see at a glance which subjects the corpus is dense around and which hang
off the edge by a single thread.

## Settings to get the picture

Open the graph (**Cmd+G**, or the icon in the left ribbon), then the settings
gear at its top-left:

**Filters**
- **Tags: on** — this is the setting the whole view depends on
- **Orphans: on** at first. The notes sitting alone are information: a call with
  no topic and no clinical link. Turn them off once you have seen them.
- **Search box: `-path:dashboards`** — already set. These notes are tooling, not
  corpus; they link only to each other, so in the graph they are an island of
  noise beside the thing you are looking at.
- To narrow to just the call-to-topic network, add to that:
  `-path:dashboards (path:scenarios OR tag:#topic)`

**Groups** — add one per line with the + button:

| Query | Color |
|---|---|
| *(cannot be set)* | topic hubs keep Obsidian's default node color: a color group matches notes, never tag nodes |
| `path:conditions` | rose `#f65e7f` |
| `path:procedures` | green `#3ddc84` |
| `path:medications` | cyan `#22d3ee` |
| `path:scenarios` | steel `#7da9e0` — quieter than the rest, but still legible |

These are spread around the color wheel rather than drawn from the app's
palette. A graph node is a few pixels across and carries hue and almost nothing
else, so harmony loses to separation here — an earlier version used the house
clay and amber and put two of these groups one degree of hue apart.

`python -m ems.cli.obsidian export --reset-graph` writes all of this for you,
including the decimal RGB values, so there is no reason to enter them by hand.

Colors are set by clicking the swatch beside each group. Group queries match
notes; a tag *node* is matched by its own full tag, so if `tag:#topic` colors the
calls rather than the hubs, try the specific form `tag:#topic/bleeding-and-shock`
on one group to see which behavior your version has.

**Display**
- Text fade: drag left until labels appear only near the cursor
- Node size: down a little — at this count the default nodes merge
- Arrows: off. Direction is noise here; what matters is what is connected.

**Forces** — the defaults pack this corpus into a solid disc:
- Center force: **low** (~0.3)
- Repel force: **high** (~14)
- Link force: ~0.55
- Link distance: ~90

Let it settle for a few seconds before judging it.

## Reading it

- A topic hub with many threads is a subject the corpus covers deeply.
- A hub with two or three is a thin spot — cross-check it in [[Coverage gaps]].
- A call floating unattached has no topic and no clinical link. Those are listed
  under **Patient-care calls with no clinical links** in [[Coverage gaps]].
- Clusters that touch are subjects that co-occur — bleeding and shock sitting
  against trauma is the corpus agreeing with the medicine.

## Getting an image out

The graph is a live canvas and Obsidian has no export for it, so this one is a
screenshot rather than a saved file:

1. Open the graph in its own pane and make it as large as you can.
2. Let the layout settle, then scroll to frame it.
3. `Cmd+Shift+4`, then **space**, then click the pane — that captures the window
   cleanly at Retina resolution rather than a rough drag.
4. Save as `library-graph.png`, move it into `frontend/public/features/`, and
   pass `src="/features/library-graph.png"` to the matching `ChartSlot`.

Use the **local graph** on a single condition (depth 2) for a legible close-up —
the global graph is the impression, the local one is the argument.
""",
    "Start here": """This vault is **generated**. Nothing here is a source of truth.

- It is rebuilt from `wiki/` by `python -m ems.cli.obsidian export`.
- Edits made here are **lost on the next export**. Fix the real file in `wiki/`.
- It is gitignored, so it costs nothing to delete and rebuild.

## What was changed on the way in

| Source | Here | Why |
|---|---|---|
| `tags: [airway and breathing]` | `tags: [topic/airway-and-breathing]` | Obsidian tags cannot contain spaces |
| `linked_pages: [oxygen]` | `linked_pages: ["[[oxygen]]"]` | bare slugs are invisible to the graph |
| `kind`, `source_index`, `scope_level`, `status` | also nested tags | so the tag pane and graph filter by them |
| body with no links | a `## Related` line | 78 scenarios were graph orphans |

Every original field is kept, and the plain slugs survive as `<field>_slugs`,
so a Dataview query can still get at them.

## Where to go

- [[Corpus overview]] — what exists
- [[Coverage gaps]] — what is missing
- [[Review quality]] — where the generator is weakest
- [[Charts]] — the figures, drawn
- [[Graph]] — the corpus as a network, and how to capture it

Dashboards need the **Dataview** plugin; [[Charts]] also needs **Obsidian
Charts**. Both are community plugins.
""",
}


def write_dashboards(dest: Path) -> int:
    """Generated Dataview notes. Rewritten on every export."""
    out = dest / "dashboards"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, body in DASHBOARDS.items():
        (out / f"{name}.md").write_text(
            f"---\ntags:\n- dashboard\n---\n\n# {name}\n\n{body}", encoding="utf-8"
        )
    return len(DASHBOARDS)


#: Graph-view settings, keyed exactly as Obsidian writes them. The defaults pack
#: 553 notes plus their tag nodes into a solid disc where no structure shows, so
#: these spread it out and quiet the labels.
GRAPH_SETTINGS = {
    # The dashboards are tooling, not corpus. They link to each other and to
    # nothing clinical, so in the graph they are a little island of noise beside
    # the thing you are actually looking at.
    "search": "-path:dashboards",
    "showTags": True,          # the whole point: topics become hubs
    "showAttachments": False,
    "hideUnresolved": False,
    "showOrphans": True,       # a call with no topic is information
    "showArrow": False,        # direction is noise; connection is the signal
    "textFadeMultiplier": -1.4,
    # Small dots carry hue and nothing else; 0.7 made that worse.
    "nodeSizeMultiplier": 1.15,
    "lineSizeMultiplier": 0.6,
    "centerStrength": 0.28,
    "repelStrength": 14,
    # 0.55, tried and kept. 0.85 pulls clusters tight enough that the corpus
    # reads as a handful of knots rather than a network, which loses the thing
    # the picture is for.
    "linkStrength": 0.55,
    "linkDistance": 90,
}

#: Query → color. Written as the decimal integer Obsidian stores, which is the
#: part that is unreasonable to enter by hand through a color wheel.
#:
#: **Chosen for hue separation, not for house style.** The first version of this
#: used the app's own palette — clay, pale clay, amber — and at graph node sizes
#: the topic hubs and the condition pages were 1 degree of hue apart, which is
#: to say identical. A dot a few pixels across carries hue and little else, so
#: these are spread around the wheel and saturated hard: the smallest gap is now
#: 23 degrees. Orange still marks the topic hubs, which is the one tie to the
#: page that survived, and scenarios are deliberately the most muted of the six
#: because there are 368 of them and they should recede behind the structure.
#: **A color group matches notes, never tag nodes.** Established the hard way, in
#: two steps. With `tag:#topic` first it claimed all 368 notes *carrying* a topic
#: tag — every scenario — and painted them orange, leaving the scenario group
#: matching nothing. Moved last it matched nothing at all: the only notes it
#: could have taken were already claimed, and the tag nodes themselves are not
#: reachable by a `tag:` query. So the topic hubs cannot be colored, and the
#: group is dropped rather than left in as a setting that silently does nothing.
#:
#: They are still perfectly visible — they are the nodes everything converges on,
#: drawn in Obsidian's own default color. `TOPIC_NODE_COLOR` approximates it so
#: the legend describes what is actually on screen.
GRAPH_GROUPS = (
    ("path:conditions", "#f65e7f"),   # rose
    ("path:procedures", "#3ddc84"),   # green
    ("path:medications", "#22d3ee"),  # cyan — only 13, so it can be loud
    ("path:scenarios", "#7da9e0"),    # steel — quieter than the rest, but 368
                                      # notes must still be visible at dot size
)

#: Obsidian's default node color on a dark theme. Legend only: nothing sets it.
TOPIC_NODE_COLOR = "#9aa1a8"


def write_graph_config(dest: Path, force: bool = False) -> bool:
    """Tune the graph view.

    Written only when absent by default: `.obsidian/` is the user's, and
    clobbering their tuning on every export would be the kind of help nobody
    asked for. `force=True` is the deliberate opt-in — it merges over whatever
    is there, keeping any key it does not set, and leaves a `.bak` behind.

    Obsidian holds these settings in memory and writes them back when they
    change, so it must not be running with this vault open when this is forced.
    """
    config = dest / ".obsidian" / "graph.json"
    if config.exists() and not force:
        return False

    current = {}
    if config.exists():
        try:
            current = json.loads(config.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
        config.with_suffix(".json.bak").write_text(
            json.dumps(current, indent=2), encoding="utf-8"
        )

    current.update(GRAPH_SETTINGS)
    current["colorGroups"] = [
        {"query": query, "color": {"a": 1, "rgb": int(hex_color[1:], 16)}}
        for query, hex_color in GRAPH_GROUPS
    ]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return True


#: Query → the word a person would use for it, for the on-graph legend.
GROUP_LABELS = {
    "tag:#topic": "Topic hubs",
    "path:conditions": "Conditions",
    "path:procedures": "Procedures",
    "path:medications": "Medications",
    "path:scenarios": "Scenarios",
}


#: The legend reads best with the hubs first, which is the opposite of the
#: match order the graph needs.
LEGEND_ORDER = ("tag:#topic", "path:conditions", "path:procedures",
                "path:medications", "path:scenarios")

#: Legend rows that are not color groups — see TOPIC_NODE_COLOR.
LEGEND_EXTRA = {"tag:#topic": TOPIC_NODE_COLOR}


def _legend_size() -> tuple[int, int]:
    """Width and height of the legend, in CSS pixels.

    The SVG and the CSS box that holds it must agree exactly: when the box was
    sized from `GRAPH_GROUPS` and the drawing from `LEGEND_ORDER`, dropping a
    color group left the last row rendered but clipped.
    """
    return 168, 16 + len(LEGEND_ORDER) * 22


def _legend_svg() -> str:
    """The legend, drawn from the same palette that colors the graph.

    One SVG rather than styled elements because CSS gives a pseudo-element a
    single `content`, and a legend needs a colored dot per row. A background
    image can carry the whole thing, and generating it here means the legend
    cannot drift from `GRAPH_GROUPS`.
    """
    colors = {**dict(GRAPH_GROUPS), **LEGEND_EXTRA}
    rows = [(GROUP_LABELS.get(q, q), colors[q]) for q in LEGEND_ORDER]
    width, height = _legend_size()
    body = []
    for i, (label, color) in enumerate(rows):
        y = 26 + i * 22
        body.append(f'<circle cx="18" cy="{y - 5}" r="6" fill="{color}"/>')
        body.append(
            f'<text x="34" y="{y}" fill="#d8d4cc" font-size="13" '
            f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">{label}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" rx="10" fill="#12151a" '
        f'fill-opacity="0.88" stroke="#33415a"/>'
        f'{"".join(body)}</svg>'
    )


def write_graph_legend(dest: Path, force: bool = False) -> bool:
    """A color key on the graph itself, so the meaning is not behind a gear.

    Obsidian has no legend of its own — the groups are visible only in the
    graph's settings panel. This paints one into the corner of the pane as a
    CSS snippet, and enables it, so neither step needs the GUI.
    """
    snippet = dest / ".obsidian" / "snippets" / "graph-legend.css"
    if snippet.exists() and not force:
        return False

    width, height = _legend_size()
    svg = base64.b64encode(_legend_svg().encode("utf-8")).decode("ascii")
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        "/* Generated by `protocol-obsidian export --reset-graph`.\n"
        "   A legend for the graph's color groups, which Obsidian otherwise\n"
        "   shows only inside the settings panel. Edits here are overwritten;\n"
        "   the palette lives in ems/obsidian_export.py. */\n"
        '.workspace-leaf-content[data-type="graph"] .view-content,\n'
        '.workspace-leaf-content[data-type="localgraph"] .view-content { position: relative; }\n'
        '.workspace-leaf-content[data-type="graph"] .view-content::after,\n'
        '.workspace-leaf-content[data-type="localgraph"] .view-content::after {\n'
        "  content: '';\n"
        "  position: absolute;\n"
        "  left: 14px;\n"
        "  bottom: 14px;\n"
        f"  width: {width}px;\n  height: {height}px;\n"
        f'  background: url("data:image/svg+xml;base64,{svg}") no-repeat;\n'
        "  /* Never eat a click meant for the canvas underneath. */\n"
        "  pointer-events: none;\n"
        "  z-index: 10;\n"
        "}\n",
        encoding="utf-8",
    )

    # Turn it on without a trip to Appearance settings.
    appearance = dest / ".obsidian" / "appearance.json"
    current = {}
    if appearance.exists():
        try:
            current = json.loads(appearance.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    enabled = [s for s in current.get("enabledCssSnippets", []) if s != "graph-legend"]
    current["enabledCssSnippets"] = enabled + ["graph-legend"]

    # Dark, unless the reader has already chosen. Obsidian opens light by
    # default, and everything here is drawn for a dark ground: the chart blocks
    # set light text because Chart.js otherwise draws near-black and invisible,
    # and this legend is a dark panel. On the default theme a fresh vault would
    # render charts nobody can read — which is a poor first impression of a
    # vault someone else generated.
    current.setdefault("theme", "obsidian")
    appearance.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return True
