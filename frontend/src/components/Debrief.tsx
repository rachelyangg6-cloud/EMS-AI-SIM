import { useState } from 'react'

import { actions, useStore } from '../store'
import type { Grade } from '../types'

const SIZE_UP_LABEL: Record<string, string> = {
  'scene-safety': 'Scene safety',
  bsi: 'BSI / PPE',
  'patient-count': 'Number of patients',
  'moi-noi': 'Mechanism / nature of illness',
  'additional-resources': 'Additional resources',
}

const MARK: Record<string, string> = { hit: '✓', partial: '~', missed: '✗' }

const STATUS_LABEL: Record<string, string> = {
  hit: 'You did this',
  partial: 'Partly',
  missed: 'You missed this',
}

/** Citations are `[SRC-22:p660]`; pull them out so the step reads as prose. */
const CITE_RE = /\[[A-Z0-9-]+:[^\]]+\]/g

function splitCitations(action: string): { text: string; cites: string[] } {
  const cites = action.match(CITE_RE) ?? []
  return { text: action.replace(CITE_RE, '').replace(/\s{2,}/g, ' ').trim(), cites }
}

/** A verdict on the *scenario*, kept well away from the score for the trainee.
 *
 *  Somebody who has just scored 45 is being asked whether the case that beat
 *  them was any good. Those are different judgements and the copy has to say so,
 *  or the rating measures how the call went instead of how real it was.
 */
