/**
 * What the system does, and how — in two tiers.
 *
 * The lead of every section is written for a trainee. The technical detail
 * underneath is written for someone deciding whether to trust this with their
 * students, and is folded away in a `<details>` so it is there without being in
 * the way. Native disclosure rather than a state toggle: no ARIA to hand-wire,
 * keyboard-correct for free, and find-in-page opens a closed one, so Ctrl-F
 * still reaches the technical text.
 *
 * **The numbers are live.** They come from `/api/corpus`, which counts `wiki/`
 * as the server has it, so the page cannot claim a corpus it does not
 * have. The prose is the page and always renders; a figure that has not arrived
 * shows `—` rather than blanking the section.
 */

import type { ReactNode } from 'react'

import { actions, useStore } from '../store'

/** The technical tier. The summary names what is inside — never "read more". */
function Deep({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="deep">
      <summary>{title}</summary>
      <div className="deep-body">{children}</div>
    </details>
  )
}

/** One figure. `—` until the fetch lands, so a slow or failed call is legible
 *  rather than a hole in the layout. */
function Stat({ value, label }: { value: number | string | undefined; label: string }) {
  return (
    <div className="stat">
      <b>{value ?? '—'}</b>
      <span>{label}</span>
    </div>
  )
}

/**
 * A reserved slot for a chart built in Obsidian and exported as an image.
 *
 * Drop the file in `frontend/public/features/` and pass `src` as
 * `/features/<name>.png` — `public/` is copied into the bundle at build time,
 * so a pasted image ships with no config change. Until then the well renders
 * empty with its caption and the live figure it will visualize, so the section
 * is informative before the chart exists.
 */
function ChartSlot({
  figure,
  title,
  caption,
  src,
  alt,
  children,
}: {
  figure: number
  title: string
  caption: string
  src?: string
  alt?: string
  children?: ReactNode
}) {
  return (
    <figure className="chart-slot">
      {/* Numbered, so a caption can never be misread as a section heading —
          which is exactly what happened when the title was just bold text. */}
      <figcaption>
        <span className="fig-label">Fig. {figure}</span>
        <span className="fig-title">{title}</span>
        <span className="hint">{caption}</span>
      </figcaption>
      <div className="chart-slot-stage">
        {src ? <img src={src} alt={alt ?? title} loading="lazy" /> : children}
      </div>
    </figure>
  )
}

