# EMS-AI-SIM

An AI-native ride-along simulator for EMTs. You run the call: the tones drop, you size up the scene, assess the patient, treat, and hand off. When the call ends, you get a graded debrief on every action, checked against a rubric written from your own training material.

**Try the live app → [ambulance.emsridealong.app](https://ambulance.emsridealong.app/)**

> This repo is the open-source infrastructure, without the reference corpus. The `wiki/` folder holds a small demo set (two calls and the pages they link to) so the app runs and the tests pass. It is not clinical guidance.

---

## About

EMS-AI-SIM helps EMTs practice decision-making on realistic tone-out scenarios, on demand, in the terminal or the browser. Each call covers the full arc: dispatch, size-up, primary and secondary assessment, interventions, transport, and a debrief. The debrief covers the size-up checklist, each correct action, the scenario's rationale, and any red flags you missed.

Every scenario is grounded in source material you bring. You load your own resources (manuals, protocols, SOPs), and each one gets an index. Wiki pages and scenarios cite them as `[SRC-<index>:p<page>]`, or `[SOP-ID:Section]` for SOPs. Claude (CLI or API) drafts pages and practice calls from that material. Nothing reaches the practice pool until a certified EMT approves it.

Two design choices set it apart:

1. **An LLM Wiki underneath, built to keep hallucination out of medical content.** The infrastructure is inspired by Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) idea. Instead of retrieving from raw documents on every request, the source material is compiled once into a persistent, cross-linked markdown wiki that grows with every source you ingest. The model never answers or grades from memory. Every clinical claim must carry a citation back to a page of your material, and citations that aren't in the retrieved context are flagged or stripped. Answers the wiki can't support come back as `NOT IN PROVIDED PROTOCOLS` rather than a guess.
2. **A closed loop learning process that keeps EMTs in control of the model.** The AI drafts but never decides. Generated calls sit in quarantine until a certified EMT approves, corrects, or rejects them, and only approved, signed-off scenarios reach the practice pool. Every rejection is distilled into `system/generation-lessons.md`, which feeds every later draft. The generator improves from human judgment, and the human stays the final authority on what trainees learn.