function ReviewPanel() {
  const reviewed = useStore((s) => s.reviewed)
  const busy = useStore((s) => s.busy)
  const [comment, setComment] = useState('')
  const [realism, setRealism] = useState(4)

  if (reviewed) {
    return (
      <section className="panel panel--review">
        <h2>Your verdict</h2>
        <p>
          {reviewed.decision === 'approve'
            ? `Approved. ${reviewed.scenario_id} is in the shared library and can be dealt from the next call.`
            : reviewed.decision === 'reject'
              ? `Rejected. ${reviewed.scenario_id} stays out of the library, and your comment goes to the next draft.`
              : `Set aside. ${reviewed.scenario_id} is still unjudged and will come back after the drafts you have not seen.`}
        </p>
        {/* Say what is actually there rather than implying a queue. With none
            left, the honest next step is the command that makes more. */}
        {reviewed.decision === 'skip' && (
          <p className="hint">
            {reviewed.drafts_remaining
              ? `${reviewed.drafts_remaining} other draft${reviewed.drafts_remaining === 1 ? '' : 's'} waiting — start another call in generated mode.`
              : 'No other drafts are waiting. Run /generate-case <condition> to write more.'}
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="panel panel--review">
      <h2>Was this a realistic call?</h2>
      <p className="aside">
        This is about the scenario, not your score. Approving puts it in the
        shared library; rejecting keeps it out and sends your comment back to
        whoever writes the next one.
      </p>

      <label>
        How realistic, 1–5
        <input
          type="range"
          min={1}
          max={5}
          value={realism}
          onChange={(e) => setRealism(Number(e.target.value))}
        />
        <span className="realism-value">{realism}</span>
      </label>

      <label>
        What was wrong with it, or what worked
        <textarea
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="A 58-year-old with this history would already be on home oxygen…"
        />
      </label>

      <div className="review-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => void actions.review('approve', comment, realism)}
        >
          Approve into the library
        </button>
        <button
          type="button"
          className="ghost"
          /* A rejection with no comment is refused by the server, and it would
             teach the generator nothing anyway. */
          disabled={busy || !comment.trim()}
          onClick={() => void actions.review('reject', comment, realism)}
        >
          Reject
        </button>
        {/* Not a third verdict — a way of not giving one yet. Anything already
            typed is kept, because the reason for hesitating is exactly what
            gets forgotten before the draft comes round again. */}
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={() => void actions.review('skip', comment, realism)}
        >
          Skip for now
        </button>
      </div>
      {!comment.trim() && (
        <p className="hint">A rejection needs a comment — it is the only thing it produces.</p>
      )}
    </section>
  )
}

/**
 * The written debrief, wrapped around a score it did not decide.
 *
 * Rendered above the checklists because it is the part a trainee actually
 * reads. Anything it could not support with one of the scenario's own citations
 * has already been dropped server-side; `stripped` is shown rather than hidden,
 * because "the model tried to cite something that isn't there" is exactly the
 * thing a reviewer needs to see.
 */
function NarrativePanel({ narrative }: { narrative: NonNullable<Grade['narrative']> }) {
  const lists: [string, string[]][] = [
    ['What went well', narrative.pros],
    ['What did not', narrative.cons],
    ['Do this differently', narrative.improvements],
  ]

  return (
    <section className="panel panel--narrative">
      <h2>Your debrief</h2>
      {narrative.summary && <p className="debrief-summary">{narrative.summary}</p>}
      {lists.map(([heading, items]) =>
        items.length > 0 ? (
          <div key={heading}>
            <h3>{heading}</h3>
            <ul>
              {items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      {narrative.stripped.length > 0 && (
        <p className="hint">
          {narrative.stripped.length} point
          {narrative.stripped.length === 1 ? ' was' : 's were'} left out for
          citing a source this scenario does not have.
        </p>
      )}
    </section>
  )
}

export function Debrief() {
  const grade = useStore((s) => s.grade)
  const scenarioId = useStore((s) => s.scenarioId)
  const mode = useStore((s) => s.mode)
  const user = useStore((s) => s.user)
  if (!grade) return null

  // Client-side only for the look of the thing — the server decides. Rendering
  // a button that is going to 403 is worse than not offering it.
  const mayReview = mode === 'generated' && user?.training_status === 'certified'

  const missed = grade.actions.filter((a) => a.status !== 'hit')

  return (
    <article className="debrief">
      <header className="debrief-head">
        <div>
          <p className="eyebrow">Debrief · {scenarioId}</p>
          {/* The verdict leads, and the points sit under it. A critical error
              fails the call outright, so a number alone could otherwise say
              "25 of 27" about a call that killed the patient. */}
          <h1 className={grade.passed ? 'verdict verdict--pass' : 'verdict verdict--fail'}>
            {grade.passed ? 'Pass' : 'Fail'}
            <span>{grade.points} / {grade.points_possible} points</span>
          </h1>
        </div>
        <div className="debrief-actions">
          {/* The same case again, from the tone-out. Sitting next to the score
              because the moment you want it is the moment you read the score. */}
          <button type="button" className="ghost" onClick={() => void actions.replayCall()}>
            Replay this call
          </button>
          <button type="button" onClick={actions.newCall}>
            Run another call
          </button>
        </div>
      </header>

      {/* Before any checklist. A bare number teaches nothing. */}
      {grade.summary && <p className="debrief-summary">{grade.summary}</p>}

      {/* The narrative is additive: with the LLM off, or after a failed call to
          write one, everything below still stands on its own. */}
      {grade.narrative && <NarrativePanel narrative={grade.narrative} />}

      {mayReview && <ReviewPanel />}
      {mode === 'generated' && !mayReview && (
        <p className="aside">
          This was an unreviewed practice case. Certified EMTs can approve it
          into the shared library.
        </p>
      )}

      {grade.breakdown.length > 0 && (
        <section className="panel">
          <h2>How the points were reached</h2>
          <table className="breakdown">
            <tbody>
              {grade.breakdown.map(([label, earned, possible]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{earned}{possible > 0 && <span className="of"> / {possible}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {grade.critical_errors.length > 0 && (
        <section className="panel panel--critical">
          <h2>Critical</h2>
          <ul>
            {grade.critical_errors.map((e, i) => (
              <li key={i}>
                <p>{e.detail}</p>
                {e.guidance && <p className="guidance">Instead: {e.guidance}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* What to fix first, pulled out of the full list so it is not buried. */}
      {missed.length > 0 && (
        <section className="panel panel--focus">
          <h2>What to work on</h2>
          <ol>
            {missed.map((a) => {
              const { text } = splitCitations(a.action)
              return <li key={a.index}>{text}</li>
            })}
          </ol>
        </section>
      )}

      <section className="panel">
        <h2>Scene size-up · {grade.size_up.score}/5</h2>
        <ul className="checklist">
          {grade.size_up.covered.map((item) => (
            <li key={item} className="ok">✓ {SIZE_UP_LABEL[item] ?? item}</li>
          ))}
          {grade.size_up.missed.map((item) => (
            <li key={item} className="miss">
              ✗ {SIZE_UP_LABEL[item] ?? item} — not stated
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>The call, step by step</h2>
        <ol className="actions">
          {grade.actions.map((a) => {
            const { text, cites } = splitCitations(a.action)
            return (
              <li key={a.index} className={`action action--${a.status}`}>
                <span className="mark" aria-label={STATUS_LABEL[a.status]}>
                  {MARK[a.status]}
                </span>
                <div>
                  <p className="step">{text}</p>
                  {/* What you actually said, so you can tell a wording problem
                      from a clinical one. */}
                  {a.said && <p className="said">You said: “{a.said}”</p>}
                  {a.note && <p className="note">{a.note}</p>}
                  {cites.length > 0 && (
                    <p className="cites">{cites.join(' ')}</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
        {grade.out_of_order > 0 && (
          <p className="aside">{grade.out_of_order} step(s) were done out of sequence.</p>
        )}
        {grade.turns_to_first_intervention && (
          <p className="aside">
            First intervention came on turn {grade.turns_to_first_intervention}.
          </p>
        )}
      </section>

      {/* The reasoning behind the answer key, written by the EMT who vetted the
          case. This is the part that explains *why*, and it was never shown. */}
      {grade.rationale && (
        <section className="panel panel--why">
          <h2>Why these are the right steps</h2>
          {grade.rationale.split(/\n{2,}/).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </section>
      )}

      <section className="panel">
        <h2>What this call turned on</h2>
        {/* Not scored, and no longer marked caught or missed. Catching one used
            to mean saying it out loud, and nobody narrates "cold, clammy skin
            with tachycardia" on a real call — they act on it. These are here to
            be read after the fact, which is what they were always good for. */}
        <p className="hint">
          The findings this case was built around. Nothing here costs you points.
        </p>
        <ul className="checklist">
          {[...grade.red_flags_caught, ...grade.red_flags_missed].map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </section>

      <footer className="sources">
        Every claim above traces to EMT-vetted content: {grade.citations.join('  ')}
      </footer>
    </article>
  )
}