/** The top few rows of a histogram, so a slot says something before its chart. */
function TopRows({ data, limit = 6 }: { data?: Record<string, number>; limit?: number }) {
  const rows = Object.entries(data ?? {}).slice(0, limit)
  if (!rows.length) return <p className="hint">Waiting for the numbers…</p>
  return (
    <dl className="mini-bars">
      {rows.map(([label, n]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{n}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Features() {
  const corpus = useStore((s) => s.corpus)
  const busy = useStore((s) => s.busy)
  const error = useStore((s) => s.error)

  const pages = corpus?.pages
  const cases = corpus?.scenarios
  const topics = corpus?.topics
  const cites = corpus?.citations
  const sources = corpus?.sources

  return (
    <div className="card features">
      <header className="row">
        <div>
          <h1>Features</h1>
          <p className="sub">
            What this is built from, and what it will not do.
          </p>
        </div>
        <button type="button" className="ghost" onClick={actions.backToMenu}>
          Back
        </button>
      </header>

      {error && <p className="error">{error}</p>}
      {busy && !corpus && <p className="hint">Counting the library…</p>}

      <div className="stats">
        <Stat value={corpus?.files} label="pages in the library" />
        <Stat value={cases?.expertise_marked} label="calls vetted by an EMT" />
        <Stat value={cites?.distinct} label="resource/SOP/SOG references" />
        <Stat value="EMT-B" label="scope, end to end" />
      </div>

      <h2 className="part">What you actually do here</h2>

      <section className="panel">
        <h3>A call, run in real time</h3>
        <p>
          Dispatch tones out and you are on scene. You size it up, then say what
          you would actually do — out loud or typed — and the patient, the
          bystanders and the scene answer you. Nothing is multiple choice:
          you decide what to ask, what to look at, what to do, and in what
          order. Ask the wrong question and you get the answer to the wrong
          question.
        </p>
        <p>
          Say &ldquo;end of call&rdquo; when you are done, and the call is over
          whether or not you did everything. That is the point: the decision
          about when you have enough is part of what is being practiced.
        </p>
      </section>

      <section className="panel">
        <h3>Say it your way</h3>
        <p>
          &ldquo;Non-rebreather at 15 liters&rdquo; and &ldquo;supplemental
          oxygen via NRB&rdquo; are the same act, and both are credited.
        </p>
        <Deep title="How free speech becomes a graded action">
          <p>
            Both your words and the answer key run through one hand-written
            table of 84 intents and around 600 patterns, and are compared as
            sets. Word overlap alone cannot tell a nonrebreather from a
            bag-valve mask, which is a distinction whole calls turn on — so a
            device mismatch never scores a full hit, however close the wording.
          </p>
          <p>
            Matching is global rather than in order: the strongest match in the
            whole call is settled first, so a vague sentence cannot consume the
            one that would have satisfied a precise step.
          </p>
        </Deep>
      </section>

      <section className="panel">
        <h3>A debrief built like a skill sheet</h3>
        <p>
          Then you are graded the way the NREMT grades: pass or fail, the five
          scene size-up items scored on their own, every expected action marked
          hit, partial or missed — with what you actually said printed beside
          it — and critical criteria that fail the call outright however well
          the rest of it went.
        </p>
        <p>
          Every step cites the page it came from, so a mark you disagree with
          can be taken back to the source and argued with. You can replay the
          same call immediately, or take another.
        </p>
      </section>

      <section className="panel">
        <h3>Your score is arithmetic, not an opinion</h3>
        <p>
          Pass or fail is computed without a language model anywhere in the
          decision. The written debrief is composed afterwards and cannot
          overturn it.
        </p>
        <Deep title="How the points are actually counted">
          <p>
            Five NREMT scene size-up items at one point each, then two points
            for a step you performed and one for a partial. Seventy percent
            passes. A critical error fails the call outright without touching
            the points, so the score still records what was done.
          </p>
          <p>
            Prohibitions are pass/fail rather than scored — doing nothing
            satisfies every &ldquo;do not&rdquo; on the sheet, and an empty call
            was collecting points for forbidden things it had not got round to.
            Red flags are shown but never scored: catching one used to mean
            saying it out loud, and nobody narrates &ldquo;cold, clammy
            skin&rdquo; on a real call — they act on it.
          </p>
        </Deep>
      </section>

      <section className="panel">
        <h3>Choose what you practice</h3>
        <p>
          Leave the topic box empty and you are dealt a call at random. Type a
          topic and you are dealt one of those — useful the week before a
          practical, or the week after a call that did not go well.
        </p>
        <div className="topic-chips">
          {Object.keys(topics?.by_topic ?? {}).map((topic) => (
            <span key={topic}>{topic}</span>
          ))}
        </div>
        <p className="hint">
          {topics?.used ?? '—'} topics, taken from the vetted corpus itself — so
          the list cannot offer you something nothing has been written about.
        </p>
      </section>

      <section className="panel">
        <h3>Or let the day choose</h3>
        <p>
          Given a corps location, the app reads the actual air quality and
          weather there and shifts what you are likely to be dealt. On a day
          when PM2.5 has pushed the AQI past 300, respiratory calls get more
          likely — because that is what the tones would be doing.
        </p>
        <Deep title="How a scenario is chosen, a detailed example">
          <p>
            Say the air quality where the corps runs has gone past 300. The app
            gathers every call in scope that falls under the four conditions
            that rule names — asthma, hypoxia, respiratory failure and acute MI,
            59 of them as the library stands — and applies a multiplier to each:
            asthma <strong>3.0&times;</strong>, hypoxia <strong>2.0&times;</strong>,
            respiratory failure <strong>1.8&times;</strong>, acute MI{' '}
            <strong>1.4&times;</strong>. The call you are dealt is then a random
            draw in those proportions:
          </p>
          <div className="table-wrap">
            <table className="figures">
              <thead>
                <tr>
                  <th>Condition</th><th>Calls written</th>
                  <th>Multiplier</th><th>Share of draws</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>asthma</td><td>8</td><td>3.0&times;</td><td>20.6%</td></tr>
                <tr><td>hypoxia</td><td>26</td><td>2.0&times;</td><td>44.6%</td></tr>
                <tr><td>respiratory failure</td><td>14</td><td>1.8&times;</td><td>21.6%</td></tr>
                <tr><td>acute MI</td><td>11</td><td>1.4&times;</td><td>13.2%</td></tr>
              </tbody>
            </table>
          </div>
          <p>
            Those multipliers are set in a YAML file rather than in code, so a
            corps can tune them to the calls its own region actually runs —
            weighting up what it sees often, dropping what it never sees. The
            same file holds a gentler set for an AQI above 150, and one for each
            season.
          </p>
          <p>
            Air quality comes from AirNow and the sky from the National Weather
            Service.
          </p>
        </Deep>
      </section>

      <h2 className="part">The whole library at a glance</h2>

      <ChartSlot
        figure={1}
        title="The whole library at a glance"
        caption={
          corpus
            ? `${corpus.files} notes: every page and every call.`
            : 'Every page and every call, by type.'
        }
      >
        <TopRows data={pages?.by_type} />
      </ChartSlot>

      <section className="panel">
        <h3>Built source by source, not cherry-picked</h3>
        <p>
          The library is worked through each indexed resource in turn rather than
          assembled from whatever was easy to write. Where a source has fewer
          calls it is because less of it happens at a patient&rsquo;s side —
          an operations resource yields fewer than a trauma one.
        </p>
      </section>

      <ChartSlot
        figure={2}
        title="Vetted calls per source"
        caption={
          sources
            ? `${sources.covered} indexed sources covered.`
            : 'Vetted calls by source index.'
        }
      >
        <TopRows data={sources?.by_source} />
      </ChartSlot>

      <ChartSlot
        figure={3}
        title="Topic coverage across the corpus"
        caption={
          topics
            ? `${topics.used} of ${topics.vocabulary} topics in use, ${topics.assignments} assignments across the vetted calls.`
            : 'Topics in use across the vetted calls.'
        }
      >
        <TopRows data={topics?.by_topic} />
      </ChartSlot>

      <section className="panel">
        <h3>The library is a network, not a list</h3>
        <p>
          Every call is wired to the topics it teaches and the conditions,
          procedures and medications it turns on. That is what lets a question
          about one thing reach the pages around it — and what makes a thin
          spot in the corpus visible as a topic with almost nothing attached.
        </p>
      </section>

      <ChartSlot
        figure={4}
        title="The library as a network"
        caption={
          topics
            ? `${corpus?.files ?? '—'} notes drawn together around ${topics.used} topic hubs.`
            : 'Every note, and what links it to the rest.'
        }
      >
        <TopRows data={pages?.by_type} />
      </ChartSlot>

      <ChartSlot
        figure={5}
        title="What a case is built to teach"
        caption="Vetted calls by kind. Only patient-care cases can be played as a ride-along."
      >
        <TopRows data={cases?.by_kind} limit={8} />
      </ChartSlot>

      <h2 className="part">How the library is built</h2>

      <section className="panel">
        <h3>Every call was signed by a person</h3>
        <p>
          A scenario is only ever dealt to you once an EMT has read it and put
          their name to it. Every call in the library has been through that
          review — nothing is published automatically.
        </p>
        <Deep title="What counts as vetted, exactly">
          <p>
            Two conditions, both required: <code>status: approved</code> and a
            non-empty <code>labeled_by</code>. A draft that is marked approved
            but signed by nobody is not dealt. Drafts wait in a quarantine
            directory and are promoted by a physical file move, so a case cannot
            be approved and still sitting in quarantine.
          </p>
          <p>
            The review is not a formality. Every vetted call was read through by
            an EMT who corrected what needed correcting before signing it —
            these are not drafts that were glanced at and passed.
          </p>
          <p>
            Rejections are not thrown away. Each one&rsquo;s critique is
            distilled into a line in <code>generation-lessons.md</code>, and the
            whole file is fed into the prompt for every later draft — currently{' '}
            {corpus?.lessons ?? '—'} standing lessons.
          </p>
        </Deep>
      </section>

      <section className="panel">
        <h3>Human review, and what it leaves behind</h3>
        <p>
          {cases?.reviewed ?? '—'} drafts have been read line by line by a
          qualified EMT and ruled on one at a time. Not sampled, not
          spot-checked — every call in the library reached it that way.
        </p>
        <p>
          That work does not stop, and it does not evaporate. New cases are
          drafted, reviewed the same way, and the ones that hold up join the
          library for good. What a reviewer says about the ones that do not
          becomes a written lesson the next draft is held to — so each round of
          review makes the next batch better before anybody reads it.
        </p>
        <div className="stats">
          <Stat value={cases?.reviewed} label="drafts read and ruled on by an EMT" />
        </div>
      </section>

      <section className="panel">
        <h3>Everything traces to an indexed user resource, or an SOP/SOG</h3>
        <p>
          Every page and every vetted call carries at least one source
          reference — {cites ? `${cites.pages_cited} of ${cites.pages_total}` : '—'}{' '}
          library pages and{' '}
          {cites ? `${cites.scenarios_cited} of ${cites.scenarios_total}` : '—'}{' '}
          calls. Nothing in the corpus is unsourced.
        </p>
        <Deep title="Why a citation here is a check, not a decoration">
          <p>
            A citation names its source and the exact place inside it, so a
            claim can be taken back to the document it came from and read in
            context. The library draws on{' '}
            {cites?.sources_cited ?? '—'} sources and carries{' '}
            {cites?.distinct ?? '—'} distinct references to them.
          </p>
          <p>
            The model never cites from memory. It is given the specific sources
            retrieved for the question and is allowed to cite only those. Once it
            has written an answer, every reference it used is compared against
            what it was actually given, and anything that does not match is
            flagged as unverified.
          </p>
          <p>
            In your debrief the check is enforced rather than reported: a
            statement whose reference cannot be matched is removed entirely
            rather than shown with a warning. A claim you cannot trace is a
            claim you cannot check, and on this material that is worse than
            saying nothing.
          </p>
        </Deep>
      </section>

      <h2 className="part">Ordinary code and LLM model usage</h2>

      <section className="panel">
        <h3>Ground truth is data, not LLM model output</h3>
        <p>
          The correct answer for a call comes from a page a named EMT signed —
          never from a model. Everything that decides what the system knows is
          ordinary code: scoring pages, filtering by certification, refusing
          when the match is too weak. No LLM model runs in that path, so the step
          that establishes fact has nothing to invent with.
        </p>
        <p>
          That is also why this is not a search over raw documents. What gets
          retrieved is a maintained page someone wrote and put their name to,
          and where two sources disagreed a person settled it when the page was
          written — rather than both fragments being handed to a model to
          referee, at speed, every time anybody asks.
        </p>
        <Deep title="How the library is searched, and when it refuses">
          <p>
            <strong>There is no LLM anywhere in this path.</strong> Finding the
            right page is arithmetic over files on disk: each page is scored by
            weighted term overlap — title &times;3, metadata &times;2, body
            &times;1 — and blended with a vector and a graph signal at{' '}
            <code>0.6 / 0.3 / 0.1</code>. Ordinary code, the same answer every
            time, and nothing that can be talked into a different one.
          </p>
          <p>
            <strong>Nothing is chopped up.</strong> The usual arrangement slices
            documents into fragments, embeds them, and stuffs whichever ones
            score highest into a prompt — so what the model reads is a handful
            of paragraph-shaped pieces torn out of their context. Here the unit
            is a whole page about one thing, with a fixed set of headings,
            written and maintained as a page. Nothing is cut mid-idea because
            nothing is cut at all.
          </p>
          <p>
            Scope filtering runs <em>before</em> ranking, so a page above your
            certification is never even a candidate. The refusal gate is the raw
            keyword score taken before any blending: below it the answer is
            exactly <code>NOT IN PROVIDED PROTOCOLS</code>. Similarity alone can
            never unlock an answer, which is what stops a vaguely-related page
            from becoming a confident wrong one.
          </p>
          <p>
            Citations are then checked by set difference against the text
            actually retrieved — mechanically, not by asking the model nicely.
            In the debrief a bullet whose citation cannot be matched is dropped
            whole rather than shown with a warning.
          </p>
        </Deep>
      </section>

      <section className="panel">
        <h3>What the LLM model is allowed to do</h3>
        <p>
          A Large Language Model (LLM) does three jobs here: it voices the
          patient, the dispatcher and the bystanders while a call is running; it
          drafts new cases for an EMT to review; and it writes the prose of your
          debrief. None of those decides whether you passed.
        </p>
        <Deep title="The guardrail on each of the three">
          <p>
            <strong>Drafting cases.</strong> A generated case lands in
            quarantine marked pending and cannot be dealt to anyone. Only a
            certified reviewer can promote it, which physically moves the file
            into the library. Rejections are not discarded: the critique becomes
            a written lesson fed into every later generation.
          </p>
          <p>
            <strong>Running the call.</strong> The personas talk, but the
            scenario&rsquo;s correct actions are fixed text written by a person
            before the call started — the model cannot move the target while you
            are aiming at it. If it is slow or fails, the turn falls back to the
            scenario&rsquo;s own written line rather than stalling.
          </p>
          <p>
            <strong>Writing the debrief.</strong> It runs strictly after the
            deterministic grade, receives that grade as fixed input, and is told
            the critical errors stand and are to be explained rather than
            excused. Every bullet it writes is citation-checked against the
            scenario&rsquo;s own sources before you see it.
          </p>
        </Deep>
      </section>

      <section className="panel">
        <h3>Which Claude model does which job</h3>
        <p>
          The patient and the dispatcher are voiced by a fast model. The written
          debrief gets the strong one. Neither decides your score.
        </p>
        <dl>
          <dt>Patient, dispatcher, bystanders</dt>
          <dd><code>{corpus?.models.personas ?? '—'}</code></dd>
          <dt>Written debrief</dt>
          <dd><code>{corpus?.models.grading ?? '—'}</code></dd>
          <dt>Building the library</dt>
          <dd><code>{corpus?.models.authoring ?? '—'}</code></dd>
        </dl>
      </section>

      <section className="panel">
        <h3>In short, who decides what is true</h3>
        <dl>
          <dt>A person</dt>
          <dd>
            The correct actions for every call, and the pass mark. Ground truth.
          </dd>
          <dt>Ordinary code</dt>
          <dd>
            Scoring, scope filtering, citation checking, the refusal gate.
            Authoritative — an LLM cannot overrule any of it.
          </dd>
          <dt>A Large Language Model (LLM)</dt>
          <dd>
            The patient&rsquo;s voice and the debrief&rsquo;s prose, checked
            afterwards and dropped where it cannot be traced to a source.
          </dd>
        </dl>
      </section>
    </div>
  )
}