**See the whole knowledge base in Obsidian.** The `/export-obsidian` skill turns the wiki into a ready-to-open [Obsidian](https://obsidian.md/) vault of fully connected notes. Every call, condition, procedure, and medication is wikilinked to the pages it relates to. Tags are nested by topic, kind, source, scope, and review status, so one click filters the graph along any of those axes. The export includes custom Dataview dashboards (corpus overview, coverage gaps, review quality, and charts) and a tuned graph view with color groups, so you can see where the corpus is dense, where it is thin, and where reviewers had to step in. The export is deterministic and needs no API key. It is one-way: `wiki/` stays the source of truth, and the vault is regenerated whenever the corpus changes.

Without an API key the whole call plays deterministically. Add an Anthropic key to have Claude voice the dispatcher, scene, and patient, and write a narrative debrief.

---

## What's inside

| Layer | Tech |
|---|---|
| Frontend | React 19 + TypeScript + Vite |
| Voice | Browser Web Speech API (server-side STT/TTS endpoints are stubbed for later) |
| HTTP backend | FastAPI + uvicorn on `127.0.0.1:8000` (Vite proxies `/api`) |
| Simulator engine | `ems/sim/`: scene, session, intent classifier, grader, hints, vitals, personas, debrief |
| Practice history | SQLite (`var/ems.db`, or `EMS_DB_PATH`) |
| Corpus | Markdown wiki with YAML frontmatter, enforced by [`SCHEMA.md`](SCHEMA.md) |
| Authoring | Claude Code skills + `protocol-*` CLIs; Apple Vision OCR, PDF and TXT extraction; optional local embeddings |

Two ways to play:
- **Terminal**: `protocol-practice`, text only, no API key needed.
- **Browser**: the full ride-along UI with a vitals monitor, voice input, history, and user accounts.

---

## Prerequisites

- **Python 3.10+** (CI runs 3.12)
- **Node.js 22+** for the frontend
- **macOS** only if you OCR scanned page images (Apple Vision via `ocrmac`); PDF and TXT work anywhere
- **Claude Code** if you build a corpus with the skills
- A modern browser with microphone permission (Chrome/Edge recommended for Web Speech)

---

## API keys you'll need

All keys stay on the server. The browser never sees them.

| Service | What it does | Required? |
|---|---|---|
| **Anthropic** | Live personas, narrative debrief, and the API-based authoring CLIs (`protocol-ingest`, `protocol-scenarios`, `protocol-query`) | Optional: the simulator and the Claude Code skills run without it |
| **AirNow** | Live air-quality flavor for scene conditions (`EMS_LIVE_ENV=1`) | Optional, off by default |

---

## Setup

### 1. Backend

```bash
git clone https://github.com/rachelyangg6-cloud/EMS-AI-SIM.git
cd EMS-AI-SIM
pip install -e ".[web,dev]"
```

Add extras as needed: `extraction` (OCR for scanned page images; PDF and TXT need no extra) and `embeddings` (local vector search, pulls PyTorch).

### 2. Frontend

```bash
cd frontend && npm install
```

### 3. Configure secrets (optional)

```bash
cp .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-...
# EMS_PERSONA_MODEL=claude-sonnet-5
# EMS_GRADER_MODEL=claude-opus-5
```

### 4. Create an account

```bash
protocol-users add --corp westchester-vac --name "Jane Roe" \
                   --email jane@example.org --years 3 --status apprentice
```

There is no self-service sign-up. `apprentice` trainees can practice; `certified` EMTs can also approve generated calls (`protocol-users promote <username>`).

---

## Run

### Browser (two terminals)

```bash
# Terminal 1 — API
python -m ems.cli.serve
# Listens on http://127.0.0.1:8000 (must be this port)

# Terminal 2 — frontend
cd frontend && npm run dev
# Vite serves http://localhost:5173
```

### Terminal

```bash
python -m ems.cli.practice                        # a vetted call at intermediate
python -m ems.cli.practice --level basic          # hints on by default here
python -m ems.cli.practice --scenario src1-s01    # a specific case
python -m ems.cli.practice --personas             # live voices (needs a key)
```

To finish, say `end of call` (or `end scene`, `stop`, or an empty line).

| Flag | What it does |
|---|---|
| `--hints` / `--no-hints` | Next-step nudge each turn (on by default at `--level basic`) |
| `--generated` | Deal an unreviewed draft instead of a vetted case |
| `--include-generated` | Draw from both pools (opt-in, never the default) |
| `--review` | Approve or reject a generated draft after the debrief |
| `--personas` | Voice the dispatcher, scene and patient with Claude |
| `--seed N` | Repeat the same call |
| `--season` `--aqi` `--flu` | Force the conditions selection reacts to |

---

## Building your own corpus

Use only material you're licensed to use. Keep each resource in a resources folder under its index `N`, in any of three forms:

| Form | How it's read | Page markers |
|---|---|---|
| `source_N/` folder of page PNGs | OCR with Apple Vision (macOS, `extraction` extra) | From file names: `1.png`, `1_1.png` → `[p.1]` |
| `source_N.pdf` | Text extraction with pdfminer, any OS | One per PDF page. Scanned PDFs with no text layer are refused; export their pages as PNGs instead |
| `source_N.txt` | Read as UTF-8, any OS | Pages split on form feeds; a file without them is `[p.1]` |

`protocol-add-resource` (or `/ingest-source`) writes each one to `raw/source-N.md` with `[p.NN]` markers, which become `[SRC-N:pNN]` citations. SOPs go through `protocol-add-source`, which reads PDF or text. `raw/` is gitignored (see [`raw/README.md`](raw/README.md)).

### Claude Code skills

The agent reads the material and does the reasoning. Deterministic `ems` helpers save the results, so skills need no API key. Most skills take a source index `N`.

| Skill | Purpose |
|---|---|
| **`/ingest-source <N>`** | Extract a source (page PNGs, PDF or TXT) and write the condition/procedure pages it supports, citing `[SRC-N:pNN]` |
| **`/generate-scenarios <N>`** | Author 10 grounded, cited training scenarios for a source, saved as `pending` |
| **`/label-scenarios [<N>]`** | Review pending scenarios: approve, edit, reject, or author new ones |
| **`/scenarios <N>`** | `generate-scenarios` → `label-scenarios` |
| **`/process-source <N>`** | `ingest-source` → `generate-scenarios` → `label-scenarios` |
| **`/generate-case <slug>`** | Draft a new call grounded in the wiki, gated by the playability checks |
| **`/build-embeddings`** / **`/build-graph`** | Build the local vector index and knowledge graph |
| **`/query <question>`** | Cited, scope-aware answer from the wiki |
| **`/export-obsidian`** | Export the wiki as an Obsidian vault |

Generated drafts are quarantined in `wiki/scenarios/generated/` until a certified EMT approves them. Rejections are written to `system/generation-lessons.md`, which every later draft reads.

---

## Useful scripts

```bash
protocol-add-resource <dir> --sources 1-4   # source_<N>/ PNGs (OCR), source_<N>.pdf or .txt → raw notes
protocol-add-source <file>                  # extract an SOP document (PDF or text) into a raw note
protocol-ingest                             # summarize, route, and update wiki pages (Claude API)
protocol-scenarios --sources 1-4            # generate scenarios per source (Claude API)
protocol-generate / protocol-review         # draft a call, then approve or reject it
protocol-embed / protocol-graph / protocol-query   # retrieval
protocol-rubric-check                       # rubric lines the grader can't classify
protocol-context-check                      # scenarios that give the trainee nothing to work with
protocol-difficulty --backfill              # derive basic/intermediate/expert per scenario
protocol-transcript                         # export a practice call for review

python -m pytest -q                         # offline test suite (the LLM is mocked)
cd frontend && npm run build                # tsc + vite build
cd frontend && npm run lint                 # oxlint
```

---

## Project layout

```
ems/              core: OCR + PDF/TXT extraction, ingest, scenarios, page updater, retrieval
ems/sim/          simulator: scene, session, intents, grader, hints, vitals, personas, debrief
ems/web/          FastAPI server
ems/cli/          protocol-* CLI entry points
frontend/         React + Vite client
.claude/skills/   Claude Code authoring skills
wiki/             demo pages and scenarios (replace with your own corpus)
raw/              your source material (gitignored)
system/           vocabulary, call patterns, vital profiles, generation lessons
tests/            offline test suite
SCHEMA.md         enforceable page and scenario schema
PROTOCOLS.md      section templates and naming conventions
```

---

## Model routing

| Call | Model | Why |
|---|---|---|
| Dispatcher / scene / patient personas | Sonnet 5 (`EMS_PERSONA_MODEL`) | They talk a lot and say little that is hard |
| Narrative debrief | **Opus 5** (`EMS_GRADER_MODEL`) | Clinical reasoning, precision matters |
| API-based authoring CLIs | Opus 4.8 (`ANTHROPIC_MODEL`) | Grounded drafting from source text |

Defaults live in `ems/config.py`. The rule-based grader and intent classifier run without any model.

---

## Notes

- **Citations are verified.** An answer or draft that cites something not in its retrieved context is flagged, and invented citations are stripped from generated calls.
- **Scope-aware.** Interventions above the trainee's certification are tagged (`[Paramedic only]`, `[OUT OF SCOPE for EMT-B]`).
- **Out of scope:** clinical accuracy claims. The demo corpus is illustrative, and anything you build is only as good as its sources and its reviewers.

---

## License

[GNU Affero General Public License v3.0](LICENSE). If you run a modified version as a network service, you must offer its users the source.
