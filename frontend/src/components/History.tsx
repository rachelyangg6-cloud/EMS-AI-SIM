import { actions, useStore } from '../store'
import type { HistoryEntry } from '../types'

/**
 * Past calls, and one of them opened up.
 *
 * Everything here was already being written on every turn — `record_turns` runs
 * per request and `finish_session` stores the grade. This is the screen that
 * finally shows it.
 */

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })

/** An ended call has a result; one that was abandoned mid-shift does not.
 *
 *  Three cases, not two. A row written before the score stopped being a
 *  percentage has `points_possible === null`, and showing its 72 as "72/27"
 *  would be a lie about a call that was never measured that way.
 */
function Score({ entry }: { entry: HistoryEntry }) {
  if (entry.ended_at === null) return <span className="score score--none">unfinished</span>
  if (entry.score === null) return <span className="score score--none">—</span>
  if (entry.points_possible === null) {
    return <span className="score score--none">{entry.score}% (old scale)</span>
  }
  return (
    <span className={`score score--${entry.passed ? 'good' : 'poor'}`}>
      {entry.passed ? 'Pass' : 'Fail'}{' '}
      <span className="score-points">
        {entry.score}/{entry.points_possible}
      </span>
    </span>
  )
}

function Detail() {
  const detail = useStore((s) => s.historyDetail)
  if (!detail) return null

  const grade = detail.grade
  return (
    <section className="history-detail" aria-label="One past call">
      <header className="row">
        <div>
          <h2>{detail.scenario_id}</h2>
          <p className="sub">
            {when(detail.started_at)} · {detail.difficulty || 'unrated'}
            {detail.mode === 'generated' && ' · unreviewed draft'}
          </p>
        </div>
        <button type="button" className="ghost" onClick={actions.closeHistoryEntry}>
          Close
        </button>
      </header>

      {grade?.summary && <p className="lede">{grade.summary}</p>}

      {grade && (
        <ul className="history-marks">
          <li>
            <strong>{grade.passed ? 'Pass' : 'Fail'}</strong> ·{' '}
            {grade.points}/{grade.points_possible} points
          </li>
          <li>
            <strong>{grade.red_flags_caught.length}</strong> of{' '}
            {grade.red_flags_caught.length + grade.red_flags_missed.length} red flags caught
          </li>
          {grade.critical_errors.length > 0 && (
            <li className="bad">
              <strong>{grade.critical_errors.length}</strong> critical{' '}
              {grade.critical_errors.length === 1 ? 'error' : 'errors'}
            </li>
          )}
        </ul>
      )}

      <h3>What was said</h3>
      <ol className="history-turns">
        {detail.turns.map((turn) => (
          <li key={turn.seq} className={`turn turn--${turn.speaker}`}>
            <span className="turn-speaker">{turn.speaker}</span>
            <span className="turn-text">{turn.utterance}</span>
          </li>
        ))}
      </ol>
      {detail.turns.length === 0 && <p className="hint">Nothing was said on this call.</p>}
    </section>
  )
}

export function History() {
  const sessions = useStore((s) => s.history)
  const detail = useStore((s) => s.historyDetail)
  const busy = useStore((s) => s.busy)
  const error = useStore((s) => s.error)

  return (
    <div className="card history">
      <header className="row">
        <div>
          <h1>Past calls</h1>
          <p className="sub">Every call you have run, with what you said and how it graded.</p>
        </div>
        <button type="button" className="ghost" onClick={actions.backToMenu}>
          Back
        </button>
      </header>

      {error && <p className="error">{error}</p>}
      {busy && sessions.length === 0 && <p className="hint">Loading…</p>}
      {!busy && sessions.length === 0 && (
        <p className="hint">
          No calls yet. Run one from the menu and it will be waiting here afterwards.
        </p>
      )}

      {sessions.length > 0 && (
        <ul className="history-list">
          {sessions.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className={`history-row ${detail?.id === entry.id ? 'is-open' : ''}`}
                onClick={() => void actions.openHistoryEntry(entry.id)}
              >
                <span className="history-when">{when(entry.started_at)}</span>
                <span className="history-what">{entry.scenario_id}</span>
                <span className="history-level">{entry.difficulty || '—'}</span>
                <Score entry={entry} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <Detail />
    </div>
  )
}
